"""MCP server exposing the DesignJet 750C to AI agents.

Every tool talks straight to the USB printer interface: no driver, no spooler.
Tools that actually plot end by feeding the page, so a job is never left half
buffered inside the plotter.
"""

from __future__ import annotations

import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from . import raster, render, svg
from .hpgl2 import Canvas
from .pages import color_test_canvas, selftest_canvas
from .usbprint import UsbPrinter, list_devices

PAGES = {
    "A4": (297.0, 210.0),
    "A3": (420.0, 297.0),
    "A2": (594.0, 420.0),
    "A1": (841.0, 594.0),
    "A0": (1189.0, 841.0),
    "roll": (841.0, 594.0),
}

mcp = FastMCP("designjet-750c")


def _page(name: str) -> tuple[float, float]:
    key = (name or "").strip().upper()
    if key in PAGES:
        return PAGES[key]
    if "X" in key:
        width, height = key.split("X", 1)
        return float(width), float(height)
    raise ValueError(f"Unknown page size '{name}'. Use A4..A0 or WIDTHxHEIGHT in mm.")


@mcp.tool()
def plotter_status() -> dict:
    """Report whether the plotter is reachable over USB and can be opened."""
    devices = list_devices()
    result = {
        "interfaces": [d.short for d in devices],
        "openable": False,
        "note": "HP DesignJet 750C Plus, raw HP-GL/2 over USB, no driver needed.",
    }
    if devices:
        try:
            with UsbPrinter():
                result["openable"] = True
        except OSError as exc:
            result["error"] = str(exc)
    return result


@mcp.tool()
def plot_selftest() -> dict:
    """Plot a small self-test page: frame, labels, diagonal and circle."""
    return render.plot_canvas(selftest_canvas())


@mcp.tool()
def plot_color_test() -> dict:
    """Plot four labelled squares, one per pen, to verify the physical pen order.

    The 750C has four cartridges (black, cyan, magenta, yellow). If the front
    panel shows MONOCHROME, the colour cartridges are missing or not detected
    and every pen will print black.
    """
    return render.plot_canvas(color_test_canvas())


@mcp.tool()
def plot_svg(
    path: str,
    page: str = "A3",
    margin_mm: float = 10.0,
    fit: bool = True,
    speed_cm_s: float | None = None,
    rotate_deg: int = 0,
    dry_run: bool = False,
) -> dict:
    """Plot an SVG file.

    Args:
        path: absolute path to the .svg file.
        page: A4, A3, A2, A1, A0, roll, or WIDTHxHEIGHT in millimetres.
        margin_mm: page margin used when fitting.
        fit: scale the drawing to fit the page. False keeps its own size.
        speed_cm_s: pen speed in cm/s. Omit for the plotter default.
        rotate_deg: rotate the drawing 0, 90, 180 or 270 degrees on the page.
        dry_run: only count bytes, do not send anything to the plotter.
    """
    file = Path(path)
    if not file.exists():
        raise FileNotFoundError(path)
    width, height = _page(page)
    result = render.plot_svg(
        file,
        page=(width, height),
        margin=margin_mm,
        fit=fit,
        speed=speed_cm_s,
        dry_run=dry_run,
        rotate_deg=rotate_deg,
    )
    result.pop("payload", None)
    return result


@mcp.tool()
def plot_image(
    path: str,
    width_mm: float | None = None,
    dpi: int = 300,
    band_rows: int = 800,
    fill: str | None = None,
    rotate: int = 0,
    dry_run: bool = False,
) -> dict:
    """Print a JPEG or PNG as an HP RTL colour raster.

    Args:
        path: absolute path to the image file.
        width_mm: printed width in millimetres. Omit to keep the image's own
            pixels at the chosen resolution.
        dpi: raster resolution. The 750C prints colour at 300 dpi.
        band_rows: rows per raster band. Bands keep the 11 MB plotter buffer
            from overflowing on big images.
        fill: cover a page size (A4..A0 or WIDTHxHEIGHT mm), cropping the
            excess. A portrait poster on a landscape sheet prints sideways;
            turn the sheet to read it.
        rotate: rotate the image clockwise (0/90/180/270) before composing.
        dry_run: compose and measure the job without sending it.
    """
    file = Path(path)
    if not file.exists():
        raise FileNotFoundError(path)
    sheet = _page(fill) if fill else None
    return raster.plot_image(
        file, width_mm=width_mm, dpi=dpi, band_rows=band_rows,
        sheet_mm=sheet, rotate=rotate, dry_run=dry_run,
    )


@mcp.tool()
def plot_polylines(
    polylines: list[list[list[float]]],
    page: str = "A3",
    close: bool = False,
    speed_cm_s: float | None = None,
    dry_run: bool = False,
) -> dict:
    """Plot raw geometry given as millimetre coordinates.

    Args:
        polylines: list of polylines; each polyline is a list of [x, y] in mm.
        page: A4, A3, A2, A1, A0, roll, or WIDTHxHEIGHT in millimetres.
        close: join the last point back to the first on every polyline.
        speed_cm_s: pen speed in cm/s.
        dry_run: only count bytes.
    """
    width, height = _page(page)
    canvas = Canvas(width_mm=width, height_mm=height)
    canvas.begin(speed=speed_cm_s)
    for line in polylines:
        canvas.polyline([(float(x), float(y)) for x, y in line], close=close)
    return render.plot_canvas(canvas, dry_run=dry_run)


@mcp.tool()
def plot_text(
    text: str,
    size_mm: float = 8.0,
    x_mm: float = 10.0,
    y_mm: float = 20.0,
    page: str = "A4",
) -> dict:
    """Plot one line of text at millimetre coordinates (origin top-left)."""
    width, height = _page(page)
    canvas = Canvas(width_mm=width, height_mm=height)
    canvas.begin()
    canvas.text(x_mm, y_mm, text, size_mm=size_mm)
    return render.plot_canvas(canvas)


@mcp.tool()
def feed_page() -> dict:
    """Advance the media by one page."""
    canvas = Canvas()
    canvas.raw(b"IN;")
    return render.plot_canvas(canvas)


def main() -> None:
    # stdout belongs to the JSON-RPC channel: log only to stderr.
    print("designjet-750c MCP server ready", file=sys.stderr)
    mcp.run()


if __name__ == "__main__":
    main()
