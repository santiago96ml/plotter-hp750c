"""Ready-made pages: self test and colour test."""

from __future__ import annotations

from datetime import datetime

from .hpgl2 import Canvas

PEN_NAMES = {1: "PEN 1 - BLACK", 2: "PEN 2 - CYAN", 3: "PEN 3 - MAGENTA", 4: "PEN 4 - YELLOW"}
PEN_RGB = {1: (0, 0, 0), 2: (0, 255, 255), 3: (255, 0, 255), 4: (255, 255, 0)}


def _claim_pens(canvas: Canvas) -> None:
    """Declare each pen's colour explicitly instead of relying on pen order."""
    for pen, rgb in PEN_RGB.items():
        canvas.pen(pen)
        canvas.pen_color(rgb)


def selftest_canvas(width: float = 280.0, height: float = 190.0) -> Canvas:
    canvas = Canvas(width_mm=width, height_mm=height)
    canvas.begin()
    canvas.rect(5, 5, width - 10, height - 10)
    canvas.text(12, 22, "HP DESIGNJET 750C PLUS", size_mm=10)
    canvas.text(12, 40, "USB -> parallel, raw HP-GL/2", size_mm=6)
    canvas.text(12, 55, "No driver. No print queue.", size_mm=6)
    canvas.text(12, 70, datetime.now().strftime("Test %Y-%m-%d %H:%M"), size_mm=6)
    canvas.move(12, 85)
    canvas.draw_to(width - 12, height - 12)
    canvas.move(12, height - 12)
    canvas.draw_to(width - 12, 85)
    canvas.circle(width / 2, height / 2, 25)
    canvas.text(12, height - 10, "If you can read this, the whole chain works.", size_mm=6)
    return canvas


def color_test_canvas(width: float = 280.0, height: float = 190.0) -> Canvas:
    """Four labelled pen squares, so the physical pen order can be verified."""
    canvas = Canvas(width_mm=width, height_mm=height)
    canvas.begin()
    _claim_pens(canvas)
    canvas.rect(5, 5, width - 10, height - 10)
    canvas.text(12, 20, "PEN / COLOUR MAPPING TEST", size_mm=8)

    box, gap = 55.0, 8.0
    top = 40.0
    for index, pen in enumerate(sorted(PEN_NAMES)):
        x = 12 + index * (box + gap)
        canvas.pen(pen)
        canvas.line_width(0.4)
        canvas.rect(x, top, box, box)
        canvas.move(x, top + box)
        canvas.draw_to(x + box, top)
        canvas.move(x, top)
        canvas.draw_to(x + box, top + box)
        canvas.text(x, top + box + 14, PEN_NAMES[pen], size_mm=6)
        canvas.text(x, top + box + 28, "check the real colour", size_mm=4)

    canvas.pen(1)
    canvas.text(12, height - 12, "Tell the agent which square came out in which colour.", size_mm=5)
    return canvas


def color_quick_canvas(width: float = 160.0, height: float = 95.0) -> Canvas:
    """Fast pen check: four thick bars instead of filled areas."""
    canvas = Canvas(width_mm=width, height_mm=height)
    canvas.begin()
    _claim_pens(canvas)
    for index, pen in enumerate(sorted(PEN_NAMES)):
        y = 16 + index * 18
        canvas.pen(pen)
        canvas.line_width(2.5)
        canvas.move(12, y)
        canvas.draw_to(68, y)
        canvas.pen(1)
        canvas.line_width(0.35)
        canvas.text(74, y + 2, PEN_NAMES[pen], size_mm=5)
    canvas.text(12, height - 8, "quick pen test", size_mm=4)
    return canvas
