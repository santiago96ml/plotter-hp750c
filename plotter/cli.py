"""Command line interface for the HP DesignJet 750C plotter."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import colors, raster, render, svg
from .hpgl2 import Canvas
from .pages import color_quick_canvas, color_test_canvas, selftest_canvas
from .usbprint import UsbPrinter, list_devices

PAGES = {
    "A4": (297.0, 210.0),
    "A3": (420.0, 297.0),
    "A2": (594.0, 420.0),
    "A1": (841.0, 594.0),
    "A0": (1189.0, 841.0),
}


def parse_page(value: str | None) -> tuple[float, float] | None:
    if not value:
        return None
    key = value.upper()
    if key in PAGES:
        return PAGES[key]
    if "x" in value.lower():
        w, h = value.lower().split("x", 1)
        return float(w), float(h)
    raise SystemExit(f"Unknown page size: {value}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="plotter", description="HP DesignJet 750C over raw USB")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("devices", help="list USB printer interfaces")
    sub.add_parser("status", help="check the device can be opened")
    sub.add_parser("test", help="send the built-in self test page")
    color_cmd = sub.add_parser("color", help="send the four pen colour test page")
    color_cmd.add_argument("--quick", action="store_true", help="fast bars instead of filled squares")

    svg_cmd = sub.add_parser("svg", help="plot an SVG file")
    svg_cmd.add_argument("path", type=Path)
    svg_cmd.add_argument("--page", help="A4..A0 or WxH in mm")
    svg_cmd.add_argument("--margin", type=float, default=10.0)
    svg_cmd.add_argument("--no-fit", action="store_true", help="keep the SVG's own size")
    svg_cmd.add_argument("--speed", type=float, default=None, help="pen speed in cm/s")
    svg_cmd.add_argument("--rotate", type=int, default=0, choices=[0, 90, 180, 270],
                         help="rotate the drawing on the page")
    svg_cmd.add_argument("--dry-run", type=Path, help="write HP-GL/2 to a file instead of plotting")

    image_cmd = sub.add_parser("image", help="print a JPEG/PNG as HP RTL colour raster")
    image_cmd.add_argument("path", type=Path)
    image_cmd.add_argument("--width-mm", type=float, default=None,
                           help="printed width in mm; omit to keep 300 dpi pixels")
    image_cmd.add_argument("--fill", help="cover this page size (A4..A0 or WxH mm)")
    image_cmd.add_argument("--rotate", type=int, default=0, choices=[0, 90, 180, 270],
                           help="rotate the image clockwise before printing")
    image_cmd.add_argument("--dpi", type=int, default=raster.COLOR_DPI)
    image_cmd.add_argument("--band-rows", type=int, default=800,
                           help="rows per raster band; keeps memory use low")
    image_cmd.add_argument("--dry-run", type=Path,
                           help="write the HP RTL job to a file instead of printing")

    text_cmd = sub.add_parser("text", help="plot a single line of text")
    text_cmd.add_argument("value")
    text_cmd.add_argument("--size", type=float, default=8.0)
    text_cmd.add_argument("--x", type=float, default=10.0)
    text_cmd.add_argument("--y", type=float, default=20.0)
    text_cmd.add_argument("--page", default="A4")

    sub.add_parser("feed", help="advance the media one page")

    raw_cmd = sub.add_parser("raw", help="send a raw HP-GL/2 file")
    raw_cmd.add_argument("path", type=Path)

    args = parser.parse_args(argv)

    if args.command == "devices":
        devices = list_devices()
        if not devices:
            print("No USB printer interface found.")
            return 1
        for device in devices:
            print(device.path)
        return 0

    if args.command == "status":
        devices = list_devices()
        print(f"USB printer interfaces: {len(devices)}")
        for device in devices:
            print(f"  {device.short}")
        if not devices:
            return 1
        with UsbPrinter() as printer:
            print(f"open: OK  ({printer.device.short})")
        return 0

    if args.command == "test":
        result = render.plot_canvas(selftest_canvas())
        print(f"self test sent: {result['bytes']} bytes in {result['seconds']}s")
        return 0

    if args.command == "color":
        canvas = color_quick_canvas() if args.quick else color_test_canvas()
        result = render.plot_canvas(canvas)
        print(f"colour test sent: {result['bytes']} bytes in {result['seconds']}s")
        return 0

    if args.command == "svg":
        result = render.plot_svg(
            args.path,
            page=parse_page(args.page),
            margin=args.margin,
            fit=not args.no_fit,
            speed=args.speed,
            dry_run=bool(args.dry_run),
            rotate_deg=args.rotate,
        )
        if args.dry_run:
            args.dry_run.write_bytes(result["payload"])
            print(f"wrote {result['bytes']} bytes to {args.dry_run}")
        else:
            print(f"sent {result['bytes']} bytes in {result['seconds']}s")
        return 0

    if args.command == "image":
        if args.dry_run:
            plan = raster.build(args.path, width_mm=args.width_mm, dpi=args.dpi,
                                band_rows=args.band_rows,
                                sheet_mm=parse_page(args.fill),
                                rotate=args.rotate)
            args.dry_run.write_bytes(plan.payload)
            print(
                f"wrote {plan.bytes} bytes to {args.dry_run} "
                f"({plan.width_px}x{plan.height_px} px, "
                f"{plan.width_mm:.1f}x{plan.height_mm:.1f} mm at {plan.dpi} dpi)"
            )
        else:
            result = raster.plot_image(args.path, width_mm=args.width_mm, dpi=args.dpi,
                                       band_rows=args.band_rows,
                                       sheet_mm=parse_page(args.fill),
                                       rotate=args.rotate)
            print(
                f"image sent: {result['width_px']}x{result['height_px']} px, "
                f"{result['width_mm']}x{result['height_mm']} mm, "
                f"{result['bytes']} bytes in {result['seconds']}s"
            )
        return 0

    if args.command == "text":
        page = parse_page(args.page) or (297.0, 210.0)
        canvas = Canvas(width_mm=page[0], height_mm=page[1])
        canvas.begin()
        canvas.text(args.x, args.y, args.value, size_mm=args.size)
        result = render.plot_canvas(canvas)
        print(f"sent {result['bytes']} bytes in {result['seconds']}s")
        return 0

    if args.command == "feed":
        canvas = Canvas()
        canvas.raw(b"IN;")
        payload = canvas.dumps(feed=True)
        with UsbPrinter() as printer:
            printer.send(payload)
        print("page fed")
        return 0

    if args.command == "raw":
        payload = args.path.read_bytes()
        with UsbPrinter() as printer:
            elapsed = printer.send(payload)
        print(f"sent {len(payload)} bytes in {elapsed:.3f}s")
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
