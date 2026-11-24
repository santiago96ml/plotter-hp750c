"""Minimal SVG -> drawing model converter.

Supports the subset that matters for plots and AI-generated diagrams:
paths, lines, polylines, polygons, rects, circles, ellipses, text and nested
`translate` / `scale` / `rotate` / `matrix` transforms. Curves and arcs are
flattened into line segments, because HP-GL/2 is a line language.
"""

from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

UNIT_MM = {
    "mm": 1.0,
    "cm": 10.0,
    "in": 25.4,
    "pt": 25.4 / 72.0,
    "pc": 25.4 / 6.0,
    "px": 25.4 / 96.0,
    "": 1.0,
}

NUMBER = r"[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?"


@dataclass
class Poly:
    points: list[tuple[float, float]]
    width_mm: float = 0.35
    fill: bool = False
    closed: bool = False
    color: str = "black"


@dataclass
class Label:
    x: float
    y: float
    text: str
    size_mm: float = 5.0
    color: str = "black"


@dataclass
class Drawing:
    width_mm: float
    height_mm: float
    elements: list[Poly | Label] = field(default_factory=list)

    def bounds(self) -> tuple[float, float, float, float]:
        xs: list[float] = []
        ys: list[float] = []
        for element in self.elements:
            if isinstance(element, Poly):
                xs.extend(p[0] for p in element.points)
                ys.extend(p[1] for p in element.points)
            else:
                xs.append(element.x)
                ys.append(element.y)
        if not xs:
            return 0.0, 0.0, self.width_mm, self.height_mm
        return min(xs), min(ys), max(xs), max(ys)


# -- affine transforms -----------------------------------------------------
Matrix = tuple[float, float, float, float, float, float]  # a b c d e f
IDENTITY: Matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def mat_mul(m1: Matrix, m2: Matrix) -> Matrix:
    a1, b1, c1, d1, e1, f1 = m1
    a2, b2, c2, d2, e2, f2 = m2
    return (
        a1 * a2 + c1 * b2,
        b1 * a2 + d1 * b2,
        a1 * c2 + c1 * d2,
        b1 * c2 + d1 * d2,
        a1 * e2 + c1 * f2 + e1,
        b1 * e2 + d1 * f2 + f1,
    )


def apply(m: Matrix, x: float, y: float) -> tuple[float, float]:
    a, b, c, d, e, f = m
    return a * x + c * y + e, b * x + d * y + f


def parse_transform(value: str | None) -> Matrix:
    if not value:
        return IDENTITY
    m = IDENTITY
    for name, args in re.findall(r"(matrix|translate|scale|rotate|skewX|skewY)\s*\(([^)]*)\)", value):
        nums = [float(n) for n in re.findall(NUMBER, args)]
        if name == "matrix" and len(nums) == 6:
            step: Matrix = tuple(nums)  # type: ignore[assignment]
        elif name == "translate":
            step = (1, 0, 0, 1, nums[0], nums[1] if len(nums) > 1 else 0)
        elif name == "scale":
            sx = nums[0]
            sy = nums[1] if len(nums) > 1 else sx
            step = (sx, 0, 0, sy, 0, 0)
        elif name == "rotate":
            angle = math.radians(nums[0])
            cos, sin = math.cos(angle), math.sin(angle)
            step = (cos, sin, -sin, cos, 0, 0)
            if len(nums) == 3:
                cx, cy = nums[1], nums[2]
                step = mat_mul(mat_mul((1, 0, 0, 1, cx, cy), step), (1, 0, 0, 1, -cx, -cy))
        elif name == "skewX":
            step = (1, 0, math.tan(math.radians(nums[0])), 1, 0, 0)
        elif name == "skewY":
            step = (1, math.tan(math.radians(nums[0])), 0, 1, 0, 0)
        else:
            continue
        m = mat_mul(m, step)
    return m


# -- geometry --------------------------------------------------------------
def _cubic(p0, p1, p2, p3, steps=24):
    out = []
    for i in range(1, steps + 1):
        t = i / steps
        u = 1 - t
        out.append((
            u**3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t**3 * p3[0],
            u**3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t**3 * p3[1],
        ))
    return out


def _quadratic(p0, p1, p2, steps=20):
    out = []
    for i in range(1, steps + 1):
        t = i / steps
        u = 1 - t
        out.append((
            u * u * p0[0] + 2 * u * t * p1[0] + t * t * p2[0],
            u * u * p0[1] + 2 * u * t * p1[1] + t * t * p2[1],
        ))
    return out


