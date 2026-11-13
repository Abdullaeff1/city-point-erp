"""Named CoA role → account code mapping (A.6). Codes are 3-digit international style."""

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


def code_for(role: str) -> str:
    return DEFAULT_ROLE_CODES.get(role, role)
