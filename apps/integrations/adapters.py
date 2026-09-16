"""Integration adapter interfaces — no vendor guessing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class AdapterResult:
    ok: bool
    external_id: str = ""
    raw: Any = None
    error: str = ""


class AccessControlAdapter(Protocol):
    def health_check(self) -> AdapterResult: ...

    def upsert_person(self, person_payload: dict) -> AdapterResult: ...

    def assign_credential(self, credential_payload: dict) -> AdapterResult: ...

    def revoke_credential(self, credential_payload: dict) -> AdapterResult: ...

    def fetch_events(self, since_iso: str | None = None) -> list[dict]: ...


class MockAccessControlAdapter:
    """Safe default until turnstile vendor audit is complete."""

    def health_check(self) -> AdapterResult:
        return AdapterResult(ok=True, raw={"mode": "mock"})

    def upsert_person(self, person_payload: dict) -> AdapterResult:
        return AdapterResult(ok=True, external_id=f"mock-person-{person_payload.get('id', 'x')}")

    def assign_credential(self, credential_payload: dict) -> AdapterResult:
        return AdapterResult(ok=True, external_id=f"mock-cred-{credential_payload.get('code', 'x')}")

    def revoke_credential(self, credential_payload: dict) -> AdapterResult:
        return AdapterResult(ok=True)

    def fetch_events(self, since_iso: str | None = None) -> list[dict]:
        return []


class WebsiteLeadAdapter(Protocol):
    def ingest_lead(self, payload: dict) -> AdapterResult: ...


class MockWebsiteLeadAdapter:
    def ingest_lead(self, payload: dict) -> AdapterResult:
        ext = payload.get("external_id") or f"web-{payload.get('email', 'unknown')}"
        return AdapterResult(ok=True, external_id=str(ext), raw=payload)
