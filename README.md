# HP DesignJet 750C over raw USB

Drive a 1996 HP DesignJet 750C Plus from Windows 11 x64 with **no driver, no
print queue and no administrator rights**.

## Why this exists

HP never shipped a 64-bit driver for the 750C. The official support ended around
Windows XP, and the printer is not listed by any modern Windows version. The
usual advice ("install the driver") cannot work.

The plotter, however, never needed a driver: it speaks HP-GL/2, a plain-text
command language. What it needs is a byte pipe. A cheap USB-to-parallel adapter
(USB printer class, `usbprint.sys`) already provides one, and Windows exposes it
as a device interface that any user process can open and write to.

## How it works

```
SVG / coordinates / text
        |
        v
  plotter/svg.py      parse SVG, flatten curves, apply transforms
        |
        v
  plotter/hpgl2.py    emit HP-GL/2 commands in plotter units (1/40 mm)
        |
        v
  plotter/render.py   pick pens, send bytes
        |
        v
  plotter/usbprint.py SetupAPI -> CreateFileW -> WriteFile (bulk OUT)
        |
        v
   USB adapter -> Centronics -> DesignJet 750C -> paper
```

No spooler, no driver, no elevation. The device is discovered through
`GUID_DEVINTERFACE_USBPRINT` (`{28d78fad-5a12-11d1-ae5b-0000f803a8c2}`), so the
USB serial number is never hard-coded.

## Usage

```powershell
python -m plotter.cli status                 # is the adapter present and openable?
python -m plotter.cli test                   # self-test page
python -m plotter.cli color                  # four pen squares, to verify pen order
python -m plotter.cli svg drawing.svg --page A3
python -m plotter.cli svg drawing.svg --dry-run out.hpgl   # inspect, do not plot
python -m plotter.cli image poster.jpg --width-mm 190       # HP RTL colour raster
python -m plotter.cli image poster.jpg --dry-run out.hpgl   # raster job, not sent
python -m plotter.cli text "Hola" --size 12
python -m plotter.cli feed
python -m plotter.cli raw file.hpgl
```

`--page` accepts `A4 A3 A2 A1 A0` or `WIDTHxHEIGHT` in millimetres.
`--speed` sets pen speed in cm/s (lower is easier to watch).
`--no-fit` keeps the SVG's own size instead of scaling it to the page.

### Printing photographs

The 750C is an inkjet, so it also speaks HP RTL raster. `image` sends a
JPEG/PNG as 24-bit RGB at 300 dpi (the plotter's colour resolution):

```powershell
python -m plotter.cli image poster.jpg                  # native pixels at 300 dpi
python -m plotter.cli image poster.jpg --width-mm 190   # resize to fit a page
python -m plotter.cli image poster.jpg --dpi 150        # bigger, softer output
```

The job is split into horizontal bands of `--band-rows` rows (800 by default)
because the 750C Plus has about 11 MB of memory; each band is a separate raster
sequence and the plotter stacks them. Decoding images needs Pillow; the vector
commands do not.

## MCP server (for AI agents)

`server.py` starts a stdio MCP server with these tools:

| tool | purpose |
| --- | --- |
| `plotter_status` | device present and openable |
| `plot_selftest` | built-in test page |
| `plot_color_test` | four labelled pen squares |
| `plot_svg` | plot an SVG file, optional page fit |
| `plot_image` | print a JPEG/PNG as HP RTL colour raster |
| `plot_polylines` | plot raw `[[x, y], ...]` millimetre geometry |
| `plot_text` | one line of text |
| `feed_page` | advance the media |

Register it in your MCP client config (e.g. `opencode.json` or Claude Desktop):

```json
"plotter": {
  "type": "local",
  "enabled": true,
  "command": [
    "python",
    "C:\\path\\to\\plotter-hp750c\\server.py"
  ]
}
```

## Installation & Tests

```bash
pip install -r requirements.txt

python tests/test_raster.py
python tests/test_mcp.py
```

## Limitations

- **Four pens.** The 750C has black, cyan, magenta and yellow cartridges. Any
  colour is mapped to the closest pen; there is no halftone or ink mixing yet.
  Blue maps to magenta, for example. Overprinting (cyan + magenta = blue) is a
  possible future improvement.
- **Vector only.** SVG paths and explicit geometry work. Photos, PDFs and PNGs
  need HP RTL raster support, which is not implemented.
- **No feedback channel.** The adapter has no usable reverse pipe, so the
  plotter cannot report status, ink levels or errors back. The front panel is
  the source of truth.
- **SVG subset.** `use`, filters, gradients, clip paths and embedded images are
  ignored.

## Front panel notes

- `Edge not found / Reload media`: the media sensor does not see the leading
  edge. Cut the edge square, align the right edge with the perforated line on
  the entry platen, insert until it buckles, then choose `Roll load`.
- `Monochrome` lamp on: one or more colour cartridges are missing or not
  detected. The plotter falls back to black.
- `Repair cartridges / Continue`: cartridge service routine. `Continue` skips
  it; the routine itself is slow and consumes ink.

## Layout

```
plotter/usbprint.py    SetupAPI discovery + raw write
plotter/hpgl2.py       HP-GL/2 command builder
plotter/svg.py         SVG parser and geometry flattener
plotter/colors.py      RGB -> pen mapping
plotter/render.py      drawing -> canvas -> device
plotter/pages.py       self test and colour test pages
plotter/cli.py         command line
plotter/mcp_server.py  MCP tools
server.py              MCP entry point
tests/test_mcp.py      stdio handshake smoke test
```
