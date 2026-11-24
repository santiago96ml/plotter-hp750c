"""Structural checks for the HP RTL raster job; no hardware is touched."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image

from plotter import raster


def check_small_job() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "red.png"
        Image.new("RGB", (2, 2), (1, 2, 3)).save(path)

        plan = raster.build(path)

        assert plan.width_px == 2 and plan.height_px == 2, plan
        assert plan.width_mm == 2 / 300 * 25.4
        assert plan.payload.startswith(b"\x1bE\x1b%0A"), plan.payload[:16]
        assert b"*v18W" in plan.payload
        assert b"*t300R" in plan.payload
        assert b"*r2S" in plan.payload and b"*r2T" in plan.payload
        assert plan.payload.count(b"*b6W") == 2, "one transfer command per row"
        assert plan.payload.count(b"\x01\x02\x03") == 4, "four pixels"
        assert plan.payload.endswith(b"\x1b*rC\x1b%0BPG;"), plan.payload[-16:]


def check_scaling() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "square.png"
        Image.new("RGB", (100, 100), (10, 20, 30)).save(path)

        plan = raster.build(path, width_mm=25.4)

        assert plan.width_px == 300, plan.width_px
        assert plan.height_px == 300, plan.height_px
        assert plan.width_mm == 25.4


def check_banding() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "stripes.png"
        Image.new("RGB", (2, 4), (7, 8, 9)).save(path)

        plan = raster.build(path, band_rows=2)

        assert plan.payload.count(b"*r0A") == 2, "two bands"
        assert plan.payload.count(b"*rC") == 2, "each band ends raster mode"
        assert plan.payload.count(b"*r2T") == 2, "two rows per band"
        assert plan.payload.count(b"*b6W") == 4, "four rows in total"


def check_cover() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "square.png"
        Image.new("RGB", (100, 100), (4, 5, 6)).save(path)

        plan = raster.build(path, dpi=100, sheet_mm=(297.0, 210.0))

        assert plan.width_px == round(297 / 25.4 * 100), plan.width_px
        assert plan.height_px == round(210 / 25.4 * 100), plan.height_px


def check_rotation() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "row.png"
        image = Image.new("RGB", (2, 1))
        image.putpixel((0, 0), (1, 2, 3))
        image.putpixel((1, 0), (4, 5, 6))
        image.save(path)

        plan = raster.build(path, rotate=90)

        assert plan.width_px == 1 and plan.height_px == 2, (plan.width_px, plan.height_px)
        assert plan.payload.count(b"\x01\x02\x03") == 1, "left pixel ends up on top"
        assert plan.payload.count(b"\x04\x05\x06") == 1, "right pixel ends up below"


def main() -> int:
    check_small_job()
    check_scaling()
    check_banding()
    check_cover()
    check_rotation()
    print("raster tests: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
