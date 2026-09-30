"""Raster post-processing shared by screen capture and logo stamping.

The SolidWorks original did three things with GDI+ that are worth porting
properly rather than approximating:

* **flood the background white** and report the content bounding box, so a
  capture of a model on a dark background still prints on white paper;
* **fit the content into an A4 canvas at 300 dpi** with a small margin;
* **place a logo at a millimetre position** on an existing capture, cleaning
  the old logo's area first.

All three work on raw pixel buffers so they do not need Qt's GUI stack, which
keeps them usable from ``freecadcmd``.  Qt's ``QImage`` is used only for the
final PNG write, and only when available.
"""

from __future__ import annotations

import math
import os
import struct
from typing import Any, List, Optional, Sequence, Tuple

__all__ = [
    "Raster",
    "write_png",
    "read_png_size",
    "flood_background",
    "content_bbox",
    "fit_into_canvas",
    "mm_to_px",
    "clear_rect",
    "paste_rgba",
    "load_rgba",
    "save_rgba",
    "DPI",
]

DPI = 300
MM_PER_INCH = 25.4


# ---------------------------------------------------------------------------
# A minimal RGBA raster
# ---------------------------------------------------------------------------
class Raster:
    """An 8-bit RGBA image stored as ``bytearray``.

    Deliberately dependency-free: ``PIL`` and ``numpy`` are both optional in
    FreeCAD and neither is guaranteed to be importable inside the macro
    sandbox.
    """

    __slots__ = ("width", "height", "pixels")

    def __init__(self, width: int, height: int, pixels: Optional[bytearray] = None, fill: int = 255):
        self.width = int(width)
        self.height = int(height)
        if pixels is None:
            self.pixels = bytearray(bytes([fill, fill, fill, 255]) * (self.width * self.height))
        else:
            expected = self.width * self.height * 4
            if len(pixels) != expected:
                raise ValueError("pixel buffer is {0} bytes, expected {1}".format(len(pixels), expected))
            self.pixels = pixels

    # -- pixel access -----------------------------------------------------
    def index(self, x: int, y: int) -> int:
        return (y * self.width + x) * 4

    def get(self, x: int, y: int) -> Tuple[int, int, int, int]:
        i = self.index(x, y)
        data = self.pixels
        return (data[i], data[i + 1], data[i + 2], data[i + 3])

    def set(self, x: int, y: int, rgba: Sequence[int]) -> None:
        if 0 <= x < self.width and 0 <= y < self.height:
            i = self.index(x, y)
            data = self.pixels
            data[i] = rgba[0] & 0xFF
            data[i + 1] = rgba[1] & 0xFF
            data[i + 2] = rgba[2] & 0xFF
            data[i + 3] = rgba[3] & 0xFF if len(rgba) > 3 else 255

    def copy(self) -> "Raster":
        return Raster(self.width, self.height, bytearray(self.pixels))

    def filled(self, rgba: Sequence[int]) -> "Raster":
        return Raster(self.width, self.height, fill=255).paint(rgba)

    def paint(self, rgba: Sequence[int]) -> "Raster":
        r, g, b = rgba[0] & 0xFF, rgba[1] & 0xFF, rgba[2] & 0xFF
        a = rgba[3] & 0xFF if len(rgba) > 3 else 255
        self.pixels[:] = bytes((r, g, b, a)) * (self.width * self.height)
        return self

    @property
    def nbytes(self) -> int:
        return len(self.pixels)


# ---------------------------------------------------------------------------
# PNG encode / decode (pure stdlib, via zlib)
# ---------------------------------------------------------------------------
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _chunk(tag: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + tag
        + data
        + struct.pack(">I", zlib_crc32(tag + data) & 0xFFFFFFFF)
    )


def zlib_crc32(data: bytes) -> int:
    import zlib

    return zlib.crc32(data)


def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def write_png(path: str, raster: Raster, dpi: int = DPI) -> bool:
    """Write ``raster`` as an 8-bit RGBA PNG with a physical resolution."""
    import zlib

    width, height = raster.width, raster.height
    raw = bytearray()
    stride = width * 4
    for y in range(height):
        raw.append(0)  # filter type 0 (None)
        start = y * stride
        raw += raster.pixels[start : start + stride]

    ppm = int(round(dpi / MM_PER_INCH))
    body = (
        _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + _chunk(b"pHYs", struct.pack(">IIB", ppm, ppm, 1))
        + _chunk(b"IDAT", zlib.compress(bytes(raw), 6))
        + _chunk(b"IEND", b"")
    )
    tmp = path + ".part"
    with open(tmp, "wb") as handle:
        handle.write(_PNG_MAGIC)
        handle.write(body)
    os.replace(tmp, path)
    return True


