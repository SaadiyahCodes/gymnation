"""In-memory member store. Phone uniqueness is check+insert under one lock."""
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