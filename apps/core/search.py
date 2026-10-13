"""Case-insensitive text search helpers (Azerbaijani İ/I/ı aware)."""

from __future__ import annotations

import operator
import re
import unicodedata
from functools import reduce

from django.db.models import CharField, F, Func, Q, QuerySet

# Map Azerbaijani/Turkish I variants to ASCII i before Unicode casefold.
_AZ_I_MAP = str.maketrans({"İ": "i", "I": "i", "ı": "i"})


def fold_search(value: str) -> str:
    """Normalize text for case-insensitive matching (AZ-aware)."""
    s = (value or "").translate(_AZ_I_MAP)
    s = s.casefold()
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    return re.sub(r"\s+", " ", s).strip()


class SearchFold(Func):
    """PostgreSQL expression mirroring :func:`fold_search`."""

    arity = 1
    output_field = CharField()
    template = (
        "lower(translate(COALESCE(%(expressions)s, ''), 'İIı', 'iii')"
        ")"
    )


def filter_text_search(qs: QuerySet, query: str, *fields: str) -> QuerySet:
    """Filter queryset by folded substring match on any of ``fields``.

    ``fields`` are ORM paths (e.g. ``\"full_name\"``, ``\"company__name\"``).
    """
    folded = fold_search(query)
    if not folded or not fields:
        return qs
    aliases: dict = {}
    clauses: list[Q] = []
    for i, field in enumerate(fields):
        alias = f"_cps{i}"
        aliases[alias] = SearchFold(F(field))
        clauses.append(Q(**{f"{alias}__contains": folded}))
    return qs.alias(**aliases).filter(reduce(operator.or_, clauses))