def _arc(p0, rx, ry, phi_deg, large, sweep, p1, steps=48):
    x1, y1 = p0
    x2, y2 = p1
    if (x1, y1) == (x2, y2):
        return []
    rx, ry = abs(rx), abs(ry)
    if rx == 0 or ry == 0:
        return [p1]
    phi = math.radians(phi_deg)
    cos_p, sin_p = math.cos(phi), math.sin(phi)
    dx, dy = (x1 - x2) / 2, (y1 - y2) / 2
    x1p = cos_p * dx + sin_p * dy
    y1p = -sin_p * dx + cos_p * dy
    lam = (x1p * x1p) / (rx * rx) + (y1p * y1p) / (ry * ry)
    if lam > 1:
        scale = math.sqrt(lam)
        rx, ry = rx * scale, ry * scale
    num = rx * rx * ry * ry - rx * rx * y1p * y1p - ry * ry * x1p * x1p
    den = rx * rx * y1p * y1p + ry * ry * x1p * x1p
    coef = math.sqrt(max(0.0, num / den)) if den else 0.0
    if large == sweep:
        coef = -coef
    cxp = coef * rx * y1p / ry
    cyp = -coef * ry * x1p / rx
    cx = cos_p * cxp - sin_p * cyp + (x1 + x2) / 2
    cy = sin_p * cxp + cos_p * cyp + (y1 + y2) / 2

    def angle(ux, uy, vx, vy):
        dot = ux * vx + uy * vy
        norm = math.hypot(ux, uy) * math.hypot(vx, vy)
        a = math.acos(max(-1.0, min(1.0, dot / norm))) if norm else 0.0
        return -a if ux * vy - uy * vx < 0 else a

    theta1 = angle(1, 0, (x1p - cxp) / rx, (y1p - cyp) / ry)
    delta = angle((x1p - cxp) / rx, (y1p - cyp) / ry,
                  (-x1p - cxp) / rx, (-y1p - cyp) / ry)
    if not sweep and delta > 0:
        delta -= 2 * math.pi
    elif sweep and delta < 0:
        delta += 2 * math.pi

    out = []
    for i in range(1, steps + 1):
        t = theta1 + delta * i / steps
        out.append((
            cx + rx * math.cos(t) * cos_p - ry * math.sin(t) * sin_p,
            cy + rx * math.cos(t) * sin_p + ry * math.sin(t) * cos_p,
        ))
    return out


def parse_path(d: str) -> list[tuple[list[tuple[float, float]], bool]]:
    """Return subpaths as (points, closed). Absolute and relative commands."""
    tokens = re.findall(r"[MmLlHhVvCcSsQqTtAaZz]|" + NUMBER, d)
    subpaths: list[tuple[list[tuple[float, float]], bool]] = []
    points: list[tuple[float, float]] = []
    cur = (0.0, 0.0)
    start = (0.0, 0.0)
    last_cubic: tuple[float, float] | None = None
    last_quad: tuple[float, float] | None = None
    i = 0
    command = None

    def flush(closed=False):
        nonlocal points
        if len(points) > 1:
            subpaths.append((points, closed))
        points = []

    while i < len(tokens):
        token = tokens[i]
        if token.isalpha():
            command = token
            i += 1
            if command in "Zz":
                if points:
                    points.append(start)
                    flush(closed=True)
                cur = start
                continue
            continue

        if command is None:
            i += 1
            continue

        def num():
            nonlocal i
            value = float(tokens[i])
            i += 1
            return value

        rel = command.islower()
        op = command.upper()

        if op == "M":
            x, y = num(), num()
            if rel:
                x, y = x + cur[0], y + cur[1]
            flush()
            cur = start = (x, y)
            points = [(x, y)]
            command = "l" if rel else "L"
            last_cubic = last_quad = None
        elif op == "L":
            x, y = num(), num()
            if rel:
                x, y = x + cur[0], y + cur[1]
            cur = (x, y)
            points.append(cur)
            last_cubic = last_quad = None
        elif op == "H":
            x = num() + (cur[0] if rel else 0)
            cur = (x, cur[1])
            points.append(cur)
            last_cubic = last_quad = None
        elif op == "V":
            y = num() + (cur[1] if rel else 0)
            cur = (cur[0], y)
            points.append(cur)
            last_cubic = last_quad = None
        elif op in "CS":
            if op == "C":
                c1 = (num(), num())
                c2 = (num(), num())
            else:
                c1 = last_cubic if last_cubic else cur
                c2 = (num(), num())
            end = (num(), num())
            if rel:
                c1 = (c1[0] + cur[0], c1[1] + cur[1])
                c2 = (c2[0] + cur[0], c2[1] + cur[1])
                end = (end[0] + cur[0], end[1] + cur[1])
            points.extend(_cubic(cur, c1, c2, end))
            last_cubic, last_quad = c2, None
            cur = end
        elif op in "QT":
            if op == "Q":
                c = (num(), num())
            else:
                c = last_quad if last_quad else cur
            end = (num(), num())
            if rel:
                c = (c[0] + cur[0], c[1] + cur[1])
                end = (end[0] + cur[0], end[1] + cur[1])
            points.extend(_quadratic(cur, c, end))
            last_quad, last_cubic = c, None
            cur = end
        elif op == "A":
            rx, ry, phi, large, sweep = num(), num(), num(), num(), num()
            end = (num(), num())
            if rel:
                end = (end[0] + cur[0], end[1] + cur[1])
            points.extend(_arc(cur, rx, ry, phi, bool(large), bool(sweep), end))
            cur = end
            last_cubic = last_quad = None
        else:
            i += 1

    flush()
    return subpaths


