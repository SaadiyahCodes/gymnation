from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from app import main
from app.store import MemberStore


@pytest.fixture()
def client():
    main.members = MemberStore()
    return TestClient(main.app)


def post(c, **kw):
    body = {"name": "Noura Al Harbi", "country": "SA", "phone": "055 123 4567"}
    body.update(kw)
    return c.post("/members", json=body)


def code(r):
    return r.json()["error"]["code"]


def test_health(client):
    assert client.get("/health").status_code == 200


def test_create_national(client):
    r = post(client)
    assert r.status_code == 201
    b = r.json()
    assert b["phone"] == "+966551234567" and b["country"] == "SA" and b["id"]


def test_name_trimmed_and_limits(client):
    assert post(client, name="  Bob  ").json()["name"] == "Bob"
    assert code(post(client, name="   ", phone="0551111111")) == "VALIDATION"
    assert code(post(client, name="x" * 121, phone="0552222222")) == "VALIDATION"
    assert post(client, name="x" * 120, phone="0553333333").status_code == 201


@pytest.mark.parametrize("patch", [
    {"name": 5}, {"country": "US"}, {"country": None}, {"phone": 55}, {"phone": None},
])
def test_shape_errors(client, patch):
    r = post(client, **patch)
    assert r.status_code == 422 and code(r) == "VALIDATION"


def test_bad_json_and_non_object(client):
    r = client.post("/members", content="{nope", headers={"content-type": "application/json"})
    assert r.status_code == 422 and code(r) == "VALIDATION"
    assert code(client.post("/members", json=[1])) == "VALIDATION"


@pytest.mark.parametrize("phone", [
    "00966551234567", "+0551234567", "05512345", "0451234567", "055-123-45x7",
    "++966551234567", "966 55 123 456", "٠٥٥١٢٣٤٥٦٧", "", "+966-5-5123-4567-0",
    "0551234567 ", "\t0551234567",
])
def test_invalid_phone(client, phone):
    r = post(client, phone=phone)
    if phone == "0551234567 ":
        assert r.status_code == 201  # trailing literal space is stripped
    else:
        assert r.status_code == 422 and code(r) == "INVALID_PHONE"


def test_all_spellings_collide(client):
    first = post(client).json()
    for p in ["+966551234567", "966551234567", "0551234567", "+966 (55) 123-4567"]:
        r = post(client, name="Other", phone=p)
        assert r.status_code == 409
        e = r.json()["error"]
        assert e["code"] == "PHONE_TAKEN" and e["existing_member_id"] == first["id"]


def test_national_read_in_member_country(client):
    ae = post(client, country="AE", phone="0551234567").json()
    assert ae["phone"] == "+971551234567"
    bh = post(client, country="BH", phone="3123 4567").json()
    assert bh["phone"] == "+97331234567"


def test_national_wrong_shape_for_country(client):
    assert code(post(client, country="BH", phone="0551234567")) == "INVALID_PHONE"
    assert code(post(client, country="SA", phone="31234567")) == "INVALID_PHONE"


def test_foreign_sim_allowed(client):
    r = post(client, country="SA", phone="+97331234567")
    assert r.status_code == 201 and r.json()["phone"] == "+97331234567"


def test_lookup_three_spellings(client):
    m = post(client).json()
    for url in [
        "/members/lookup?phone=966551234567",
        "/members/lookup?phone=%2B966551234567",
        "/members/lookup?phone=055%20123%204567&country=SA",
    ]:
        r = client.get(url)
        assert r.status_code == 200 and r.json() == m


def test_lookup_unencoded_plus(client):
    m = post(client).json()
    assert client.get("/members/lookup?phone=+966551234567").json() == m


def test_lookup_errors(client):
    post(client)
    r = client.get("/members/lookup?phone=0551234567")
    assert r.status_code == 422 and code(r) == "PHONE_NEEDS_COUNTRY"
    r = client.get("/members/lookup?phone=" + quote("+966551234567") + "&country=AE")
    assert r.status_code == 422 and code(r) == "PHONE_COUNTRY_MISMATCH"
    assert code(client.get("/members/lookup?phone=0551234567&country=BH")) == "INVALID_PHONE"
    assert code(client.get("/members/lookup?phone=00966551234567")) == "INVALID_PHONE"
    assert code(client.get("/members/lookup")) == "VALIDATION"
    assert code(client.get("/members/lookup?phone=0551234567&country=XX")) == "VALIDATION"
    r = client.get("/members/lookup?phone=0559999999&country=SA")
    assert r.status_code == 404 and code(r) == "NOT_FOUND"


def test_lookup_country_matches_dial(client):
    m = post(client).json()
    assert client.get("/members/lookup?phone=966551234567&country=SA").json() == m


def test_unknown_route_shape(client):
    r = client.get("/nope")
    assert r.status_code == 404 and code(r) == "NOT_FOUND"


def test_concurrent_same_phone_one_wins(client):
    spellings = ["+966551234567", "966551234567", "0551234567", "055 123 4567"] * 5

    def go(p):
        return post(client, phone=p).status_code

    with ThreadPoolExecutor(20) as ex:
        results = list(ex.map(go, spellings))
    assert results.count(201) == 1 and results.count(409) == 19