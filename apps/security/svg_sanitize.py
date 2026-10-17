"""Allowlist SVG sanitization for converted floor plans."""

from __future__ import annotations

import re
from xml.etree import ElementTree as ET

_EVENT_ATTR = re.compile(r"^on", re.I)
_BAD_URL = re.compile(r"^\s*(javascript|data|vbscript|file|http|https):", re.I)
_CSS_BAD = re.compile(r"url\s*\(|@import|expression\s*\(|javascript:", re.I)

_ALLOWED_TAGS = {
    "svg",
    "g",
    "path",
    "polyline",
    "polygon",
    "line",
    "rect",
    "circle",
    "ellipse",
    "text",
    "tspan",
    "defs",
    "clipPath",
    "use",
    "title",
    "desc",
    "marker",
    "symbol",
    "style",  # ezdxf emits class strokes; content must pass CSS allowlist
}

_BLOCKED_TAGS = {
    "script",
    "foreignObject",
    "iframe",
    "object",
    "embed",
    "image",
    "a",
}


class SvgSanitizeError(ValueError):
    pass


def sanitize_svg(raw: str | bytes) -> str:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    text = (raw or "").strip()
    if not text:
        raise SvgSanitizeError("Empty SVG")
    if re.search(r"<!DOCTYPE|<!ENTITY", text, re.I):
        raise SvgSanitizeError("SVG DOCTYPE/ENTITY not allowed")
    # Drop XML declaration for ElementTree.
    text = re.sub(r"<\?xml[^?]*\?>", "", text, count=1).strip()
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise SvgSanitizeError(f"Invalid SVG XML: {exc}") from exc

    def local(tag: str) -> str:
        if "}" in tag:
            return tag.rsplit("}", 1)[-1]
        return tag

    def walk(el: ET.Element) -> None:
        name = local(el.tag)
        if name in _BLOCKED_TAGS or name not in _ALLOWED_TAGS:
            raise SvgSanitizeError(f"Disallowed SVG element: {name}")
        if name == "style":
            css = "".join(el.itertext())
            if _CSS_BAD.search(css):
                raise SvgSanitizeError("Disallowed CSS in style element")
        for attr in list(el.attrib):
            low = attr.lower()
            attr_local = low.split("}")[-1] if "}" in low else low
            if _EVENT_ATTR.match(attr_local):
                raise SvgSanitizeError(f"Event handler attribute not allowed: {attr}")
            if low.startswith("xmlns"):
                continue
            val = el.attrib.get(attr, "")
            if isinstance(val, str) and _BAD_URL.search(val):
                raise SvgSanitizeError(f"Disallowed URL in attribute {attr}")
            if attr_local == "style" and isinstance(val, str) and _CSS_BAD.search(val):
                raise SvgSanitizeError("Disallowed CSS in style attribute")
            if attr_local in {"href", "xlink:href"}:
                if not val.strip().startswith("#"):
                    raise SvgSanitizeError("External href not allowed")
                if name != "use":
                    raise SvgSanitizeError("href only allowed on use")
        for child in list(el):
            walk(child)

    walk(root)
    return ET.tostring(root, encoding="unicode")