def read_png_size(path: str) -> Tuple[int, int]:
    """``(width, height)`` of a PNG, read from the header only."""
    with open(path, "rb") as handle:
        header = handle.read(24)
    if not header.startswith(_PNG_MAGIC) or len(header) < 24:
        raise ValueError("not a PNG: " + path)
    width, height = struct.unpack(">II", header[16:24])
    return (int(width), int(height))


def load_rgba(path: str) -> Raster:
    """Load a PNG into a :class:`Raster`.

    Delegates to Qt when available (it handles interlacing and every colour
    type), and falls back to a minimal decoder for the plain 8-bit
    non-interlaced case that FreeCAD's own exports produce.
    """
    raster = _load_with_qt(path)
    if raster is not None:
        return raster
    return _load_pure_python(path)


def _load_with_qt(path: str) -> Optional[Raster]:
    from mrfreecad import compat

    if not compat.HAS_QT:
        return None
    try:
        image = compat.qt_gui("PNG load").QImage(path)
        if image.isNull():
            return None
        converted = image.convertToFormat(compat.qt_gui("PNG load").QImage.Format_RGBA8888)
        width, height = converted.width(), converted.height()
        buffer = compat.qimage_to_bytes(converted)
        expected = width * height * 4
        if len(buffer) < expected:
            return None
        return Raster(width, height, bytearray(buffer[:expected]))
    except Exception as exc:
        compat.console_log("Qt PNG load failed, using fallback: " + str(exc))
        return None


def _load_pure_python(path: str) -> Raster:
    """Decode a non-interlaced 8-bit PNG.  Raises on anything it cannot do."""
    import zlib

    with open(path, "rb") as handle:
        data = handle.read()
    if not data.startswith(_PNG_MAGIC):
        raise ValueError("not a PNG: " + path)

    pos = len(_PNG_MAGIC)
    width = height = 0
    depth = colour = interlace = 0
    idat = bytearray()
    palette = b""
    while pos + 8 <= len(data):
        length = struct.unpack(">I", data[pos : pos + 4])[0]
        tag = data[pos + 4 : pos + 8]
        payload = data[pos + 8 : pos + 8 + length]
        pos += 12 + length
        if tag == b"IHDR":
            width, height, depth, colour, _comp, _filt, interlace = struct.unpack(">IIBBBBB", payload)
        elif tag == b"PLTE":
            palette = payload
        elif tag == b"IDAT":
            idat += payload
        elif tag == b"IEND":
            break

    if depth != 8 or interlace != 0 or colour not in (0, 2, 3, 4, 6):
        raise ValueError("unsupported PNG variant (depth={0} colour={1})".format(depth, colour))

    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[colour]
    raw = zlib.decompress(bytes(idat))
    stride = width * channels
    out = bytearray(width * height * 4)
    previous = bytearray(stride)

    pos = 0
    for y in range(height):
        filter_type = raw[pos]
        pos += 1
        line = bytearray(raw[pos : pos + stride])
        pos += stride
        _unfilter(filter_type, line, previous, channels)
        _expand_row(line, width, channels, colour, palette, out, y)
        previous = line
    return Raster(width, height, out)


def _unfilter(filter_type: int, line: bytearray, previous: bytearray, channels: int) -> None:
    if filter_type == 0:
        return
    for i in range(len(line)):
        left = line[i - channels] if i >= channels else 0
        up = previous[i]
        upleft = previous[i - channels] if i >= channels else 0
        if filter_type == 1:
            line[i] = (line[i] + left) & 0xFF
        elif filter_type == 2:
            line[i] = (line[i] + up) & 0xFF
        elif filter_type == 3:
            line[i] = (line[i] + ((left + up) >> 1)) & 0xFF
        elif filter_type == 4:
            line[i] = (line[i] + _paeth(left, up, upleft)) & 0xFF
        else:
            raise ValueError("unknown PNG filter type {0}".format(filter_type))


