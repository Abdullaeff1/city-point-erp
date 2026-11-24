"""Named CoA role → account code mapping (A.6).

Default codes are the synthetic 3-digit placeholder chart. Finance may override
via Django setting ACCOUNTING_ROLE_CODES = {"ar": "115", ...} after importing
the real chart. code_for() always resolves through that merge.
"""

from __future__ import annotations

# Placeholder 3-digit chart until client imports full CoA
DEFAULT_ROLE_CODES = {
    "cash": "100",
    "bank": "101",
    "ar": "110",
    "ap": "200",
    "vat": "210",
    "equity": "300",
    "rent_revenue": "400",
    "service_revenue": "410",
    "other_revenue": "420",
    "penalty_revenue": "430",
    "expense": "500",
}

DEFAULT_COA_ROWS = [
    ("100", "Kassa", "asset"),
    ("101", "Bank", "asset"),
    ("110", "Debitorlar (AR)", "asset"),
    ("200", "Kreditorlar (AP)", "liability"),
    ("210", "ƏDV öhdəliyi", "liability"),
    ("300", "Kapital", "equity"),
    ("400", "Kirayə gəliri", "revenue"),
    ("410", "Xidmət haqqı gəliri", "revenue"),
    ("420", "Digər gəlir", "revenue"),
    ("430", "Cərimə gəliri", "revenue"),
    ("500", "Əməliyyat xərcləri", "expense"),
]


def role_codes() -> dict[str, str]:
    """Merged role→code map (settings override wins)."""
    codes = dict(DEFAULT_ROLE_CODES)
    try:
        from django.conf import settings

        override = getattr(settings, "ACCOUNTING_ROLE_CODES", None) or {}
        if isinstance(override, dict):
            codes.update({str(k): str(v) for k, v in override.items() if k and v})
    except Exception:  # noqa: BLE001 — settings may be unconfigured in import-time tools
        pass
    return codes


def code_for(role: str) -> str:
    return role_codes().get(role, role)
