"""Invoice schedule (Part 2). Pure functions: no HTTP, no storage.

Months are handled as a single integer index (year * 12 + month - 1) so that
"one month before/after" never needs date arithmetic on a clamped day.
The anchor (due_day) never changes; only the date of a given month clamps.
"""
import calendar
from datetime import date

from .money import CURRENCY, round_div, vat


def _idx(d: date) -> int:
    return d.year * 12 + d.month - 1


def due_in_month(idx: int, due_day: int) -> date:
    """min(due_day, days in that month) for the month with this index."""
    y, m = divmod(idx, 12)
    m += 1
    return date(y, m, min(due_day, calendar.monthrange(y, m)[1]))


def first_cycle_index(start: date, due_day: int) -> int:
    """Month index of N: the first due date strictly after start."""
    i = _idx(start)
    return i if due_in_month(i, due_day) > start else i + 1


def first_invoice(start, due_day, monthly, joining_fee, country) -> dict:
    n_idx = first_cycle_index(start, due_day)
    n = due_in_month(n_idx, due_day)
    p = due_in_month(n_idx - 1, due_day)
    days, cycle = (n - start).days, (n - p).days
    net = round_div(monthly * days, cycle) + joining_fee
    return _make(1, start, "FIRST", {"days": days, "cycle_days": cycle}, net, country)


def _make(no, due, kind, proration, net, country) -> dict:
    v = vat(net, country)
    return {"invoice_no": no, "due_date": due.isoformat(), "kind": kind,
            "proration": proration, "net": net, "vat": v, "total": net + v,
            "currency": CURRENCY[country]}


def invoices_in_range(start: date, due_day: int, monthly: int, joining_fee: int,
                      country: str, frm: date, to: date) -> list[dict]:
    """Invoices whose due_date is in [frm, to], with whole-schedule invoice_no."""
    out = []
    if frm <= start <= to:
        out.append(first_invoice(start, due_day, monthly, joining_fee, country))
    n_idx = first_cycle_index(start, due_day)
    # invoice k >= 2 is due in month n_idx + (k - 2); due dates only increase with k
    for m in range(max(n_idx, _idx(frm)), _idx(to) + 1):
        d = due_in_month(m, due_day)
        if frm <= d <= to:
            out.append(_make(m - n_idx + 2, d, "MONTHLY", None, monthly, country))
    return out