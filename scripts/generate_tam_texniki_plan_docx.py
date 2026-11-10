#!/usr/bin/env python3
"""Generate Word copy of CityPoint_Tam_Texniki_Plan.md (simple markdown → docx)."""

from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.shared import Cm

ROOT = Path(__file__).resolve().parents[1]
MD = ROOT / "docs" / "architecture" / "CityPoint_Tam_Texniki_Plan.md"
OUT = ROOT / "docs" / "architecture" / "CityPoint_Tam_Texniki_Plan.docx"


def main() -> None:
    md = MD.read_text(encoding="utf-8")
    doc = Document()
    for section in doc.sections:
        section.top_margin = Cm(2)
        section.bottom_margin = Cm(2)
        section.left_margin = Cm(2.2)
        section.right_margin = Cm(2.2)

    in_code = False
    for raw in md.splitlines():
        line = raw.rstrip()
        if line.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            doc.add_paragraph(line)
            continue
        if not line.strip():
            continue
        if line.startswith("# "):
            doc.add_heading(line[2:].strip(), level=0)
        elif line.startswith("## "):
            doc.add_heading(line[3:].strip(), level=1)
        elif line.startswith("### "):
            doc.add_heading(line[4:].strip(), level=2)
        elif line.startswith("> "):
            p = doc.add_paragraph(line[2:].strip())
            for r in p.runs:
                r.italic = True
        elif line.startswith("|"):
            body = line.strip().strip("|")
            if set(body.replace("-", "").replace(":", "").replace("|", "").strip()) == set():
                continue
            cells = [c.strip() for c in body.split("|")]
            doc.add_paragraph(" · ".join(cells))
        elif line.startswith("- "):
            doc.add_paragraph(line[2:].strip(), style="List Bullet")
        else:
            doc.add_paragraph(line)

    doc.save(OUT)
    print(f"WROTE {OUT} ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
