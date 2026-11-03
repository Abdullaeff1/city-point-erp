"""Gated public media — block legacy document paths under /media/documents/."""

from __future__ import annotations

from django.conf import settings
from django.http import HttpResponseForbidden
from django.views.static import serve


BLOCKED_MEDIA_PREFIXES = (
    "documents/",
    "documents\\",
)


def is_blocked_media_path(path: str) -> bool:
    normalized = (path or "").lstrip("/").replace("\\", "/")
    return any(normalized.startswith(p.replace("\\", "/")) for p in BLOCKED_MEDIA_PREFIXES)


def media_serve(request, path):
    """DEBUG (and optional prod) media handler that refuses document files."""
    if is_blocked_media_path(path):
        return HttpResponseForbidden("Document files are not publicly available.")
    return serve(request, path, document_root=settings.MEDIA_ROOT)
