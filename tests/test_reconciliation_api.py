import random

import pytest
from fastapi.testclient import TestClient

from app import main
from app.store import AgreementStore, MemberStore, PlanStore, RunStore


@pytest.fixture()
def client():
    main.members, main.plans, main.agreements = MemberStore(), PlanStore(), AgreementStore()
    main.runs = RunStore()
    return TestClient(main.app)


def code(r):
    return r.json()["error"]["code"]


def setup_world(c):
    """SA agreement (Oct invoice #2 = 34385) and BH agreement (Oct invoice #2 = 26950)."""
    c.post("/plans", json={"id": "sa", "country": "SA", "monthly": 29900, "joining_fee": 0})
    c.post("/plans", json={"id": "bh", "country": "BH", "monthly": 24500, "joining_fee": 0})
    sa = c.post("/members", json={"name": "Noura", "country": "SA", "phone": "0551234567"}).json()
    bh = c.post("/members", json={"name": "Yusuf", "country": "BH", "phone": "31234567"}).json()
    a = c.post("/agreements", json={"member_id": sa["id"], "plan_id": "sa",
                                    "start_date": "2026-09-20", "due_day": 1}).json()
    b = c.post("/agreements", json={"member_id": bh["id"], "plan_id": "bh",
                                    "start_date": "2026-09-20", "due_day": 1}).json()
    return a["id"], b["id"]


def row(txn, ag, amount=34385, cur="SAR", status="SETTLED", on="2026-10-01"):
    return {"gateway_txn_id": txn, "agreement_id": ag, "amount": amount, "currency": cur,
            "status": status, "attempted_on": on}


def run(c, rows, month="2026-10"):
    return c.post("/reconciliation/runs", json={"month": month, "rows": rows})


def test_brief_example_end_to_end(client):
    a, b = setup_world(client)
    r = run(client, [row("T-88121", a),
                     row("T-88122", b, amount=26950, cur="BHD", status="DECLINED", on="2026-10-02")])
    assert r.status_code == 201
    body = r.json()
    assert body["id"] and body["month"] == "2026-10"
    assert body["summary"] == {"MATCHED": 1, "DUE_DAY_DRIFT": 0, "DOUBLE_CHARGE_RISK": 0,
                               "MISSING_FROM_LEDGER": 0, "DECLINED": 1}
    assert body["rows"] == [
        {"gateway_txn_id": "T-88121", "verdict": "MATCHED", "invoice": {"agreement_id": a, "invoice_no": 2}},
        {"gateway_txn_id": "T-88122", "verdict": "DECLINED", "invoice": None}]
    assert body["unmatched_invoices"] == [{"agreement_id": b, "invoice_no": 2,
                                           "due_date": "2026-10-01", "total": 26950, "currency": "BHD"}]
    got = client.get(f"/reconciliation/runs/{body['id']}")
    assert got.status_code == 200 and got.json() == body


def test_all_verdicts(client):
    a, b = setup_world(client)
    body = run(client, [
        row("m", a), row("d", b, amount=26950, cur="BHD", on="2026-10-05"),
        row("x1", a, amount=34384), row("miss", "ghost-agreement", cur="USD"),
        row("dec", a, status="DECLINED")]).json()
    # m and x1 both land on invoice A#2 -> double charge
    v = {r["gateway_txn_id"]: r["verdict"] for r in body["rows"]}
    assert v == {"m": "DOUBLE_CHARGE_RISK", "x1": "DOUBLE_CHARGE_RISK", "d": "DUE_DAY_DRIFT",
                 "miss": "MISSING_FROM_LEDGER", "dec": "DECLINED"}
    assert body["summary"] == {"MATCHED": 0, "DUE_DAY_DRIFT": 1, "DOUBLE_CHARGE_RISK": 2,
                               "MISSING_FROM_LEDGER": 1, "DECLINED": 1}
    assert body["unmatched_invoices"] == []


def test_empty_rows_lists_all_invoices_unmatched_sorted(client):
    a, b = setup_world(client)
    body = run(client, []).json()
    assert body["rows"] == [] and sum(body["summary"].values()) == 0
    assert [(u["agreement_id"], u["invoice_no"]) for u in body["unmatched_invoices"]] == \
        sorted([(a, 2), (b, 2)])


def test_two_invoices_in_one_month_for_one_agreement(client):
    client.post("/plans", json={"id": "ae", "country": "AE", "monthly": 24900, "joining_fee": 9900})
    m = client.post("/members", json={"name": "Omar", "country": "AE", "phone": "0501234567"}).json()
    ag = client.post("/agreements", json={"member_id": m["id"], "plan_id": "ae",
                                          "start_date": "2026-09-05", "due_day": 20}).json()["id"]
    body = run(client, [row("a", ag, amount=23045, cur="AED", on="2026-09-05"),
                        row("b", ag, amount=26145, cur="AED", on="2026-09-21")], month="2026-09").json()
    assert [(r["verdict"], r["invoice"]["invoice_no"]) for r in body["rows"]] == \
        [("MATCHED", 1), ("DUE_DAY_DRIFT", 2)]
    assert body["unmatched_invoices"] == []


