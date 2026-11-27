"""AxTrax RO — səhifə açılışında təzələmə (throttled).

Production-da daimi təzəlik ``poll_axtrax`` prosesindən gəlir; bu modul
davamiyyət/keçid səhifəsi açılarkən bir dövrə əlavə edir (və ya poller
stale olanda boşluğu bağlayır). Heç vaxt exception qaldırmır — AxTrax
offline olsa belə ERP səhifəsi açılır.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any

from django.core.cache import cache

logger = logging.getLogger(__name__)

CACHE_KEY = "axtrax:on_demand:last_ok"
CACHE_LOCK = "axtrax:on_demand:lock"
DEFAULT_THROTTLE_SEC = 30


def _running_under_django_tests() -> bool:
    """Avoid live MSSQL timeouts during ``manage.py test`` unless explicitly allowed."""
    if (os.environ.get("AXTRAX_SYNC_ON_VIEW_ALLOW_LIVE") or "").strip() in {"1", "true", "yes"}:
        return False
    argv = " ".join(sys.argv).lower()
    return "manage.py test" in argv or argv.endswith(" test") or " pytest" in f" {argv}"


def _enabled() -> bool:
    return (os.environ.get("AXTRAX_SYNC_ON_VIEW") or "1").strip() not in {
        "0",
        "false",
        "no",
        "off",
    }


def _password_configured() -> bool:
    return bool((os.environ.get("TURNSTILE_MSSQL_PASSWORD") or "").strip())


def _throttle_seconds() -> int:
    try:
        return max(5, int(os.environ.get("AXTRAX_SYNC_ON_VIEW_INTERVAL", DEFAULT_THROTTLE_SEC)))
    except (TypeError, ValueError):
        return DEFAULT_THROTTLE_SEC


def maybe_refresh_axtrax_from_view(*, include_people: bool | None = None) -> dict[str, Any]:
    """Best-effort events (+ optional people) sync when an access page opens.

    Returns a small status dict for UI (Azərbaycan dili mesajları).
    """
    result: dict[str, Any] = {
        "attempted": False,
        "synced": False,
        "skipped": False,
        "reason": "",
        "message": "",
        "events_created": 0,
        "error": None,
    }

    if not _enabled():
        result["skipped"] = True
        result["reason"] = "disabled"
        result["message"] = "Səhifə açılışında AxTrax sinxronu söndürülüb."
        return result

    if _running_under_django_tests():
        result["skipped"] = True
        result["reason"] = "tests"
        result["message"] = "Test rejimində canlı AxTrax çağırışı keçildi."
        return result

    if not _password_configured():
        result["skipped"] = True
        result["reason"] = "no_password"
        result["message"] = (
            "AxTrax parolu təyin olunmayıb (TURNSTILE_MSSQL_PASSWORD). "
            "Keçid məlumatı yalnız lokal bazadandır."
        )
        return result

    throttle = _throttle_seconds()
    # Skip if a successful on-demand (or we recently ran) within throttle window.
    if cache.get(CACHE_KEY):
        result["skipped"] = True
        result["reason"] = "throttled"
        result["message"] = "AxTrax bu yaxınlarda sinxronlaşıb."
        return result

    # Single-flight lock so parallel list/detail tabs don't open N SQL sessions.
    if not cache.add(CACHE_LOCK, "1", timeout=min(60, throttle + 15)):
        result["skipped"] = True
        result["reason"] = "in_progress"
        result["message"] = "AxTrax sinxronu artıq gedir."
        return result

    result["attempted"] = True
    try:
        from apps.integrations.axtrax_events_sync import get_events_cursor, sync_event_rows
        from apps.integrations.axtrax_health import axtrax_sync_health
        from apps.integrations.axtrax_mssql import fetch_granted_events
        from apps.integrations.axtrax_people_sync import sync_people_from_mssql

        lookback = int(os.environ.get("AXTRAX_POLL_LOOKBACK_HOURS", "48"))
        try:
            login_to = max(2, int(os.environ.get("AXTRAX_ON_VIEW_LOGIN_TIMEOUT", "5")))
        except (TypeError, ValueError):
            login_to = 5
        try:
            query_to = max(5, int(os.environ.get("AXTRAX_ON_VIEW_QUERY_TIMEOUT", "20")))
        except (TypeError, ValueError):
            query_to = 20

        health = axtrax_sync_health(stale_after_minutes=max(2, throttle // 60 or 2))
        do_people = include_people
        if do_people is None:
            # People sync pollerdə qalır; səhifədə yalnız heç vaxt sync olmayıbsa cəhd.
            do_people = not health.get("last_people_sync_at")

        if do_people:
            try:
                sync_people_from_mssql()
            except Exception as people_exc:  # noqa: BLE001
                logger.warning("AxTrax on-view people sync failed: %s", people_exc)

        cursor = get_events_cursor()
        rows = fetch_granted_events(
            since_id=cursor,
            lookback_hours=lookback,
            login_timeout=login_to,
            timeout=query_to,
        )
        created = 0
        if rows:
            stats = sync_event_rows(rows, since_id=cursor, source="on_view")
            created = int(stats.get("created") or 0)
        result["synced"] = True
        result["events_created"] = created
        result["reason"] = "ok"
        if created:
            result["message"] = f"AxTrax yeniləndi · {created} yeni keçid."
        else:
            result["message"] = "AxTrax əlaqəsi quruldu · yeni keçid yoxdur."
        cache.set(CACHE_KEY, "1", timeout=throttle)
    except Exception as exc:  # noqa: BLE001
        logger.warning("AxTrax on-view sync failed: %s", exc)
        result["error"] = str(exc)
        result["reason"] = "error"
        result["message"] = (
            "AxTrax-a qoşulmaq alınmadı. Səhifə lokal məlumatla açılır; "
            "LAN/poller bərpa olunanda avtomatik davam edəcək."
        )
        # Short negative cache so a dead host doesn't stall every refresh.
        cache.set(CACHE_KEY, "1", timeout=min(15, throttle))
    finally:
        cache.delete(CACHE_LOCK)

    return result
