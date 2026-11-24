"""HP RTL raster printing: photographs and bitmaps on the DesignJet 750C.

The 750C is an inkjet plotter, not a pen plotter: besides HP-GL/2 vectors it
speaks HP RTL (HP's Raster Transfer Language). This module composes a raw HP
RTL job that carries a 24-bit RGB image and writes it over the same USB pipe
used by the vector path.

Protocol notes (HP-GL/2 and HP RTL Reference Guide, HP part 5961-3526):

* ESC E resets the device; ESC%0A enters HP RTL from HP-GL/2.
* ESC*v18W plus 18 bytes configures colour imaging: colour space 0 (device
  RGB), pixel encoding 3 (direct by pixel), 8 bits per index, 8/8/8 bits per
  primary, white references 255 and black references 0.
* ESC*t#R sets the graphics resolution. The 750C prints colour at 300 dpi.
* ESC*r#S and ESC*r#T declare the source size in pixels.
* ESC*r0A starts raster mode at the left edge of the logical page.
* Every row is sent as ESC*b#W followed by # RGB bytes.
* ESC*rC ends raster mode; ESC%0B returns to HP-GL/2 and PG advances the page.

Decoding the picture needs Pillow, which is only imported when an image is
actually loaded. The vector commands keep working without it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .usbprint import UsbPrinter

ESC = b"\x1b"

# The 750C prints colour at 300 x 300 dpi; black-only vector plots reach 600.
COLOR_DPI = 300

# HP RTL caps source dimensions at 65 535 pixels.
MAX_PIXELS = 65_535


@dataclass(frozen=True)
class RasterPlan:
    """A complete HP RTL job plus the metadata needed to report it."""

    width_px: int
    height_px: int
    dpi: int
    payload: bytes

    @property
    def bytes(self) -> int:
        return len(self.payload)

    @property
    def width_mm(self) -> float:
        return self.width_px / self.dpi * 25.4

    @property
    def height_mm(self) -> float:
        return self.height_px / self.dpi * 25.4


def configure_image_data() -> bytes:
    """Return the Configure Image Data command for direct 24-bit RGB."""
    header = bytes((0, 3, 8, 8, 8, 8))
    header += (255).to_bytes(2, "big") * 3  # white references: R, G, B
    header += (0).to_bytes(2, "big") * 3  # black references: R, G, B
    return ESC + b"*v18W" + header


def _cover(image, target_w: int, target_h: int):
    """Scale and centre-crop so the image fills exactly target_w x target_h."""
    from PIL import Image

    scale = max(target_w / image.width, target_h / image.height)
    scaled_w = max(target_w, round(image.width * scale))
    scaled_h = max(target_h, round(image.height * scale))
    image = image.resize((scaled_w, scaled_h), Image.LANCZOS)
    left = (scaled_w - target_w) // 2
    top = (scaled_h - target_h) // 2
    return image.crop((left, top, left + target_w, top + target_h))


def _load_rgb(
    path: str | Path,
    width_mm: float | None,
    dpi: int,
    sheet_mm: tuple[float, float] | None = None,
    rotate: int = 0,
) -> tuple[bytes, int, int]:
    from PIL import Image

    with Image.open(path) as image:
        image = image.convert("RGB")
        if rotate % 360:
            # PIL rotates counter-clockwise; positive values here mean clockwise.
            image = image.rotate(-(rotate % 360), expand=True)
        if sheet_mm:
            # On roll media the 750C maps source width to the page X axis and
            # source height to the feed axis, so the bitmap is printed as-is.
            page_w, page_h = sheet_mm
            target_w = max(1, round(page_w / 25.4 * dpi))
            target_h = max(1, round(page_h / 25.4 * dpi))
            image = _cover(image, target_w, target_h)
        elif width_mm:
            target_w = max(1, round(width_mm / 25.4 * dpi))
            if target_w != image.width:
                target_h = max(1, round(image.height * target_w / image.width))
                image = image.resize((target_w, target_h), Image.LANCZOS)
        width, height = image.size
        if width > MAX_PIXELS or height > MAX_PIXELS:
            raise ValueError(
                f"image is {width}x{height}; HP RTL allows at most {MAX_PIXELS} pixels per side"
            )
        return image.tobytes(), width, height


def build(
    path: str | Path,
    width_mm: float | None = None,
    dpi: int = COLOR_DPI,
    band_rows: int = 800,
    sheet_mm: tuple[float, float] | None = None,
    rotate: int = 0,
) -> RasterPlan:
    """Compose the HP RTL job for one image without touching the plotter.

    The 750C Plus ships with 11 MB of memory, so a full A5-sized 24-bit image
    (12.9 MB at 300 dpi) is sent in horizontal bands. Each band is an
    independent raster sequence and the plotter stacks them because End Raster
    Graphics leaves the CAP on the first row of the next band.

    ``sheet_mm`` is the printable media area in millimetres, width across the
    carriage: (904, 675) for an A0-width roll and a landscape print. The image
    is scaled and cropped to cover that area exactly.
    """
    if dpi <= 0:
        raise ValueError("dpi must be positive")
    if band_rows <= 0:
        raise ValueError("band_rows must be positive")
    rgb, width, height = _load_rgb(path, width_mm, dpi, sheet_mm, rotate)
    stride = width * 3

    parts: list[bytes] = [
        ESC + b"E",                     # reset: CAP to 0,0 and default page
        ESC + b"%0A",                   # enter HP RTL mode
        configure_image_data(),
        ESC + f"*t{dpi}R".encode(),     # graphics resolution
    ]
    for top in range(0, height, band_rows):
        rows = min(band_rows, height - top)
        parts.append(ESC + f"*r{width}S".encode())   # source raster width
        parts.append(ESC + f"*r{rows}T".encode())    # source raster height
        parts.append(ESC + b"*r0A")                  # start at the left bound
        for row in range(top, top + rows):
            start = row * stride
            parts.append(ESC + f"*b{stride}W".encode() + rgb[start:start + stride])
        parts.append(ESC + b"*rC")                   # end raster mode
    parts.append(ESC + b"%0B")          # back to HP-GL/2
    parts.append(b"PG;")                # eject the page

    return RasterPlan(width_px=width, height_px=height, dpi=dpi, payload=b"".join(parts))


def send(plan: RasterPlan, timeout: float = 120.0) -> float:
    """Write the job to the plotter and return the elapsed seconds."""
    with UsbPrinter(timeout=timeout) as printer:
        return printer.send(plan.payload)


def plot_image(
    path: str | Path,
    width_mm: float | None = None,
    dpi: int = COLOR_DPI,
    band_rows: int = 800,
    sheet_mm: tuple[float, float] | None = None,
    rotate: int = 0,
    dry_run: bool = False,
) -> dict:
    """Print an image, or just measure the job when dry_run is set."""
    plan = build(path, width_mm=width_mm, dpi=dpi, band_rows=band_rows,
                 sheet_mm=sheet_mm, rotate=rotate)
    result = {
        "width_px": plan.width_px,
        "height_px": plan.height_px,
        "width_mm": round(plan.width_mm, 1),
        "height_mm": round(plan.height_mm, 1),
        "dpi": plan.dpi,
        "bytes": plan.bytes,
        "sent": False,
    }
    if dry_run:
        return result
    result["seconds"] = round(send(plan), 3)
    result["sent"] = True
    return result