def test_row_order_does_not_change_result(client):
    a, b = setup_world(client)
    rows = [row("1", a), row("2", a, on="2026-10-03"), row("3", b, amount=26950, cur="BHD"),
            row("4", "ghost"), row("5", b, amount=1, cur="BHD", status="DECLINED")]
    base = run(client, rows).json()
    base_v = {r["gateway_txn_id"]: (r["verdict"], r["invoice"]) for r in base["rows"]}
    rng = random.Random(3)
    for _ in range(5):
        shuffled = rows[:]
        rng.shuffle(shuffled)
        res = run(client, shuffled).json()
        assert {r["gateway_txn_id"]: (r["verdict"], r["invoice"]) for r in res["rows"]} == base_v
        assert res["summary"] == base["summary"] and res["unmatched_invoices"] == base["unmatched_invoices"]
        assert [r["gateway_txn_id"] for r in res["rows"]] == [r["gateway_txn_id"] for r in shuffled]


# ---------- validation ----------

@pytest.mark.parametrize("month", ["2026-13", "2026-00", "202610", "2026-1", "2026-10-01",
                                   "٢٠٢٦-١٠", "0000-10", 202610, None, ""])
def test_bad_month(client, month):
    setup_world(client)
    r = client.post("/reconciliation/runs", json={"month": month, "rows": []})
    assert r.status_code == 422 and code(r) == "VALIDATION"


@pytest.mark.parametrize("patch", [
    {"gateway_txn_id": 5}, {"gateway_txn_id": ""}, {"gateway_txn_id": None},
    {"agreement_id": 5}, {"agreement_id": None},
    {"amount": 0}, {"amount": -5}, {"amount": 1.5}, {"amount": 34385.0}, {"amount": True},
    {"amount": "34385"}, {"amount": None},
    {"currency": 5}, {"currency": None},
    {"status": "PENDING"}, {"status": "settled"}, {"status": None},
    {"attempted_on": "20261001"}, {"attempted_on": "2026-10-1"}, {"attempted_on": "2026-02-30"},
    {"attempted_on": None}, {"attempted_on": 5},
])
def test_bad_row_field(client, patch):
    a, _ = setup_world(client)
    r = run(client, [{**row("t", a), **patch}])
    assert r.status_code == 422 and code(r) == "VALIDATION"


def test_missing_fields_and_bad_shapes(client):
    a, _ = setup_world(client)
    for key in ["gateway_txn_id", "agreement_id", "amount", "currency", "status", "attempted_on"]:
        r = row("t", a)
        del r[key]
        assert code(run(client, [r])) == "VALIDATION", key
    assert code(client.post("/reconciliation/runs", json={"month": "2026-10"})) == "VALIDATION"
    assert code(client.post("/reconciliation/runs", json={"rows": []})) == "VALIDATION"
    assert code(client.post("/reconciliation/runs", json={"month": "2026-10", "rows": {}})) == "VALIDATION"
    assert code(run(client, ["nope"])) == "VALIDATION"
    assert code(client.post("/reconciliation/runs", json=[1])) == "VALIDATION"
    r = client.post("/reconciliation/runs", content="{x", headers={"content-type": "application/json"})
    assert r.status_code == 422 and code(r) == "VALIDATION"


def test_shape_error_beats_invalid_rows(client):
    a, _ = setup_world(client)
    r = run(client, [row("dup", a), row("dup", a), row("bad", a, amount=0)])
    assert code(r) == "VALIDATION"


def errors_of(r):
    assert r.status_code == 422 and code(r) == "INVALID_ROWS"
    return sorted((e["gateway_txn_id"], e["code"]) for e in r.json()["error"]["errors"])


def test_invalid_rows_each_code(client):
    a, b = setup_world(client)
    assert errors_of(run(client, [row("d", a), row("d", a, on="2026-10-02"), row("ok", a)])) == \
        [("d", "DUPLICATE_TXN")] * 2
    assert errors_of(run(client, [row("o", a, on="2026-11-01")])) == [("o", "ROW_OUTSIDE_MONTH")]
    assert errors_of(run(client, [row("c", a, cur="BHD")])) == [("c", "CURRENCY_MISMATCH")]


def test_unknown_agreement_skips_currency_check(client):
    setup_world(client)
    r = run(client, [row("u", "ghost", cur="JPY")])
    assert r.status_code == 201 and r.json()["rows"][0]["verdict"] == "MISSING_FROM_LEDGER"


def test_invalid_rows_collects_all_offenders_and_run_not_stored(client):
    a, b = setup_world(client)
    r = run(client, [row("d", a), row("d", a), row("o", a, on="2026-09-30"), row("c", b), row("fine", a)])
    assert errors_of(r) == sorted([("d", "DUPLICATE_TXN"), ("d", "DUPLICATE_TXN"),
                                   ("o", "ROW_OUTSIDE_MONTH"), ("c", "CURRENCY_MISMATCH")])


def test_declined_rows_are_validated_too(client):
    a, _ = setup_world(client)
    assert errors_of(run(client, [row("x", a, status="DECLINED", on="2027-01-01")])) == \
        [("x", "ROW_OUTSIDE_MONTH")]


def test_unknown_run_is_404(client):
    r = client.get("/reconciliation/runs/nope")
    assert r.status_code == 404 and code(r) == "NOT_FOUND"


def test_run_does_not_change_agreements(client):
    a, _ = setup_world(client)
    url = f"/agreements/{a}/invoices?from=2026-09-01&to=2026-12-31"
    before = client.get(url).json()
    run(client, [row("t", a), row("u", a)])
    assert client.get(url).json() == before
    assert len(main.agreements.all()) == 2 and len(main.members._by_id) == 2