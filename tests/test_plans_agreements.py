from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from app import main
from app.store import AgreementStore, MemberStore, PlanStore


@pytest.fixture()
def client():
    main.members, main.plans, main.agreements = MemberStore(), PlanStore(), AgreementStore()
    return TestClient(main.app)


def code(r):
    return r.json()["error"]["code"]


def mk_plan(c, **kw):
    body = {"id": "anytime-sa", "country": "SA", "monthly": 29900, "joining_fee": 0}
    body.update(kw)
    return c.post("/plans", json=body)


def mk_member(c, country="SA", phone="0551234567"):
    return c.post("/members", json={"name": "Noura", "country": country, "phone": phone}).json()


def mk_agreement(c, member, plan_id="anytime-sa", **kw):
    body = {"member_id": member["id"], "plan_id": plan_id, "start_date": "2026-09-20", "due_day": 1}
    body.update(kw)
    return c.post("/agreements", json=body)


# ---------- plans ----------

def test_create_plan_currency_from_country(client):
    r = mk_plan(client)
    assert r.status_code == 201
    assert r.json() == {"id": "anytime-sa", "country": "SA", "currency": "SAR",
                        "monthly": 29900, "joining_fee": 0}
    assert mk_plan(client, id="bh", country="BH").json()["currency"] == "BHD"
    assert mk_plan(client, id="ae", country="AE").json()["currency"] == "AED"


def test_duplicate_plan(client):
    mk_plan(client)
    r = mk_plan(client, monthly=1)
    assert r.status_code == 409 and code(r) == "PLAN_EXISTS"


@pytest.mark.parametrize("patch", [
    {"id": ""}, {"id": 5}, {"id": None}, {"country": "US"}, {"country": None},
    {"monthly": 0}, {"monthly": -1}, {"monthly": 299.5}, {"monthly": 299.0},
    {"monthly": True}, {"monthly": "299"}, {"monthly": None},
    {"joining_fee": -1}, {"joining_fee": 1.5}, {"joining_fee": False}, {"joining_fee": None},
])
def test_plan_validation(client, patch):
    r = mk_plan(client, **patch)
    assert r.status_code == 422 and code(r) == "VALIDATION"


def test_plan_missing_fields_and_bad_body(client):
    assert code(client.post("/plans", json={})) == "VALIDATION"
    assert code(client.post("/plans", json=[1])) == "VALIDATION"
    r = client.post("/plans", content="{x", headers={"content-type": "application/json"})
    assert r.status_code == 422 and code(r) == "VALIDATION"


def test_concurrent_same_plan_one_wins(client):
    def go(_):
        return mk_plan(client).status_code
    with ThreadPoolExecutor(20) as ex:
        results = list(ex.map(go, range(20)))
    assert results.count(201) == 1 and results.count(409) == 19


# ---------- agreements ----------

def test_create_agreement(client):
    mk_plan(client)
    m = mk_member(client)
    r = mk_agreement(client, m)
    assert r.status_code == 201
    b = r.json()
    assert b["id"] and b["member_id"] == m["id"] and b["plan_id"] == "anytime-sa"
    assert b["start_date"] == "2026-09-20" and b["due_day"] == 1
    assert mk_agreement(client, m).status_code == 201  # several agreements allowed


def test_agreement_business_errors(client):
    mk_plan(client)
    mk_plan(client, id="bh-plan", country="BH")
    m = mk_member(client)
    r = mk_agreement(client, {"id": "nope"})
    assert r.status_code == 422 and code(r) == "UNKNOWN_MEMBER"
    r = mk_agreement(client, m, plan_id="nope")
    assert r.status_code == 422 and code(r) == "UNKNOWN_PLAN"
    r = mk_agreement(client, m, plan_id="bh-plan")
    assert r.status_code == 422 and code(r) == "PLAN_COUNTRY_MISMATCH"


@pytest.mark.parametrize("patch", [
    {"member_id": 5}, {"member_id": None}, {"plan_id": 5}, {"plan_id": None},
    {"start_date": "20260920"}, {"start_date": "2026-9-20"}, {"start_date": "2026-02-30"},
    {"start_date": "2026-09-20T00:00:00"}, {"start_date": " 2026-09-20"}, {"start_date": 20260920},
    {"start_date": None}, {"start_date": "٢٠٢٦-٠٩-٢٠"},
    {"due_day": 0}, {"due_day": 32}, {"due_day": 1.5}, {"due_day": 1.0}, {"due_day": True},
    {"due_day": "1"}, {"due_day": None},
])
def test_agreement_validation(client, patch):
    mk_plan(client)
    m = mk_member(client)
    r = mk_agreement(client, m, **patch)
    assert r.status_code == 422 and code(r) == "VALIDATION"


