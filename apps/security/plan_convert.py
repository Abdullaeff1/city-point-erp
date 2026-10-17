"""DWG/DXF → SVG conversion (local only; no cloud)."""

from __future__ import annotations

import logging
import subprocess
import tempfile
from pathlib import Path

from django.conf import settings

from apps.security.svg_sanitize import SvgSanitizeError, sanitize_svg

logger = logging.getLogger(__name__)


class UnsupportedFormat(Exception):
    """Format not supported with current converter configuration."""


def dxf_to_svg_bytes(dxf_path: Path) -> tuple[bytes, str, str]:
    """Return (svg_bytes, tool, version) using ezdxf SVG backend."""
    import ezdxf
    from ezdxf.addons.drawing import Frontend, RenderContext, layout, svg

    doc = ezdxf.readfile(str(dxf_path))
    msp = doc.modelspace()
    backend = svg.SVGBackend()
    Frontend(RenderContext(doc), backend).draw_layout(msp, finalize=True)
    page = layout.Page(0, 0, layout.Units.mm, margins=layout.Margins.all(1))
    raw = backend.get_string(page)
    cleaned = sanitize_svg(raw)
    version = getattr(ezdxf, "__version__", "")
    return cleaned.encode("utf-8"), "ezdxf", version


def convert_source_to_svg(source_path: Path, source_format: str) -> tuple[bytes, str, str]:
    """Convert DXF (or DWG if converter configured) to sanitized SVG bytes."""
    fmt = (source_format or "").lower()
    if fmt == "dxf":
        return dxf_to_svg_bytes(source_path)
    if fmt == "dwg":
        converter = getattr(settings, "SECURITY_DWG_CONVERTER", "") or ""
        if not converter:
            raise UnsupportedFormat("DWG converter quraşdırılmayıb; DXF yükləyin.")
        dxf_path = _dwg_to_dxf(source_path, converter)
        try:
            return dxf_to_svg_bytes(dxf_path)
        finally:
            try:
                dxf_path.unlink(missing_ok=True)
                dxf_path.parent.rmdir()
            except OSError:
                pass
    raise UnsupportedFormat(f"Naməlum format: {fmt}")


def _dwg_to_dxf(dwg_path: Path, converter: str) -> Path:
    """Run configured converter CLI; returns temp DXF path."""
    out_dir = Path(tempfile.mkdtemp(prefix="cp_dwg_"))
    cmd = [converter, str(dwg_path), str(out_dir)]
    try:
        subprocess.run(cmd, check=True, timeout=120, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise UnsupportedFormat("DWG converter tapılmadı.") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("DWG conversion timeout") from exc
    except subprocess.CalledProcessError as exc:
        logger.exception("DWG convert failed: %s", (exc.stderr or "")[:500])
        raise RuntimeError("DWG conversion failed") from exc
    dxfs = list(out_dir.glob("*.dxf"))
    if not dxfs:
        raise RuntimeError("DWG converter DXF çıxarmadı")
    return dxfs[0]
