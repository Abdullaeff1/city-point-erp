from pathlib import Path

from pypdf import PdfReader
from pypdf.generic import IndirectObject

p = Path("/app/docs/CityPoint_camera_report_261015_105012.pdf")
r = PdfReader(str(p))


def resolve(obj):
    while isinstance(obj, IndirectObject):
        obj = obj.get_object()
    return obj


rows = []
for i, page in enumerate(r.pages):
    anns = page.get("/Annots")
    if not anns:
        continue
    anns = resolve(anns)
    for a in anns:
        a = resolve(a)
        if not hasattr(a, "get"):
            continue
        contents = a.get("/Contents")
        title = a.get("/T")
        rc = a.get("/RC")
        rows.append(
            {
                "page": i + 1,
                "subtype": str(a.get("/Subtype", "")),
                "title": str(title) if title else "",
                "contents": str(contents) if contents else "",
                "rc": str(rc)[:800] if rc else "",
                "rect": [float(x) for x in a.get("/Rect")] if a.get("/Rect") else None,
            }
        )

print("annotations", len(rows))
with_text = [x for x in rows if x["contents"] or x["title"] or x["rc"]]
print("with text", len(with_text))
for row in with_text[:50]:
    print(row)

out = Path("/app/var/camera_pdf_extract.txt")
parts = [f"annotations={len(rows)} with_text={len(with_text)}\n"]
for row in with_text:
    parts.append(repr(row) + "\n")
for i in range(14, 19):
    parts.append(f"\n===== PAGE {i+1} =====\n")
    parts.append(r.pages[i].extract_text() or "")
out.write_text("".join(parts), encoding="utf-8")
print("wrote", out)
