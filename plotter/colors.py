"""Colour handling: map arbitrary RGB to the plotter's four pens."""

from __future__ import annotations

import re

# HP DesignJet 750C in HP-GL/2 mode addresses four pens. Which cartridge each
# pen drives is verified empirically with the colour test page; this table is
# the mapping used by the renderer.
PEN_PALETTE: dict[int, tuple[int, int, int]] = {
    1: (0, 0, 0),        # black
    2: (0, 255, 255),    # cyan
    3: (255, 0, 255),    # magenta
    4: (255, 255, 0),    # yellow
}

NAMED: dict[str, tuple[int, int, int]] = {
    "black": (0, 0, 0),
    "white": (255, 255, 255),
    "red": (255, 0, 0),
    "lime": (0, 255, 0),
    "green": (0, 128, 0),
    "blue": (0, 0, 255),
    "cyan": (0, 255, 255),
    "aqua": (0, 255, 255),
    "magenta": (255, 0, 255),
    "fuchsia": (255, 0, 255),
    "yellow": (255, 255, 0),
    "gray": (128, 128, 128),
    "grey": (128, 128, 128),
    "silver": (192, 192, 192),
    "maroon": (128, 0, 0),
    "olive": (128, 128, 0),
    "navy": (0, 0, 128),
    "teal": (0, 128, 128),
    "purple": (128, 0, 128),
    "orange": (255, 165, 0),
    "brown": (165, 42, 42),
    "pink": (255, 192, 203),
    "darkblue": (0, 0, 139),
    "darkgreen": (0, 100, 0),
    "darkred": (139, 0, 0),
    "lightgray": (211, 211, 211),
    "lightgrey": (211, 211, 211),
}

_HEX = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
_RGB = re.compile(r"^rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)")


def parse(value: str | None) -> tuple[int, int, int] | None:
    """Parse a CSS colour into RGB. Returns None for none/transparent/unknown."""
    if not value:
        return None
    text = value.strip().lower()
    if text in ("none", "transparent", "inherit", "currentcolor"):
        return None
    if text in NAMED:
        return NAMED[text]
    match = _HEX.match(text)
    if match:
        digits = match.group(1)
        if len(digits) == 3:
            digits = "".join(c * 2 for c in digits)
        return int(digits[0:2], 16), int(digits[2:4], 16), int(digits[4:6], 16)
    match = _RGB.match(text)
    if match:
        return tuple(min(255, int(float(g))) for g in match.groups())  # type: ignore[return-value]
    return None


def nearest_pen(rgb: tuple[int, int, int] | None, default: int = 1) -> int:
    """Pick the pen whose cartridge best reproduces the requested colour."""
    if rgb is None:
        return default
    # Weighted distance: green carries most of the perceived brightness.
    weights = (2.0, 4.0, 3.0)

    def distance(candidate: tuple[int, int, int]) -> float:
        return sum(w * (a - b) ** 2 for w, a, b in zip(weights, rgb, candidate))

    return min(PEN_PALETTE, key=lambda pen: distance(PEN_PALETTE[pen]))
