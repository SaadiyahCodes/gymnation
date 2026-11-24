import random

import pytest

from app.reconcile import reconcile, row_errors

MONTH = "2026-10"


def inv(no, due, total, cur="SAR"):
    return {"invoice_no": no, "due_date": due, "total": total, "currency": cur}


def row(txn, ag="A", amount=34385, status="SETTLED", on="2026-10-01", cur="SAR"):
    return {"gateway_txn_id": txn, "agreement_id": ag, "amount": amount, "currency": cur,
            "status": status, "attempted_on": on}


EXP = {"A": [inv(2, "2026-10-01", 34385)], "B": [inv(2, "2026-10-01", 26950, "BHD")]}


def verdicts(res):
    return {r["gateway_txn_id"]: r["verdict"] for r in res["rows"]}


# ---------- reconcile ----------

def test_brief_example():
    res = reconcile([row("T-88121"),
                     row("T-88122", ag="B", amount=26950, status="DECLINED", on="2026-10-02", cur="BHD")],
                    EXP)
    assert res["summary"] == {"MATCHED": 1, "DUE_DAY_DRIFT": 0, "DOUBLE_CHARGE_RISK": 0,
                              "MISSING_FROM_LEDGER": 0, "DECLINED": 1}
    assert res["rows"] == [
        {"gateway_txn_id": "T-88121", "verdict": "MATCHED",
         "invoice": {"agreement_id": "A", "invoice_no": 2}},
        {"gateway_txn_id": "T-88122", "verdict": "DECLINED", "invoice": None}]
    assert res["unmatched_invoices"] == [
        {"agreement_id": "B", "invoice_no": 2, "due_date": "2026-10-01",
         "total": 26950, "currency": "BHD"}]


def test_summary_has_every_key_even_when_empty():
    res = reconcile([], {})
    assert res == {"summary": {"MATCHED": 0, "DUE_DAY_DRIFT": 0, "DOUBLE_CHARGE_RISK": 0,
                               "MISSING_FROM_LEDGER": 0, "DECLINED": 0},
                   "rows": [], "unmatched_invoices": []}


def test_drift():
    res = reconcile([row("t", on="2026-10-04")], EXP)
    assert verdicts(res) == {"t": "DUE_DAY_DRIFT"}
    assert res["rows"][0]["invoice"] == {"agreement_id": "A", "invoice_no": 2}
    assert [u["agreement_id"] for u in res["unmatched_invoices"]] == ["B"]


@pytest.mark.parametrize("amount,want", [(34385, "MATCHED"), (34384, "MATCHED"), (34386, "MATCHED"),
                                         (34383, "MISSING_FROM_LEDGER"), (34387, "MISSING_FROM_LEDGER")])
def test_tolerance_is_within_one(amount, want):
    assert verdicts(reconcile([row("t", amount=amount)], EXP)) == {"t": want}


def test_unknown_agreement_and_no_candidate():
    res = reconcile([row("u", ag="ghost"), row("n", amount=1)], EXP)
    assert verdicts(res) == {"u": "MISSING_FROM_LEDGER", "n": "MISSING_FROM_LEDGER"}
    assert all(r["invoice"] is None for r in res["rows"])
    assert len(res["unmatched_invoices"]) == 2


def test_candidates_only_from_own_agreement():
    # B has an invoice with that amount, but the row belongs to A
    res = reconcile([row("t", ag="A", amount=26950)], EXP)
    assert verdicts(res) == {"t": "MISSING_FROM_LEDGER"}


def test_double_charge_marks_every_row():
    res = reconcile([row("a"), row("b", on="2026-10-09"), row("c", amount=34384)], EXP)
    assert verdicts(res) == {"a": "DOUBLE_CHARGE_RISK", "b": "DOUBLE_CHARGE_RISK",
                             "c": "DOUBLE_CHARGE_RISK"}
    assert all(r["invoice"] == {"agreement_id": "A", "invoice_no": 2} for r in res["rows"])
    assert [u["agreement_id"] for u in res["unmatched_invoices"]] == ["B"]


def test_declined_does_not_cause_double_charge_and_leaves_invoice_unmatched():
    res = reconcile([row("ok"), row("no", status="DECLINED")], EXP)
    assert verdicts(res) == {"ok": "MATCHED", "no": "DECLINED"}
    res = reconcile([row("no", status="DECLINED")], EXP)
    assert {u["agreement_id"] for u in res["unmatched_invoices"]} == {"A", "B"}