def _expand_row(
    line: bytearray,
    width: int,
    channels: int,
    colour: int,
    palette: bytes,
    out: bytearray,
    y: int,
) -> None:
    base = y * width * 4
    for x in range(width):
        src = x * channels
        dst = base + x * 4
        if colour == 0:  # greyscale
            value = line[src]
            out[dst] = out[dst + 1] = out[dst + 2] = value
            out[dst + 3] = 255
        elif colour == 2:  # RGB
            out[dst] = line[src]
            out[dst + 1] = line[src + 1]
            out[dst + 2] = line[src + 2]
            out[dst + 3] = 255
        elif colour == 3:  # palette
            index = line[src] * 3
            if index + 2 < len(palette):
                out[dst] = palette[index]
                out[dst + 1] = palette[index + 1]
                out[dst + 2] = palette[index + 2]
            out[dst + 3] = 255
        elif colour == 4:  # grey + alpha
            out[dst] = out[dst + 1] = out[dst + 2] = line[src]
            out[dst + 3] = line[src + 1]
        else:  # colour == 6, RGBA
            out[dst : dst + 4] = line[src : src + 4]


def save_rgba(path: str, raster: Raster, dpi: int = DPI) -> bool:
    """Write a :class:`Raster` to ``path`` as PNG."""
    return write_png(path, raster, dpi)


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------
def mm_to_px(value_mm: float, px_per_mm: float) -> int:
    return int(round(float(value_mm) * float(px_per_mm)))


def clear_rect(raster: Raster, x: int, y: int, width: int, height: int, rgba: Sequence[int] = (255, 255, 255, 255)) -> None:
    """Fill a rectangle, clipped to the raster."""
    x0 = max(0, min(x, raster.width))
    y0 = max(0, min(y, raster.height))
    x1 = max(0, min(x + width, raster.width))
    y1 = max(0, min(y + height, raster.height))
    if x1 <= x0 or y1 <= y0:
        return
    r, g, b = rgba[0] & 0xFF, rgba[1] & 0xFF, rgba[2] & 0xFF
    a = rgba[3] & 0xFF if len(rgba) > 3 else 255
    row = bytes((r, g, b, a)) * (x1 - x0)
    for yy in range(y0, y1):
        start = (yy * raster.width + x0) * 4
        raster.pixels[start : start + len(row)] = row


def paste_rgba(dst: Raster, src: Raster, at_x: int, at_y: int) -> None:
    """Alpha-blend ``src`` onto ``dst`` at ``(at_x, at_y)``, clipped to both."""
    for y in range(src.height):
        ty = at_y + y
        if ty < 0 or ty >= dst.height:
            continue
        for x in range(src.width):
            tx = at_x + x
            if tx < 0 or tx >= dst.width:
                continue
            sr, sg, sb, sa = src.get(x, y)
            if sa == 0:
                continue
            if sa == 255:
                dst.set(tx, ty, (sr, sg, sb, 255))
                continue
            dr, dg, db, da = dst.get(tx, ty)
            alpha = sa / 255.0
            inv = 1.0 - alpha
            out_a = sa + int(da * inv)
            if out_a == 0:
                dst.set(tx, ty, (0, 0, 0, 0))
                continue
            dst.set(
                tx,
                ty,
                (
                    int((sr * alpha + dr * da * inv) / out_a),
                    int((sg * alpha + dg * da * inv) / out_a),
                    int((sb * alpha + db * da * inv) / out_a),
                    out_a,
                ),
            )


def content_bbox(raster: Raster, tolerance: int = 20) -> Optional[Tuple[int, int, int, int]]:
    """Bounding box of everything that is not background, or ``None``.

    Edges are used as the seed, then a 4-connected flood fill, exactly as the
    original's ``MakeBackgroundWhite``.  Seeding from the border rather than
    from one corner is what keeps a white object in the middle of the frame
    from being erased.
    """
    width, height, data = raster.width, raster.height, raster.pixels
    if width == 0 or height == 0:
        return None
    visited = bytearray(width * height)
    queue: List[int] = []

    def enqueue(pixel: int) -> None:
        if visited[pixel]:
            return
        offset = pixel * 4
        if abs(data[offset] - 255) <= tolerance and abs(data[offset + 1] - 255) <= tolerance and abs(data[offset + 2] - 255) <= tolerance:
            visited[pixel] = 1
            queue.append(pixel)

    for x in range(width):
        enqueue(x)
        enqueue((height - 1) * width + x)
    for y in range(1, height - 1):
        enqueue(y * width)
        enqueue(y * width + width - 1)

    head = 0
    while head < len(queue):
        pixel = queue[head]
        head += 1
        x = pixel % width
        y = pixel // width
        offset = pixel * 4
        if x > 0 and not visited[pixel - 1]:
            enqueue(pixel - 1)
        if x < width - 1 and not visited[pixel + 1]:
            enqueue(pixel + 1)
        if y > 0 and not visited[pixel - width]:
            enqueue(pixel - width)
        if y < height - 1 and not visited[pixel + width]:
            enqueue(pixel + width)
        data[offset] = 255
        data[offset + 1] = 255
        data[offset + 2] = 255
        data[offset + 3] = 255

    min_x, min_y = width, height
    max_x, max_y = -1, -1
    for y in range(height):
        base = y * width
        for x in range(width):
            if not visited[base + x]:
                if x < min_x:
                    min_x = x
                if x > max_x:
                    max_x = x
                if y < min_y:
                    min_y = y
                if y > max_y:
                    max_y = y
    if max_x < 0:
        return None
    return (min_x, min_y, max_x - min_x + 1, max_y - min_y + 1)


