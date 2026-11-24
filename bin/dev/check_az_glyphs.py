"""Check whether local woff2 fonts contain Azerbaijani glyphs."""
from pathlib import Path

from fontTools.ttLib import TTFont

NEEDED = {
    "Ə": 0x018F,
    "ə": 0x0259,
    "Ğ": 0x011E,
    "ğ": 0x011F,
    "I": 0x0049,
    "ı": 0x0131,
    "İ": 0x0130,
    "i": 0x0069,
    "Ö": 0x00D6,
    "ö": 0x00F6,
    "Ş": 0x015E,
    "ş": 0x015F,
    "Ü": 0x00DC,
    "ü": 0x00FC,
    "Ç": 0x00C7,
    "ç": 0x00E7,
    "₼": 0x20BC,
}

FILES = [
    "manrope-latin.woff2",
    "manrope-latin-600.woff2",
    "manrope-latin-700.woff2",
    "plus-jakarta-sans-latin.woff2",
    "noto-sans-400.woff2",
    "noto-sans-500.woff2",
    "noto-sans-600.woff2",
    "noto-sans-700.woff2",
]


def cmap_of(path: Path) -> set[int]:
    font = TTFont(str(path))
    cps: set[int] = set()
    for table in font["cmap"].tables:
        cps.update(table.cmap.keys())
    return cps


def main() -> None:
    import sys

    # Windows cp1252 consoles cannot print Ə/ə; keep output ASCII-safe.
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    root = Path(__file__).resolve().parents[2] / "static" / "fonts"
    for name in FILES:
        path = root / name
        if not path.exists():
            print(f"MISSING {name}")
            continue
        cps = cmap_of(path)
        missing = [f"U+{cp:04X}" for _ch, cp in NEEDED.items() if cp not in cps]
        status = "ok" if not missing else f"missing={missing}"
        print(f"{name}: glyphs={len(cps)} {status}")


if __name__ == "__main__":
    main()
