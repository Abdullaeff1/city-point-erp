"""Build synthetic sample_floor.dxf next to this module."""

from __future__ import annotations

from pathlib import Path


def main() -> Path:
    import ezdxf

    out = Path(__file__).resolve().parent / "sample_floor.dxf"
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    # Simple floor outline (meters-ish units).
    msp.add_lwpolyline(
        [(0, 0), (40, 0), (40, 25), (0, 25)],
        close=True,
        dxfattribs={"layer": "WALLS"},
    )
    msp.add_lwpolyline(
        [(5, 5), (18, 5), (18, 12), (5, 12)],
        close=True,
        dxfattribs={"layer": "ROOMS"},
    )
    msp.add_lwpolyline(
        [(22, 5), (35, 5), (35, 20), (22, 20)],
        close=True,
        dxfattribs={"layer": "ROOMS"},
    )
    msp.add_text(
        "City Point — sample floor (synthetic)",
        dxfattribs={"height": 1.2, "layer": "TEXT"},
    ).set_placement((2, 22))
    msp.add_circle((10, 8), radius=0.4, dxfattribs={"layer": "CAMERAS"})
    msp.add_circle((28, 15), radius=0.4, dxfattribs={"layer": "CAMERAS"})
    doc.saveas(out)
    return out


if __name__ == "__main__":
    path = main()
    print(path)