# -- styling ---------------------------------------------------------------
def _style(el: ET.Element) -> dict[str, str]:
    style = {}
    for part in (el.get("style") or "").split(";"):
        if ":" in part:
            key, value = part.split(":", 1)
            style[key.strip()] = value.strip()
    for key in ("stroke", "fill", "stroke-width", "font-size", "font-family"):
        value = el.get(key)
        if value is not None:
            style[key] = value
    return style


def _is_hidden(el: ET.Element) -> bool:
    return (el.get("display") == "none") or (el.get("visibility") == "hidden")


def _length(value: str | None, default: float = 0.0) -> float:
    if not value:
        return default
    match = re.match(r"\s*(" + NUMBER + r")\s*([a-z%]*)", value)
    if not match:
        return default
    number, unit = float(match.group(1)), match.group(2)
    return number * UNIT_MM.get(unit, 1.0)


def _tag(el: ET.Element) -> str:
    return el.tag.split("}")[-1]


def _num(el: ET.Element, name: str, default: float = 0.0) -> float:
    raw = el.get(name)
    return _length(raw, default) if raw else default


# -- conversion ------------------------------------------------------------
def load(svg: str | Path) -> Drawing:
    text = svg.read_text(encoding="utf-8") if isinstance(svg, Path) else (
        Path(svg).read_text(encoding="utf-8") if Path(svg).exists() else svg
    )
    root = ET.fromstring(text)

    vb = re.findall(NUMBER, root.get("viewBox") or "")
    vb_x, vb_y = (float(vb[0]), float(vb[1])) if len(vb) == 4 else (0.0, 0.0)
    vb_w = float(vb[2]) if len(vb) == 4 else _length(root.get("width"), 100.0)
    vb_h = float(vb[3]) if len(vb) == 4 else _length(root.get("height"), 100.0)

    width_mm = _length(root.get("width"), 0.0) or vb_w
    height_mm = _length(root.get("height"), 0.0) or vb_h

    sx = width_mm / vb_w if vb_w else 1.0
    sy = height_mm / vb_h if vb_h else 1.0
    # map viewBox user units to millimetres keeping a top-left origin (Y grows down)
    root_matrix: Matrix = (sx, 0, 0, sy, -vb_x * sx, -vb_y * sy)

    drawing = Drawing(width_mm=width_mm, height_mm=height_mm)
    _walk(root, root_matrix, drawing, default_width=0.35)
    return drawing


