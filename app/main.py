"""FastAPI app (Parts 1 and 2). Run: uvicorn app.main:app --port 8080

Request bodies and query strings are read manually (not via Pydantic models) so
EVERY bad input maps to our own {"error": {...}} shape instead of FastAPI's default.
"""
import re
from datetime import date

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .errors import ApiError, validation
from .money import CURRENCY
from .phone import COUNTRIES, normalize_for_lookup, normalize_for_member
from .schedule import invoices_in_range
from .store import AgreementStore, MemberStore, PlanStore

app = FastAPI()
members = MemberStore()
plans = PlanStore()
agreements = AgreementStore()

_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")  # [0-9], not \d (no Arabic-Indic digits)


@app.exception_handler(ApiError)
async def _api_error(_: Request, exc: ApiError):
    return JSONResponse(exc.body(), status_code=exc.status)


@app.exception_handler(RequestValidationError)
async def _fastapi_validation(_: Request, exc: RequestValidationError):
    return JSONResponse(validation("Invalid request").body(), status_code=422)


@app.exception_handler(StarletteHTTPException)
async def _http_error(_: Request, exc: StarletteHTTPException):
    code = "NOT_FOUND" if exc.status_code == 404 else "HTTP_ERROR"
    return JSONResponse({"error": {"code": code, "message": str(exc.detail)}},
                        status_code=exc.status_code)


@app.exception_handler(Exception)
async def _unexpected(_: Request, exc: Exception):
    return JSONResponse({"error": {"code": "INTERNAL", "message": "Internal error"}},
                        status_code=500)


# ---------- small strict parsers ----------

async def _json_object(request: Request) -> dict:
    try:
        body = await request.json()
    except Exception:
        raise validation("Body must be valid JSON")
    if not isinstance(body, dict):
        raise validation("Body must be a JSON object")
    return body


def _is_int(v) -> bool:
    return type(v) is int  # bool is a subclass of int, so isinstance() would let True through


def _parse_date(value, field: str) -> date:
    if not isinstance(value, str) or not _DATE.fullmatch(value):
        raise validation(f"{field} must be a date formatted YYYY-MM-DD")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise validation(f"{field} is not a real calendar date")


# ---------- health ----------

@app.get("/health")
async def health():
    return {"status": "ok"}


# ---------- Part 1: members ----------

@app.post("/members", status_code=201)
async def create_member(request: Request):
    body = await _json_object(request)

    name, country, phone = body.get("name"), body.get("country"), body.get("phone")
    if not isinstance(name, str):
        raise validation("name must be a string")
    name = name.strip()
    if not 1 <= len(name) <= 120:
        raise validation("name must be 1 to 120 characters after trimming")
    if not isinstance(country, str) or country not in COUNTRIES:
        raise validation("country must be one of AE, SA, BH")
    if not isinstance(phone, str):
        raise validation("phone must be a string")

    canonical = normalize_for_member(phone, country)
    return members.create(name, country, canonical)


@app.get("/members/lookup")
async def lookup_member(request: Request):
    q = request.query_params
    phone, country = q.get("phone"), q.get("country")
    if country is not None and country not in COUNTRIES:
        raise validation("country must be one of AE, SA, BH")
    if phone is None:
        raise validation("phone query parameter is required")

    canonical = normalize_for_lookup(phone, country)
    member = members.find_by_phone(canonical)
    if member is None:
        raise ApiError(404, "NOT_FOUND", "No member with that phone")
    return member


# ---------- Part 2: plans ----------

@app.post("/plans", status_code=201)
async def create_plan(request: Request):
    body = await _json_object(request)

    plan_id, country = body.get("id"), body.get("country")
    monthly, joining_fee = body.get("monthly"), body.get("joining_fee")
    if not isinstance(plan_id, str) or plan_id == "":
        raise validation("id must be a non-empty string")
    if not isinstance(country, str) or country not in COUNTRIES:
        raise validation("country must be one of AE, SA, BH")
    if not _is_int(monthly) or monthly <= 0:
        raise validation("monthly must be an integer above 0")
    if not _is_int(joining_fee) or joining_fee < 0:
        raise validation("joining_fee must be an integer of 0 or more")

    return plans.create({"id": plan_id, "country": country, "currency": CURRENCY[country],
                         "monthly": monthly, "joining_fee": joining_fee})


# ---------- Part 2: agreements ----------

@app.post("/agreements", status_code=201)
async def create_agreement(request: Request):
    body = await _json_object(request)

    member_id, plan_id = body.get("member_id"), body.get("plan_id")
    start_raw, due_day = body.get("start_date"), body.get("due_day")
    if not isinstance(member_id, str):
        raise validation("member_id must be a string")
    if not isinstance(plan_id, str):
        raise validation("plan_id must be a string")
    start = _parse_date(start_raw, "start_date")
    if not _is_int(due_day) or not 1 <= due_day <= 31:
        raise validation("due_day must be an integer from 1 to 31")

    member = members.get(member_id)
    if member is None:
        raise ApiError(422, "UNKNOWN_MEMBER", "No member with that id")
    plan = plans.get(plan_id)
    if plan is None:
        raise ApiError(422, "UNKNOWN_PLAN", "No plan with that id")
    if plan["country"] != member["country"]:
        raise ApiError(422, "PLAN_COUNTRY_MISMATCH", "Plan country differs from member country")

    return agreements.create(member_id, plan_id, start.isoformat(), due_day)


@app.get("/agreements/{agreement_id}/invoices")
async def agreement_invoices(agreement_id: str, request: Request):
    q = request.query_params
    frm = _parse_date(q.get("from"), "from")
    to = _parse_date(q.get("to"), "to")

    agreement = agreements.get(agreement_id)
    if agreement is None:
        raise ApiError(404, "NOT_FOUND", "No agreement with that id")
    if to < frm or (to - frm).days > 366:
        raise ApiError(422, "INVALID_RANGE", "to must not be before from, and at most 366 days after")

    plan = plans.get(agreement["plan_id"])
    return invoices_in_range(date.fromisoformat(agreement["start_date"]), agreement["due_day"],
                             plan["monthly"], plan["joining_fee"], plan["country"], frm, to)