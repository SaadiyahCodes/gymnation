# NOTES

## How to run
```
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest -q
uvicorn app.main:app --host 0.0.0.0 --port 8080
```
Docker: `docker build --target test .`, then `docker build -t app .` and `docker run -p 8080:8080 app`.

Stack: Python 3.12, FastAPI, in-memory state (each run starts empty).

## Layout
- `app/phone.py`    phone cleaning and normalisation (pure)
- `app/money.py`    integer half-up rounding, VAT, currency per country (pure)
- `app/schedule.py` due dates, proration, invoice schedule (pure)
- `app/store.py`    in-memory stores; check+insert under a lock
- `app/main.py`     routes, strict hand-written validation, error handlers

## Status
- Part 1 (members + phones): done.
- Part 2 (plans, agreements, invoice schedule): done.
- Part 3 (reconciliation): not started.

## Assumptions: general
- Bodies and query strings are parsed by hand (no Pydantic models) so every bad input yields the contract error shape.
- Validation order: shape/types/ranges (422 VALIDATION) first, then business rules, then uniqueness (409).
- Integers must be real JSON integers: `true`, `299.0`, `"299"` are all 422 VALIDATION.
- Dates must match `YYYY-MM-DD` with ASCII digits and be a real calendar date (`20260920`, `2026-9-20`, `2026-02-30` are 422).
- All money is integer minor units; rounding is integer half-up, with no floats anywhere.

## Assumptions: Part 1 (members and phones)
- Lookup order: `country` value checked, then `phone` presence, then phone semantics.
- Only literal space, hyphen, `(` and `)` are stripped; tabs/other whitespace -> INVALID_PHONE.
- Digits must be ASCII 0-9 (Arabic-Indic digits are INVALID_PHONE).
- Lookup with a number that fits no valid shape and no `country` -> INVALID_PHONE (not NEEDS_COUNTRY).
- An unencoded `+` in a query string becomes a space and is stripped, so it still resolves.
- Name length counts characters (code points), after trimming.
- Uniqueness: a threading lock wraps check+insert in the store.

## Assumptions: Part 2 (plans, agreements, invoices)
- Plan `id` must be a non-empty string; no trimming and no length limit.
- Plan duplicate check and insert happen under one lock (409 PLAN_EXISTS holds under races).
- Agreement check order: shape (VALIDATION), then UNKNOWN_MEMBER, then UNKNOWN_PLAN, then PLAN_COUNTRY_MISMATCH.
- Invoices check order: `from`/`to` present and well-formed (VALIDATION), then unknown agreement (404), then INVALID_RANGE.
- A range of exactly 366 days (to - from = 366) is allowed; 367 is INVALID_RANGE.
- A range with no invoices returns `200 []`.
- Due date in a month = min(due_day, days in month); the anchor stays due_day, only the date clamps.
- N = first due date strictly after start; P = due date of the month before N's month (computed from the anchor, not by subtracting a month from N's clamped date).
- Invoice k >= 2 is due in month index (N's month + k - 2); invoice_no is computed from that position, so it never restarts inside a range and nothing is stored.
- Rounding happens exactly twice per invoice: prorated amount, then VAT on (prorated + joining_fee). Joining fee is on invoice 1 only.
- VAT rates: AE 5%, SA 15%, BH 10%, applied as integer percent in minor units.

## Skipped / known limits
- A start date or range at the very end of year 9999 would overflow Python's date type (returns 500). Considered out of scope.
- No persistence: state is lost on restart, as the brief allows.