def test_earliest_due_date_wins_and_linked_invoices_still_count():
    exp = {"A": [inv(1, "2026-10-05", 100), inv(2, "2026-10-20", 100)]}
    res = reconcile([row("x", amount=100, on="2026-10-05")], exp)
    assert res["rows"][0]["invoice"]["invoice_no"] == 1 and res["rows"][0]["verdict"] == "MATCHED"
    assert [u["invoice_no"] for u in res["unmatched_invoices"]] == [2]
    # a second row for the same amount does NOT move on to invoice 2: both hit invoice 1
    res = reconcile([row("x", amount=100, on="2026-10-05"),
                     row("y", amount=100, on="2026-10-20")], exp)
    assert verdicts(res) == {"x": "DOUBLE_CHARGE_RISK", "y": "DOUBLE_CHARGE_RISK"}
    assert [u["invoice_no"] for u in res["unmatched_invoices"]] == [2]


def test_earliest_beats_closer_amount():
    exp = {"A": [inv(1, "2026-10-05", 101), inv(2, "2026-10-20", 100)]}
    res = reconcile([row("x", amount=100, on="2026-10-20")], exp)
    assert res["rows"][0]["invoice"]["invoice_no"] == 1


def test_rows_in_request_order():
    res = reconcile([row("z"), row("a", ag="ghost"), row("m", status="DECLINED")], EXP)
    assert [r["gateway_txn_id"] for r in res["rows"]] == ["z", "a", "m"]


def test_unmatched_sorted_by_due_then_agreement_then_invoice():
    exp = {"Z": [inv(3, "2026-10-01", 5)], "A": [inv(9, "2026-10-01", 5), inv(2, "2026-10-15", 5)],
           "M": [inv(1, "2026-10-01", 5)]}
    got = [(u["due_date"], u["agreement_id"], u["invoice_no"])
           for u in reconcile([], exp)["unmatched_invoices"]]
    assert got == [("2026-10-01", "A", 9), ("2026-10-01", "M", 1), ("2026-10-01", "Z", 3),
                   ("2026-10-15", "A", 2)]


def test_result_does_not_depend_on_row_order():
    exp = {"A": [inv(1, "2026-10-05", 100), inv(2, "2026-10-20", 101)],
           "B": [inv(2, "2026-10-01", 200)]}
    rows = [row("1", amount=100, on="2026-10-05"), row("2", amount=101, on="2026-10-20"),
            row("3", amount=101, on="2026-10-21"), row("4", ag="B", amount=200),
            row("5", ag="B", amount=200, on="2026-10-02"), row("6", ag="B", status="DECLINED", amount=200),
            row("7", ag="ghost"), row("8", amount=55)]
    base = reconcile(rows, exp)
    base_v = {r["gateway_txn_id"]: (r["verdict"], r["invoice"]) for r in base["rows"]}
    rng = random.Random(7)
    for _ in range(25):
        shuffled = rows[:]
        rng.shuffle(shuffled)
        res = reconcile(shuffled, exp)
        assert {r["gateway_txn_id"]: (r["verdict"], r["invoice"]) for r in res["rows"]} == base_v
        assert res["summary"] == base["summary"]
        assert res["unmatched_invoices"] == base["unmatched_invoices"]


# ---------- row_errors ----------

CUR = {"A": "SAR", "B": "BHD"}.get


def test_no_errors_when_clean():
    assert row_errors(MONTH, [row("a"), row("b", ag="ghost", cur="USD")], CUR) == []


def test_duplicate_txn_flags_every_copy():
    errs = row_errors(MONTH, [row("a"), row("a", on="2026-10-02"), row("b")], CUR)
    assert errs == [{"gateway_txn_id": "a", "code": "DUPLICATE_TXN"}] * 2


def test_outside_month():
    for on in ["2026-09-30", "2026-11-01", "2025-10-01"]:
        assert row_errors(MONTH, [row("a", on=on)], CUR) == [
            {"gateway_txn_id": "a", "code": "ROW_OUTSIDE_MONTH"}]
    assert row_errors(MONTH, [row("a", on="2026-10-31"), row("b", on="2026-10-01")], CUR) == []


def test_currency_mismatch_only_for_known_agreement():
    assert row_errors(MONTH, [row("a", cur="AED")], CUR) == [
        {"gateway_txn_id": "a", "code": "CURRENCY_MISMATCH"}]
    assert row_errors(MONTH, [row("a", ag="ghost", cur="AED")], CUR) == []


def test_one_row_can_break_several_rules_and_declined_rows_are_checked():
    errs = row_errors(MONTH, [row("a", status="DECLINED", on="2026-11-02", cur="AED"), row("a")], CUR)
    codes = sorted((e["gateway_txn_id"], e["code"]) for e in errs)
    assert codes == [("a", "CURRENCY_MISMATCH"), ("a", "DUPLICATE_TXN"), ("a", "DUPLICATE_TXN"),
                     ("a", "ROW_OUTSIDE_MONTH")]