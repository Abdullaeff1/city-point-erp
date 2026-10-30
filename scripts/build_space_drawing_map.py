"""Build package_id → space_code CSV from City_Point_Ofisler_DXF_PNG + DB spaces.

Matching strategy (per floor):
1. Prefer closest contour_area_m2 ↔ Space.area_m2 (greedy, largest first)
2. Boost score when source_label fuzzy-matches space/resident name
3. Leave unmatched if no reasonable area candidate remains
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

from apps.property.models import Space  # noqa: E402

ROOT = ROOT_DIR / "docs" / "City_Point_Ofisler_DXF_PNG"
OUT = ROOT / "space_drawing_map.csv"

FLOOR_MAP = {
    "B1": "B01",
    "F01": "F01",
    "F02": "F02",
    "F03": "F03",
    "F04": "F04",
    "F05": "F05",
    "F06": "F06",
    "F07": "F07",
    "F08": "F08",
    "F09": "F09",
    "F10": "F10",
    "F12": "F12",
}


def norm(s: str | None) -> str:
    s = (s or "").strip().strip('"').lower()
    s = re.sub(r"\s+", " ", s)
    for a, b in (
        ("ə", "e"),
        ("ı", "i"),
        ("ö", "o"),
        ("ü", "u"),
        ("ş", "s"),
        ("ç", "c"),
        ("ğ", "g"),
    ):
        s = s.replace(a, b)
    return s


def load_packages() -> list[dict]:
    pkgs = []
    for p in sorted(ROOT.rglob("*.json")):
        if p.name in {"office_register.json"} or "map" in p.name or p.suffixes[-1:] == [".example"]:
            continue
        if p.name.endswith(".example"):
            continue
        raw = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(raw, dict) and raw.get("id"):
            pkgs.append(raw)
    return pkgs


def main() -> None:
    pkgs = load_packages()
    by_floor: dict[str, list[dict]] = defaultdict(list)
    for m in pkgs:
        f = FLOOR_MAP.get(m["floor"])
        if not f:
            print(f"SKIP {m['id']} unsupported floor {m['floor']}")
            continue
        by_floor[f].append(m)

    mapping: list[tuple[str, str]] = []

    for fcode, items in sorted(by_floor.items()):
        spaces = list(Space.objects.filter(floor__code=fcode).select_related("resident").order_by("code"))
        # Prefer lease spaces over lobby/odd demo codes when areas collide
        spaces = sorted(spaces, key=lambda s: (0 if str(s.code).startswith("CP-L") else 1, s.code))
        if not spaces:
            for m in items:
                print(f"SKIP {m['id']} floor={fcode} (no spaces)")
            continue

        used: set[int] = set()
        items_sorted = sorted(items, key=lambda m: -(m.get("contour_area_m2") or 0))
        for m in items_sorted:
            area = m.get("contour_area_m2")
            label = norm(m.get("source_label"))
            best = None
            best_score = None
            for s in spaces:
                if s.pk in used:
                    continue
                sa = float(s.area_m2 or 0)
                if area and sa > 0:
                    adiff = abs(sa - float(area)) / max(sa, float(area))
                else:
                    adiff = 0.95
                names = [norm(s.name), norm(getattr(s.resident, "name", None) or "")]
                nscore = max(
                    (SequenceMatcher(None, label, n).ratio() if label and n else 0.0) for n in names
                )
                score = adiff - 0.35 * nscore
                if best is None or score < best_score:
                    best = s
                    best_score = score

            if best is None or best_score is None or best_score > 0.5:
                print(
                    f"SKIP {m['id']} label={m.get('source_label')!r} area={area} "
                    f"best={(best.code if best else None)} score={best_score}"
                )
                continue

            used.add(best.pk)
            mapping.append((m["id"], best.code))
            print(
                f"OK {m['id']} -> {best.code} ({best.name} / {getattr(best.resident, 'name', None)}) "
                f"pkg={area} space={best.area_m2} score={best_score:.3f}"
            )

    OUT.write_text(
        "package_id,space_code\n" + "\n".join(f"{a},{b}" for a, b in mapping) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {OUT} rows={len(mapping)} / packages={len(pkgs)}")


if __name__ == "__main__":
    main()
