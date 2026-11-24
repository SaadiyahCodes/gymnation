"""In-memory stores. Every "may not" rule is check+insert under one lock."""
import threading
import uuid

from .errors import ApiError


class MemberStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_id: dict[str, dict] = {}
        self._by_phone: dict[str, str] = {}  # canonical phone -> member id

    def create(self, name: str, country: str, phone: str) -> dict:
        with self._lock:
            existing = self._by_phone.get(phone)
            if existing is not None:
                raise ApiError(409, "PHONE_TAKEN", "A member with this phone already exists",
                               existing_member_id=existing)
            member = {"id": str(uuid.uuid4()), "name": name, "country": country, "phone": phone}
            self._by_id[member["id"]] = member
            self._by_phone[phone] = member["id"]
            return dict(member)

    def find_by_phone(self, phone: str) -> dict | None:
        with self._lock:
            mid = self._by_phone.get(phone)
            return dict(self._by_id[mid]) if mid else None

    def get(self, member_id: str) -> dict | None:
        with self._lock:
            m = self._by_id.get(member_id)
            return dict(m) if m else None


class PlanStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_id: dict[str, dict] = {}

    def create(self, plan: dict) -> dict:
        with self._lock:
            if plan["id"] in self._by_id:
                raise ApiError(409, "PLAN_EXISTS", "A plan with this id already exists")
            self._by_id[plan["id"]] = dict(plan)
            return dict(plan)

    def get(self, plan_id: str) -> dict | None:
        with self._lock:
            p = self._by_id.get(plan_id)
            return dict(p) if p else None


class AgreementStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_id: dict[str, dict] = {}

    def create(self, member_id: str, plan_id: str, start_date: str, due_day: int) -> dict:
        with self._lock:
            ag = {"id": str(uuid.uuid4()), "member_id": member_id, "plan_id": plan_id,
                  "start_date": start_date, "due_day": due_day}
            self._by_id[ag["id"]] = ag
            return dict(ag)

    def get(self, agreement_id: str) -> dict | None:
        with self._lock:
            a = self._by_id.get(agreement_id)
            return dict(a) if a else None

    def all(self) -> list[dict]:
        with self._lock:
            return [dict(a) for a in self._by_id.values()]


class RunStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_id: dict[str, dict] = {}

    def create(self, body: dict) -> dict:
        """body is the run without an id; returns the stored run (with id)."""
        with self._lock:
            run = {"id": str(uuid.uuid4()), **body}
            self._by_id[run["id"]] = run
            return run

    def get(self, run_id: str) -> dict | None:
        with self._lock:
            return self._by_id.get(run_id)