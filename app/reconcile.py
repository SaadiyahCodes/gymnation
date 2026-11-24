"""Reconciliation (Part 3). Pure functions: no HTTP, no storage.

Inputs are plain data:
  row      = {"gateway_txn_id", "agreement_id", "amount", "currency", "status", "attempted_on"}
             (attempted_on is an already-validated YYYY-MM-DD string)
  expected = {agreement_id: [{"invoice_no", "due_date", "total", "currency"}, ...]}
             every invoice whose due_date falls in the month, for EVERY agreement

Order independence: each settled row picks its invoice on its own, from the full
list of expected invoices (an invoice already picked by another row is still a
candidate). Only after every row has picked do we count rows per invoice.
"""
from collections import Counter
from typing import Callable

VERDICTS = ("MATCHED", "DUE_DAY_DRIFT", "DOUBLE_CHARGE_RISK", "MISSING_FROM_LEDGER", "DECLINED")


def row_errors(month: str, rows: list[dict],
               currency_of: Callable[[str], str | None]) -> list[dict]:
    """INVALID_ROWS entries: one per offending row and code. Empty list = all fine.
    currency_of(agreement_id) gives the agreement's plan currency, or None if unknown."""
    seen = Counter(r["gateway_txn_id"] for r in rows)
    errors = []
    for r in rows:
        txn = r["gateway_txn_id"]
        if seen[txn] > 1:
            errors.append({"gateway_txn_id": txn, "code": "DUPLICATE_TXN"})
        if not r["attempted_on"].startswith(month + "-"):
            errors.append({"gateway_txn_id": txn, "code": "ROW_OUTSIDE_MONTH"})
        known = currency_of(r["agreement_id"])
        if known is not None and known != r["currency"]:
            errors.append({"gateway_txn_id": txn, "code": "CURRENCY_MISMATCH"})
    return errors


def _pick(row: dict, expected: dict) -> dict | None:
    """Earliest-due invoice of the row's agreement whose total is within 1 of amount."""
    cands = [i for i in expected.get(row["agreement_id"], [])
             if abs(i["total"] - row["amount"]) <= 1]
    if not cands:
        return None
    return min(cands, key=lambda i: (i["due_date"], i["invoice_no"]))


def reconcile(rows: list[dict], expected: dict) -> dict:
    """Returns {"summary", "rows", "unmatched_invoices"} (the run body minus id/month)."""
    picks: list[dict | None] = []
    for r in rows:
        picks.append(None if r["status"] == "DECLINED" else _pick(r, expected))

    # settled rows linked per invoice
    linked = Counter((r["agreement_id"], p["invoice_no"])
                     for r, p in zip(rows, picks) if p is not None)

    out_rows = []
    summary = {v: 0 for v in VERDICTS}
    for r, p in zip(rows, picks):
        if r["status"] == "DECLINED":
            verdict = "DECLINED"
        elif p is None:
            verdict = "MISSING_FROM_LEDGER"
        elif linked[(r["agreement_id"], p["invoice_no"])] >= 2:
            verdict = "DOUBLE_CHARGE_RISK"
        elif r["attempted_on"] == p["due_date"]:
            verdict = "MATCHED"
        else:
            verdict = "DUE_DAY_DRIFT"
        summary[verdict] += 1
        out_rows.append({
            "gateway_txn_id": r["gateway_txn_id"],
            "verdict": verdict,
            "invoice": ({"agreement_id": r["agreement_id"], "invoice_no": p["invoice_no"]}
                        if p is not None else None),
        })

    unmatched = [
        {"agreement_id": ag, "invoice_no": i["invoice_no"], "due_date": i["due_date"],
         "total": i["total"], "currency": i["currency"]}
        for ag, invs in expected.items() for i in invs
        if (ag, i["invoice_no"]) not in linked
    ]
    unmatched.sort(key=lambda u: (u["due_date"], u["agreement_id"], u["invoice_no"]))
    return {"summary": summary, "rows": out_rows, "unmatched_invoices": unmatched}