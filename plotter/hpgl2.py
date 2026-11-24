"""A small HP-GL/2 composer.

The DesignJet 750C works in plotter units: 1 unit = 1/40 mm (0.025 mm).
Callers draw in millimetres with a top-left origin (like SVG); this module
flips the Y axis and emits the commands.
"""

from __future__ import annotations

from dataclasses import dataclass, field

MM = 40.0  # plotter units per millimetre
ETX = b"\x03"


@dataclass
class Canvas:
    width_mm: float = 420.0
    height_mm: float = 297.0
    _parts: list[bytes] = field(default_factory=list)
    _pen: int = 1
    _down: bool = False
    _pos: tuple[float, float] = (0.0, 0.0)

    # -- low level ---------------------------------------------------------
    def raw(self, data: bytes | str) -> "Canvas":
        self._parts.append(data.encode("latin-1") if isinstance(data, str) else data)
        return self

    def _u(self, x: float, y: float) -> tuple[int, int]:
        return round(x * MM), round((self.height_mm - y) * MM)

    def _cmd(self, text: str) -> "Canvas":
        return self.raw(text)

    # -- setup -------------------------------------------------------------
    def begin(self, pen: int = 1, speed: float | None = None) -> "Canvas":
        # ESC % 0 B enters HP-GL/2 mode; IN initialises the plotter.
        self.raw(b"\x1b%0B")
        self._cmd("IN;")
        self.pen(pen)
        if speed is not None:
            self.speed(speed)
        return self

    def pen(self, number: int) -> "Canvas":
        self._pen = number
        return self._cmd(f"SP{number};")

    def pen_color(self, rgb: tuple[int, int, int], pen: int | None = None) -> "Canvas":
        """Assign a colour to a pen. HP-GL/2 takes RGB as percentages."""
        r, g, b = rgb
        suffix = f",{pen}" if pen is not None else ""
        return self._cmd(
            f"PC{round(r / 255 * 100)},{round(g / 255 * 100)},{round(b / 255 * 100)}{suffix};"
        )

    def speed(self, cm_per_second: float) -> "Canvas":
        return self._cmd(f"VS{cm_per_second:g};")

    def line_width(self, width_mm: float) -> "Canvas":
        return self._cmd(f"PW{max(1, round(width_mm * MM))};")

    # -- motion ------------------------------------------------------------
    def move(self, x: float, y: float) -> "Canvas":
        ux, uy = self._u(x, y)
        self._cmd(f"PU{ux},{uy};")
        self._down = False
        self._pos = (x, y)
        return self

    def line(self, x: float, y: float) -> "Canvas":
        ux, uy = self._u(x, y)
        self._cmd(("PD" if self._down else "PU") + f"{ux},{uy};")
        self._pos = (x, y)
        return self

    def draw_to(self, x: float, y: float) -> "Canvas":
        self._down = True
        return self.line(x, y)

    def polyline(self, points, close: bool = False) -> "Canvas":
        pts = list(points)
        if not pts:
            return self
        self.move(*pts[0])
        if len(pts) == 1:
            return self
        coords = [self._u(x, y) for x, y in pts[1:]]
        if close:
            coords.append(self._u(*pts[0]))
        body = ",".join(f"{x},{y}" for x, y in coords)
        self._cmd("PD" + body + ";")
        self._down = True
        self._pos = pts[-1]
        return self

    def rect(self, x: float, y: float, w: float, h: float) -> "Canvas":
        return self.polyline(
            [(x, y), (x + w, y), (x + w, y + h), (x, y + h)], close=True
        )

    def circle(self, cx: float, cy: float, r: float, steps: int = 72) -> "Canvas":
        import math

        pts = [
            (cx + r * math.cos(2 * math.pi * i / steps),
             cy + r * math.sin(2 * math.pi * i / steps))
            for i in range(steps)
        ]
        return self.polyline(pts, close=True)

    def polygon(self, points, fill: bool = True) -> "Canvas":
        pts = list(points)
        if len(pts) < 3:
            return self
        self._cmd("PM0;")
        self.polyline(pts, close=True)
        self._cmd("PM1;")
        if fill:
            self._cmd("FT1;FP;")
        return self

    # -- text --------------------------------------------------------------
    def text(
        self,
        x: float,
        y: float,
        value: str,
        size_mm: float = 5.0,
        angle_deg: float = 0.0,
    ) -> "Canvas":
        import math

        clean = "".join(ch for ch in value if ch >= " " and ch != "\x03")
        ux, uy = self._u(x, y)
        radians = math.radians(angle_deg)
        dx = round(math.cos(radians), 3) or 0.0
        dy = round(math.sin(radians), 3) or 0.0
        self._cmd(f"PU{ux},{uy};DI{dx},{dy};SI{size_mm / 10:g},{size_mm / 10:g};")
        self.raw(b"LB" + clean.encode("latin-1", "replace") + ETX)
        self._cmd("DI0,1;")
        return self

    # -- finish ------------------------------------------------------------
    def feed(self) -> "Canvas":
        return self._cmd("PG;")

    def dumps(self, feed: bool = True) -> bytes:
        body = b"".join(self._parts)
        suffix = b"PU;"
        if feed:
            suffix += b"PG;"
        return body + (suffix if body else b"")
