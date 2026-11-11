#!/usr/bin/env python3
"""Generate Word copy of product delivery roadmap plan (markdown → docx)."""

from __future__ import annotations

import re
from pathlib import Path

from docx import Document
from docx.shared import Cm, Pt

ROOT = Path(__file__).resolve().parents[1]
# Plan may live in Cursor plans dir or be copied into docs later
CANDIDATES = [
    Path.home() / ".cursor" / "plans" / "product_delivery_roadmap_379c9aa4.plan.md",
    ROOT / "docs" / "architecture" / "PRODUCT_DELIVERY_ROADMAP.md",
]
OUT = ROOT / "docs" / "architecture" / "CityPoint_Product_Delivery_Roadmap.docx"

LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")
BOLD_RE = re.compile(r"\*\*([^*]+)\*\*")


def strip_frontmatter(text: str) -> str:
    if not text.startswith("---"):
        return text
    end = text.find("\n---", 3)
    if end == -1:
        return text
    return text[end + 4 :].lstrip("\n")


def clean_inline(text: str) -> str:
    text = LINK_RE.sub(r"\1", text)
    text = BOLD_RE.sub(r"\1", text)
    text = text.replace("`", "")
    return text


def add_runs(paragraph, text: str) -> None:
    """Add paragraph text, preserving **bold** spans."""
    parts = BOLD_RE.split(text)
    # split keeps captures: plain, bold, plain, bold, ...
    for i, part in enumerate(parts):
        if not part:
            continue
        run = paragraph.add_run(LINK_RE.sub(r"\1", part).replace("`", ""))
        run.font.size = Pt(11)
        if i % 2 == 1:
            run.bold = True


def find_source() -> Path:
    for path in CANDIDATES:
        if path.is_file():
            return path
    raise SystemExit(f"Roadmap markdown not found in: {CANDIDATES}")


def main() -> None:
    src = find_source()
    md = strip_frontmatter(src.read_text(encoding="utf-8"))
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
            if in_code:
                continue
            continue
        if in_code:
            p = doc.add_paragraph(line)
            for r in p.runs:
                r.font.name = "Consolas"
                r.font.size = Pt(9)
            continue
        if not line.strip():
            continue
        if line.strip() == "---":
            continue

        if line.startswith("#### "):
            doc.add_heading(clean_inline(line[5:].strip()), level=3)
        elif line.startswith("### "):
            doc.add_heading(clean_inline(line[4:].strip()), level=2)
        elif line.startswith("## "):
            doc.add_heading(clean_inline(line[3:].strip()), level=1)
        elif line.startswith("# "):
            doc.add_heading(clean_inline(line[2:].strip()), level=0)
        elif line.startswith("> "):
            p = doc.add_paragraph()
            add_runs(p, line[2:].strip())
            for r in p.runs:
                r.italic = True
        elif line.startswith("|"):
            body = line.strip().strip("|")
            if set(body.replace("-", "").replace(":", "").replace("|", "").replace(" ", "")) == set():
                continue
            cells = [clean_inline(c.strip()) for c in body.split("|")]
            doc.add_paragraph(" · ".join(cells))
        elif re.match(r"^\d+\.\s+", line):
            text = re.sub(r"^\d+\.\s+", "", line)
            p = doc.add_paragraph(style="List Number")
            add_runs(p, text)
        elif line.startswith("- "):
            p = doc.add_paragraph(style="List Bullet")
            add_runs(p, line[2:].strip())
        else:
            p = doc.add_paragraph()
            add_runs(p, line)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc.save(OUT)
    print(f"SOURCE {src}")
    print(f"WROTE {OUT} ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
