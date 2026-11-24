from datetime import date as D

from app.schedule import invoices_in_range, first_invoice

WIDE = (D(2020, 1, 1), D(2020, 12, 31))


def inv(start, due_day, monthly, fee, country, frm, to):
    return invoices_in_range(D.fromisoformat(start), due_day, monthly, fee, country,
                             D.fromisoformat(frm), D.fromisoformat(to))


def test_example_1_sa():
    r = inv("2026-09-20", 1, 29900, 0, "SA", "2026-09-01", "2026-12-31")
    assert r[0] == {"invoice_no": 1, "due_date": "2026-09-20", "kind": "FIRST",
                    "proration": {"days": 11, "cycle_days": 30},
                    "net": 10963, "vat": 1644, "total": 12607, "currency": "SAR"}
    assert r[1] == {"invoice_no": 2, "due_date": "2026-10-01", "kind": "MONTHLY",
                    "proration": None, "net": 29900, "vat": 4485, "total": 34385,
                    "currency": "SAR"}
    assert [i["due_date"] for i in r] == ["2026-09-20", "2026-10-01", "2026-11-01", "2026-12-01"]
    assert [i["invoice_no"] for i in r] == [1, 2, 3, 4]


def test_example_2_ae_joining_fee_two_in_september():
    r = inv("2026-09-05", 20, 24900, 9900, "AE", "2026-09-01", "2026-10-31")
    assert r[0]["proration"] == {"days": 15, "cycle_days": 31}
    assert (r[0]["net"], r[0]["vat"], r[0]["total"]) == (21948, 1097, 23045)
    assert r[1]["due_date"] == "2026-09-20" and r[1]["invoice_no"] == 2
    assert r[1]["net"] == 24900 and r[1]["vat"] == 1245   # no joining fee again
    assert r[0]["due_date"] == "2026-09-05"


def test_start_on_due_date_is_full_price():
    r = inv("2026-09-01", 1, 29900, 0, "SA", "2026-09-01", "2026-09-30")
    assert r[0]["proration"] == {"days": 30, "cycle_days": 30}
    assert r[0]["net"] == 29900


def test_due_day_31_clamps_but_anchor_stays():
    r = inv("2026-03-31", 31, 10000, 0, "AE", "2026-03-01", "2026-06-30")
    assert [i["due_date"] for i in r] == ["2026-03-31", "2026-04-30", "2026-05-31", "2026-06-30"]
    assert r[0]["proration"] == {"days": 30, "cycle_days": 30}


def test_feb_and_leap_year():
    r = inv("2026-01-31", 31, 10000, 0, "AE", "2026-01-01", "2026-03-31")
    assert [i["due_date"] for i in r] == ["2026-01-31", "2026-02-28", "2026-03-31"]
    assert r[0]["proration"] == {"days": 28, "cycle_days": 28}
    r = inv("2028-01-31", 31, 10000, 0, "AE", "2028-02-01", "2028-02-29")
    assert [i["due_date"] for i in r] == ["2028-02-29"] and r[0]["invoice_no"] == 2


def test_start_day_before_clamped_due_across_year():
    r = inv("2026-01-30", 31, 31000, 0, "AE", "2026-01-01", "2026-01-31")
    assert r[0]["proration"] == {"days": 1, "cycle_days": 31}   # P = 31 Dec
    assert r[0]["net"] == 1000


def test_start_in_clamped_month_after_clamped_due():
    # start 28 Feb 2026, due 31: Feb due date is 28 (not after start) -> N = 31 Mar
    r = first_invoice(D(2026, 2, 28), 31, 28000, 0, "AE")
    assert r["proration"] == {"days": 31, "cycle_days": 31}


def test_start_after_due_day_in_month():
    r = first_invoice(D(2026, 9, 25), 20, 30000, 0, "SA")  # N=20 Oct, P=20 Sep
    assert r["proration"] == {"days": 25, "cycle_days": 30}


def test_invoice_no_does_not_restart_in_range():
    r = inv("2026-09-20", 1, 29900, 0, "SA", "2026-11-01", "2026-12-31")
    assert [(i["invoice_no"], i["due_date"]) for i in r] == [(3, "2026-11-01"), (4, "2026-12-01")]


def test_range_bounds_inclusive_and_empty():
    r = inv("2026-09-20", 1, 29900, 0, "SA", "2026-10-01", "2026-10-01")
    assert [i["invoice_no"] for i in r] == [2]
    assert inv("2026-09-20", 1, 29900, 0, "SA", "2026-09-21", "2026-09-30") == []
    assert inv("2026-09-20", 1, 29900, 0, "SA", "2026-01-01", "2026-09-19") == []  # before start


def test_far_future_range_numbers_correctly():
    r = inv("2026-09-20", 1, 29900, 0, "SA", "2027-09-01", "2027-09-01")
    assert r[0]["invoice_no"] == 13 and r[0]["due_date"] == "2027-09-01"


def test_bhd_in_fils():
    r = inv("2026-10-01", 1, 49000, 0, "BH", "2026-10-01", "2026-10-01")
    assert (r[0]["net"], r[0]["vat"], r[0]["total"], r[0]["currency"]) == (49000, 4900, 53900, "BHD")


def test_range_of_366_days_covers_every_month_once():
    r = inv("2026-01-15", 15, 1000, 0, "AE", "2026-01-01", "2027-01-01")
    assert [i["invoice_no"] for i in r] == list(range(1, 13))