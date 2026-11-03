"""Content-aware document file validation (do not trust browser MIME)."""

from __future__ import annotations

import zipfile
from io import BytesIO

from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _

ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".docx"}
MAX_DOCUMENT_BYTES = 20 * 1024 * 1024


def _ext(name: str) -> str:
    name = (name or "").lower()
    if "." not in name:
        return ""
    return "." + name.rsplit(".", 1)[-1]


def validate_document_file(uploaded) -> None:
    if not uploaded:
        raise ValidationError(_("Fayl tələb olunur."))
    name = getattr(uploaded, "name", "") or ""
    ext = _ext(name)
    if ext not in ALLOWED_EXTENSIONS:
        raise ValidationError(_("İcazəli formatlar: PDF, PNG, JPG, DOCX."))
    size = getattr(uploaded, "size", 0) or 0
    if size > MAX_DOCUMENT_BYTES:
        raise ValidationError(_("Fayl ölçüsü 20 MB-dan böyük ola bilməz."))

    pos = uploaded.tell() if hasattr(uploaded, "tell") else None
    head = uploaded.read(16) if hasattr(uploaded, "read") else b""
    if hasattr(uploaded, "seek"):
        uploaded.seek(0)
        content = uploaded.read()
        uploaded.seek(0)
    else:
        content = head

    if pos is not None and hasattr(uploaded, "seek"):
        try:
            uploaded.seek(pos)
        except Exception:
            uploaded.seek(0)

    if ext == ".pdf":
        if not content.startswith(b"%PDF"):
            raise ValidationError(_("Fayl PDF deyil (məzmun yoxlaması)."))
        return

    if ext in {".png", ".jpg", ".jpeg"}:
        try:
            from PIL import Image

            Image.open(BytesIO(content)).verify()
        except Exception as exc:
            raise ValidationError(_("Şəkil faylı açıla bilmədi.")) from exc
        return

    if ext == ".docx":
        try:
            with zipfile.ZipFile(BytesIO(content)) as zf:
                names = set(zf.namelist())
                if "[Content_Types].xml" not in names:
                    raise ValidationError(_("DOCX strukturu yanlışdır."))
                if not any(n.startswith("word/") for n in names):
                    raise ValidationError(_("DOCX strukturu yanlışdır."))
        except ValidationError:
            raise
        except Exception as exc:
            raise ValidationError(_("DOCX faylı açıla bilmədi.")) from exc