def test_agreement_missing_field(client):
    assert code(client.post("/agreements", json={})) == "VALIDATION"


def test_agreement_shape_checked_before_lookups(client):
    # bad due_day wins over unknown member/plan
    r = client.post("/agreements", json={"member_id": "x", "plan_id": "y",
                                         "start_date": "2026-09-20", "due_day": 99})
    assert code(r) == "VALIDATION"


# ---------- invoices ----------

def setup_sa(c, **agreement_kw):
    mk_plan(c)
    m = mk_member(c)
    return mk_agreement(c, m, **agreement_kw).json()


def test_invoices_brief_example(client):
    ag = setup_sa(client)
    r = client.get(f"/agreements/{ag['id']}/invoices?from=2026-09-01&to=2026-12-31")
    assert r.status_code == 200
    b = r.json()
    assert b[0] == {"invoice_no": 1, "due_date": "2026-09-20", "kind": "FIRST",
                    "proration": {"days": 11, "cycle_days": 30},
                    "net": 10963, "vat": 1644, "total": 12607, "currency": "SAR"}
    assert b[1] == {"invoice_no": 2, "due_date": "2026-10-01", "kind": "MONTHLY",
                    "proration": None, "net": 29900, "vat": 4485, "total": 34385, "currency": "SAR"}
    assert [i["invoice_no"] for i in b] == [1, 2, 3, 4]


def test_invoices_ae_joining_fee_example(client):
    mk_plan(client, id="ae", country="AE", monthly=24900, joining_fee=9900)
    m = mk_member(client, "AE", "0501234567")
    ag = mk_agreement(client, m, plan_id="ae", start_date="2026-09-05", due_day=20).json()
    b = client.get(f"/agreements/{ag['id']}/invoices?from=2026-09-01&to=2026-09-30").json()
    assert [(i["invoice_no"], i["due_date"]) for i in b] == [(1, "2026-09-05"), (2, "2026-09-20")]
    assert (b[0]["net"], b[0]["vat"], b[0]["total"], b[0]["currency"]) == (21948, 1097, 23045, "AED")


def test_invoices_range_keeps_numbering(client):
    ag = setup_sa(client)
    b = client.get(f"/agreements/{ag['id']}/invoices?from=2026-11-01&to=2026-11-01").json()
    assert [i["invoice_no"] for i in b] == [3]


def test_invoices_empty_range_is_empty_list(client):
    ag = setup_sa(client)
    r = client.get(f"/agreements/{ag['id']}/invoices?from=2026-01-01&to=2026-01-31")
    assert r.status_code == 200 and r.json() == []


def test_invoices_range_errors(client):
    ag = setup_sa(client)
    base = f"/agreements/{ag['id']}/invoices"
    r = client.get(base + "?from=2026-10-02&to=2026-10-01")
    assert r.status_code == 422 and code(r) == "INVALID_RANGE"
    assert client.get(base + "?from=2026-01-01&to=2027-01-02").status_code == 200   # exactly 366 days
    r = client.get(base + "?from=2026-01-01&to=2027-01-03")                         # 367 days
    assert r.status_code == 422 and code(r) == "INVALID_RANGE"
    assert client.get(base + "?from=2028-01-01&to=2029-01-01").status_code == 200   # leap year, 366 days
    assert client.get(base + "?from=2028-01-01&to=2029-01-02").status_code == 422   # 367 days


@pytest.mark.parametrize("qs", ["", "?from=2026-09-01", "?to=2026-09-30",
                                "?from=20260901&to=2026-09-30", "?from=2026-09-01&to=2026-13-01",
                                "?from=&to="])
def test_invoices_query_validation(client, qs):
    ag = setup_sa(client)
    r = client.get(f"/agreements/{ag['id']}/invoices{qs}")
    assert r.status_code == 422 and code(r) == "VALIDATION"


def test_invoices_unknown_agreement(client):
    r = client.get("/agreements/nope/invoices?from=2026-09-01&to=2026-09-30")
    assert r.status_code == 404 and code(r) == "NOT_FOUND"


def test_invoices_due_day_31(client):
    mk_plan(client, id="p", monthly=10000)
    m = mk_member(client)
    ag = mk_agreement(client, m, plan_id="p", start_date="2026-01-31", due_day=31).json()
    b = client.get(f"/agreements/{ag['id']}/invoices?from=2026-01-01&to=2026-04-30").json()
    assert [i["due_date"] for i in b] == ["2026-01-31", "2026-02-28", "2026-03-31", "2026-04-30"]