def flood_background(raster: Raster, tolerance: int = 20) -> Optional[Tuple[int, int, int, int]]:
    """Flood the background white and return the content bounding box."""
    return content_bbox(raster, tolerance)


def fit_into_canvas(
    raster: Raster,
    canvas_w: int,
    canvas_h: int,
    box: Optional[Tuple[int, int, int, int]] = None,
    margin: float = 0.04,
) -> Raster:
    """Centre ``raster``'s content on a white ``canvas_w`` x ``canvas_h`` canvas.

    ``box`` limits the source region; ``margin`` is the free space around the
    content as a fraction of the canvas, mirroring the original's 0.92 fill.
    """
    if box is None:
        box = (0, 0, raster.width, raster.height)
    x0, y0, w, h = box
    if w <= 0 or h <= 0:
        x0, y0 = 0, 0
        w, h = raster.width, raster.height

    canvas = Raster(canvas_w, canvas_h, fill=255)
    source_aspect = w / float(h)
    canvas_aspect = canvas_w / float(canvas_h)
    if source_aspect > canvas_aspect:
        target_w = canvas_w * (1.0 - margin)
        target_h = target_w / source_aspect
    else:
        target_h = canvas_h * (1.0 - margin)
        target_w = target_h * source_aspect
    dest_x = int(round((canvas_w - target_w) / 2.0))
    dest_y = int(round((canvas_h - target_h) / 2.0))
    _resample_into(canvas, raster, (x0, y0, w, h), (dest_x, dest_y, int(round(target_w)), int(round(target_h))))
    return canvas


def _resample_into(dst: Raster, src: Raster, box: Tuple[int, int, int, int], dest: Tuple[int, int, int, int]) -> None:
    """Nearest-neighbour resample of a source box into a destination rectangle.

    Nearest neighbour rather than bicubic: the content is line art on white,
    where smooth interpolation softens exactly the edges a shop needs to read.
    """
    sx, sy, sw, sh = box
    dx, dy, dw, dh = dest
    if sw <= 0 or sh <= 0 or dw <= 0 or dh <= 0:
        return
    for y in range(dh):
        ty = dy + y
        if ty < 0 or ty >= dst.height:
            continue
        src_y = sy + int((y + 0.5) * sh / dh)
        if src_y < 0 or src_y >= src.height:
            continue
        for x in range(dw):
            tx = dx + x
            if tx < 0 or tx >= dst.width:
                continue
            src_x = sx + int((x + 0.5) * sw / dw)
            if src_x < 0 or src_x >= src.width:
                continue
            dr, dg, db, da = src.get(src_x, src_y)
            if da == 0:
                continue
            if da == 255:
                dst.set(tx, ty, (dr, dg, db, 255))
                continue
            br, bg, bb, _ba = dst.get(tx, ty)
            alpha = da / 255.0
            dst.set(
                tx,
                ty,
                (
                    int(dr * alpha + br * (1 - alpha)),
                    int(dg * alpha + bg * (1 - alpha)),
                    int(db * alpha + bb * (1 - alpha)),
                    255,
                ),
            )


def canvas_px(width_mm: float, height_mm: float, dpi: int = DPI) -> Tuple[int, int]:
    """Paper size in millimetres to a pixel canvas at ``dpi``."""
    return (
        int(round(float(width_mm) / MM_PER_INCH * float(dpi))),
        int(round(float(height_mm) / MM_PER_INCH * float(dpi))),
    )
