"""Turn a drawing model into HP-GL/2 and send it to the plotter."""

from __future__ import annotations

from . import colors, svg
from .hpgl2 import Canvas
from .usbprint import UsbPrinter


def to_canvas(drawing: svg.Drawing, speed: float | None = None) -> Canvas:
    canvas = Canvas(width_mm=drawing.width_mm, height_mm=drawing.height_mm)
    canvas.begin(speed=speed)
    current_pen = 1
    for element in drawing.elements:
        rgb = colors.parse(element.color)
        # White means "leave the paper alone": the plotter has no white ink.
        if rgb is not None and min(rgb) > 245:
            continue
        pen = colors.nearest_pen(rgb, default=1)
        if pen != current_pen:
            canvas.pen(pen)
            canvas.pen_color(colors.PEN_PALETTE[pen])
            current_pen = pen
        if isinstance(element, svg.Poly):
            canvas.line_width(element.width_mm)
            if element.fill and element.closed:
                canvas.polygon(element.points, fill=True)
            else:
                canvas.polyline(element.points, close=element.closed)
        elif isinstance(element, svg.Label):
            canvas.text(element.x, element.y, element.text, size_mm=element.size_mm)
    return canvas


def plot_svg(
    path,
    page: tuple[float, float] | None = None,
    margin: float = 10.0,
    fit: bool = True,
    speed: float | None = None,
    dry_run: bool = False,
    rotate_deg: int = 0,
) -> dict:
    drawing = svg.load(path)
    if rotate_deg:
        drawing = svg.rotate(drawing, rotate_deg)
    if page and fit:
        drawing = svg.fit(drawing, page[0], page[1], margin)
    canvas = to_canvas(drawing, speed=speed)
    payload = canvas.dumps(feed=True)

    if dry_run:
        return {"bytes": len(payload), "sent": False, "payload": payload}

    with UsbPrinter() as printer:
        elapsed = printer.send(payload)
    return {"bytes": len(payload), "sent": True, "seconds": round(elapsed, 3)}


def plot_canvas(canvas: Canvas, dry_run: bool = False) -> dict:
    payload = canvas.dumps(feed=True)
    if dry_run:
        return {"bytes": len(payload), "sent": False, "payload": payload}
    with UsbPrinter() as printer:
        elapsed = printer.send(payload)
    return {"bytes": len(payload), "sent": True, "seconds": round(elapsed, 3)}
