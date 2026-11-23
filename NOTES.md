# NOTES

## How to run
```
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest -q
uvicorn app.main:app --host 0.0.0.0 --port 8080
```
Docker: `docker build --target test .`, then `docker build -t app .` and `docker run -p 8080:8080 app`.

Stack: Python 3.12, FastAPI, in-memory state.

## Status
- Part 1 (members + phones): done.
- Part 2 (plans, agreements, invoice schedule): not started.
- Part 3 (reconciliation): not started.

## Assumptions
- Validation order: body shape/types/ranges (422 VALIDATION) first, then phone semantics (INVALID_PHONE etc.), then uniqueness (409).
- Lookup order: `country` value checked, then `phone` presence, then phone semantics.
- Only literal space, hyphen, `(` and `)` are stripped; tabs/other whitespace -> INVALID_PHONE.
- Digits must be ASCII 0-9 (Arabic-Indic digits are INVALID_PHONE).
- Lookup with a number that fits no valid shape and no `country` -> INVALID_PHONE (not NEEDS_COUNTRY).
- An unencoded `+` in a query string becomes a space and is stripped, so it still resolves.
- Name length counts characters (code points), after trimming.
- Uniqueness: a threading lock wraps check+insert in the store.
- Bodies are parsed by hand (no Pydantic models) so every bad input yields the contract error shape.