def _walk(el: ET.Element, matrix: Matrix, drawing: Drawing, default_width: float) -> None:
    if _is_hidden(el):
        return
    matrix = mat_mul(matrix, parse_transform(el.get("transform")))
    tag = _tag(el)
    style = _style(el)

    stroke = style.get("stroke", "black")
    default_fill = "black" if tag == "text" else "none"
    fill = style.get("fill", default_fill)
    width = _length(style.get("stroke-width"), default_width)
    if width <= 0:
        width = default_width

    filled = fill not in ("none", "transparent")
    stroked = stroke not in ("none", "transparent")
    color = stroke if stroked else fill

    if tag == "g":
        pass
    elif not (filled or stroked):
        pass
    elif tag == "path":
        for points, closed in parse_path(el.get("d") or ""):
            drawing.elements.append(Poly(
                [apply(matrix, x, y) for x, y in points],
                width_mm=width,
                fill=filled and closed,
                closed=closed,
                color=color,
            ))
    elif tag in ("polyline", "polygon"):
        nums = [float(n) for n in re.findall(NUMBER, el.get("points") or "")]
        points = [apply(matrix, nums[i], nums[i + 1]) for i in range(0, len(nums) - 1, 2)]
        drawing.elements.append(Poly(
            points, width_mm=width,
            fill=(tag == "polygon" and filled),
            closed=(tag == "polygon"),
            color=color,
        ))
    elif tag == "line":
        p0 = apply(matrix, _num(el, "x1"), _num(el, "y1"))
        p1 = apply(matrix, _num(el, "x2"), _num(el, "y2"))
        drawing.elements.append(Poly([p0, p1], width_mm=width, color=color))
    elif tag == "rect":
        x, y = _num(el, "x"), _num(el, "y")
        w, h = _num(el, "width"), _num(el, "height")
        corners = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
        drawing.elements.append(Poly(
            [apply(matrix, px, py) for px, py in corners],
            width_mm=width,
            fill=filled,
            closed=True,
            color=color,
        ))
    elif tag in ("circle", "ellipse"):
        cx, cy = _num(el, "cx"), _num(el, "cy")
        rx = _num(el, "r") if tag == "circle" else _num(el, "rx")
        ry = _num(el, "r") if tag == "circle" else _num(el, "ry")
        points = [
            apply(matrix, cx + rx * math.cos(2 * math.pi * i / 72),
                  cy + ry * math.sin(2 * math.pi * i / 72))
            for i in range(72)
        ]
        drawing.elements.append(Poly(
            points, width_mm=width,
            fill=filled, closed=True,
            color=color,
        ))
    elif tag == "text":
        content = " ".join("".join(el.itertext()).split())
        if content:
            x, y = _num(el, "x"), _num(el, "y")
            px, py = apply(matrix, x, y)
            size = _length(style.get("font-size"), 0.0)
            if not size:
                size = drawing.height_mm * 0.02
            scale = math.hypot(matrix[0], matrix[1]) or 1.0
            drawing.elements.append(Label(
                px, py, content, size_mm=size * scale, color=fill if filled else stroke
            ))

    for child in el:
        if _tag(child) in ("defs", "style", "title", "desc", "metadata"):
            continue
        _walk(child, matrix, drawing, width)


def rotate(drawing: Drawing, degrees: int, clockwise: bool = True) -> Drawing:
    """Rotate the drawing on the page, swapping dimensions for quarter turns."""
    angle = degrees % 360
    if angle == 0:
        return drawing
    w, h = drawing.width_mm, drawing.height_mm

    if angle == 180:
        def move(x: float, y: float) -> tuple[float, float]:
            return w - x, h - y

        out = Drawing(w, h)
    elif angle == 90:
        def move(x: float, y: float) -> tuple[float, float]:
            return (h - y, x) if clockwise else (y, w - x)

        out = Drawing(h, w)
    else:  # 270
        def move(x: float, y: float) -> tuple[float, float]:
            return (y, w - x) if clockwise else (h - y, x)

        out = Drawing(h, w)

    for element in drawing.elements:
        if isinstance(element, Poly):
            out.elements.append(Poly(
                [move(x, y) for x, y in element.points],
                width_mm=element.width_mm, fill=element.fill,
                closed=element.closed, color=element.color,
            ))
        else:
            out.elements.append(Label(
                *move(element.x, element.y), element.text,
                size_mm=element.size_mm, color=element.color,
            ))
    return out


def fit(drawing: Drawing, page_w: float, page_h: float, margin: float = 10.0) -> Drawing:
    """Scale and centre the drawing inside a page, preserving aspect ratio."""
    x0, y0, x1, y1 = drawing.bounds()
    w = max(x1 - x0, 1e-6)
    h = max(y1 - y0, 1e-6)
    scale = min((page_w - 2 * margin) / w, (page_h - 2 * margin) / h)
    offset_x = (page_w - w * scale) / 2 - x0 * scale
    offset_y = (page_h - h * scale) / 2 - y0 * scale

    def move(x: float, y: float) -> tuple[float, float]:
        return x * scale + offset_x, y * scale + offset_y

    out = Drawing(page_w, page_h)
    for element in drawing.elements:
        if isinstance(element, Poly):
            out.elements.append(Poly(
                [move(x, y) for x, y in element.points],
                width_mm=element.width_mm, fill=element.fill,
                closed=element.closed, color=element.color,
            ))
        else:
            out.elements.append(Label(
                *move(element.x, element.y), element.text,
                size_mm=element.size_mm * scale, color=element.color,
            ))
    return out
