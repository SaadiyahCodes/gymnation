"""FastAPI app for Part 1. Run: uvicorn app.main:app --port 8080

Request bodies are read manually (not via Pydantic models) so EVERY bad input
maps to our own {"error": {...}} shape instead of FastAPI's default.
"""
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .errors import ApiError, validation
from .phone import COUNTRIES, normalize_for_lookup, normalize_for_member
from .store import MemberStore

app = FastAPI()
members = MemberStore()


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


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/members", status_code=201)
async def create_member(request: Request):
    try:
        body = await request.json()
    except Exception:
        raise validation("Body must be valid JSON")
    if not isinstance(body, dict):
        raise validation("Body must be a JSON object")

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