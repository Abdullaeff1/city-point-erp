"""Default AZ commercial offer PDF (Helvetica + latin transliteration until corporate template upload)."""

from __future__ import annotations

from django.core.files.base import ContentFile
from django.utils import timezone


_AZ_MAP = str.maketrans(
    {
        "ə": "e",
        "Ə": "E",
        "ı": "i",
        "İ": "I",
        "ö": "o",
        "Ö": "O",
        "ü": "u",
        "Ü": "U",
        "ğ": "g",
        "Ğ": "G",
        "ş": "s",
        "Ş": "S",
        "ç": "c",
        "Ç": "C",
    }
)


def _latin(text: str) -> str:
    return (text or "").translate(_AZ_MAP)


def _pdf_escape(text: str) -> str:
    return _latin(text).replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def build_offer_pdf_bytes(version) -> bytes:
    """Minimal single-page PDF for OfferVersion."""
    offer = version.offer
    party = str(offer.party) if offer.party_id else "—"
    space = str(offer.space) if offer.space_id else "—"
    lines = [
        "CITY POINT — Kommersiya teklifi",
        f"Teklif #{offer.pk} / Versiya v{version.version_number}",
        f"Tarix: {timezone.localdate().isoformat()}",
        "",
        f"Musteri: {party}",
        f"Sahe: {space}",
        f"Sahe (m2): {version.area_m2 or '—'}",
        f"Tarif: {version.rent_rate_per_m2} AZN/m2",
        f"Endirim: {version.discount_percent}%",
        f"Aylıq net: {version.monthly_rent_net} AZN",
        f"EDV ({version.vat_rate}%): {version.monthly_vat} AZN",
        f"Aylıq gross: {version.monthly_rent_gross} AZN",
        f"Etibarlılıq: {version.valid_until or '—'}",
        "",
        "Paket:",
        (version.package_text or "")[:400],
        "",
        "Qeyd:",
        (version.notes or offer.notes or "")[:300],
    ]
    y = 800
    content_parts = ["BT", "/F1 11 Tf"]
    for raw in lines:
        for chunk in _wrap(_latin(raw), 86):
            content_parts.append(f"1 0 0 1 50 {y} Tm ({_pdf_escape(chunk)}) Tj")
            y -= 16
            if y < 50:
                break
        if y < 50:
            break
    content_parts.append("ET")
    stream = "\n".join(content_parts).encode("latin-1", errors="replace")

    objects: list[bytes] = []
    objects.append(b"1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj\n")
    objects.append(b"2 0 obj<< /Type /Pages /Kids [3 0 R] /Count 1 >>endobj\n")
    objects.append(
        b"3 0 obj<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>endobj\n"
    )
    objects.append(
        f"4 0 obj<< /Length {len(stream)} >>stream\n".encode("ascii")
        + stream
        + b"\nendstream\nendobj\n"
    )
    objects.append(b"5 0 obj<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>endobj\n")

    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for obj in objects:
        offsets.append(len(out))
        out.extend(obj)
    xref_pos = len(out)
    out.extend(f"xref\n0 {len(offsets)}\n".encode("ascii"))
    out.extend(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        out.extend(f"{off:010d} 00000 n \n".encode("ascii"))
    out.extend(
        f"trailer<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode(
            "ascii"
        )
    )
    return bytes(out)


def _wrap(text: str, width: int) -> list[str]:
    text = (text or "").replace("\r", "").replace("\n", " ").strip()
    if not text:
        return [""]
    words = text.split()
    rows: list[str] = []
    cur = ""
    for w in words:
        cand = f"{cur} {w}".strip()
        if len(cand) <= width:
            cur = cand
        else:
            if cur:
                rows.append(cur)
            cur = w if len(w) <= width else w[:width]
    if cur:
        rows.append(cur)
    return rows or [""]


def ensure_offer_version_pdf(version, *, force: bool = False, actor=None):
    """Generate and attach default PDF to OfferVersion.pdf_file; mirror into Document archive."""
    if version.pdf_file and not force:
        from apps.documents.crm_bridge import register_offer_version_pdf

        register_offer_version_pdf(version, actor=actor)
        return version
    data = build_offer_pdf_bytes(version)
    name = f"offer_{version.offer_id}_v{version.version_number}.pdf"
    version.pdf_file.save(name, ContentFile(data), save=True)
    from apps.documents.crm_bridge import register_offer_version_pdf

    register_offer_version_pdf(version, actor=actor)
    return version
