"""Company logo stamping onto existing PNG captures.

The original opened the selected sheet format, extracted the logo bitmap and
its millimetre rectangle from the template, then for every PNG in a folder:
whited out both firms' logo rectangles and drew the selected firm's logo at its
own position.

That whole flow ports over, with one unavoidable substitution: **FreeCAD
cannot read a ``.slddrt``**, because there is no equivalent of the file.  The
TechDraw template SVG *is* the direct equivalent, so the logo image and its
millimetre rectangle are configured per firm in the settings dialog instead of
being scraped out of a binary template.

What is preserved:

* both firms' rectangles are cleaned before the new logo is drawn, so a
  Karadeniz logo never survives onto an Ayazsa sheet;
* positions are in millimetres on the paper, origin bottom-left, converted
  with the same scale factor the original used (pixels per millimetre from the
  paper width);
* the cleanup padding is asymmetric, 2 mm horizontally and 0.3 mm vertically,
  exactly as in the original, because that is what clears an old logo without
  eating into the drawing frame;
* the y axis is flipped between sheet space (y up) and pixel space (y down).
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

from mrfreecad import compat
from mrfreecad.raster import (
    Raster,
    clear_rect,
    load_rgba,
    mm_to_px,
    paste_rgba,
    write_png,
)
from mrfreecad.settings import FIRMS, LogoSlot

__all__ = ["stamp_folder", "stamp_one", "slot_to_rect", "MM_PER_INCH", "DEFAULT_PAPER_MM"]

MM_PER_INCH = 25.4
DEFAULT_PAPER_MM = (297.0, 210.0)


def slot_to_rect(
    slot: LogoSlot,
    scale: float,
    canvas_w: int,
    canvas_h: int,
    paper_mm_h: float,
    pad_mm_x: float = 0.0,
    pad_mm_y: float = 0.0,
) -> Optional[Tuple[int, int, int, int]]:
    """Millimetre logo rectangle to a pixel rectangle.

    Sheet space has its origin bottom-left with y increasing upwards; PNG space
    has its origin top-left with y increasing downwards.  The conversion is the
    same one the original used::

        px = mm_x * scale
        py = (paper_mm_h - (mm_y + mm_h)) * scale

    ``pad_mm_x`` / ``pad_mm_y`` grow the rectangle symmetrically, which is how
    the cleanup border was applied.
    """
    if slot.w < 0.01 or slot.h < 0.01:
        return None
    px_w = mm_to_px(slot.w, scale)
    px_h = mm_to_px(slot.h, scale)
    if px_w < 4 or px_h < 4:
        return None
    px_w = min(px_w, canvas_w)
    px_h = min(px_h, canvas_h)
    px = mm_to_px(slot.x, scale)
    py = mm_to_px((paper_mm_h - (slot.y + slot.h)) * 1.0, scale)

    if pad_mm_x > 0:
        pad = mm_to_px(pad_mm_x, scale)
        if pad > 0:
            px -= pad // 2
            px_w += pad
    if pad_mm_y > 0:
        pad = mm_to_px(pad_mm_y, scale)
        if pad > 0:
            py -= pad // 2
            px_h += pad

    if px < 0:
        px = 0
    if py < 0:
        py = 0
    if px + px_w > canvas_w:
        px_w = canvas_w - px
    if py + px_h > canvas_h:
        px_h = canvas_h - py
    if px_w < 1 or px_h < 1:
        return None
    return (px, py, px_w, px_h)


def stamp_one(
    png_path: str,
    firm: str,
    other_firms: Optional[List[str]] = None,
    dpi: Optional[int] = None,
) -> Tuple[bool, str]:
    """Replace the logo on a single PNG.

    Cleans every *other* firm's rectangle, cleans the selected firm's own
    rectangle, then draws the selected logo at exactly its configured size -
    no padding, so the logo lands pixel-identical to how the template draws it.
    """
    from mrfreecad.settings import get_settings

    settings = get_settings()
    slot = settings.logo(firm)
    if not slot.image or not os.path.isfile(slot.image):
        return (False, "logo dosyası yok: " + (slot.image or "(ayarlanmadı)"))
    if not os.path.isfile(png_path):
        return (False, "PNG bulunamadı: " + png_path)

    other_firms = [name for name in (other_firms if other_firms is not None else FIRMS) if name != firm]

    try:
        canvas = load_rgba(png_path)
    except Exception as exc:
        return (False, "okunamadı: " + str(exc))
    if canvas is None or canvas.width == 0:
        return (False, "okunamadı")

    width_mm = settings.get_float("Capture/PaperWidthMm", DEFAULT_PAPER_MM[0])
    height_mm = settings.get_float("Capture/PaperHeightMm", DEFAULT_PAPER_MM[1])
    scale = canvas.width / float(width_mm) if width_mm > 0 else 1.0

    cleaned: List[str] = []
    for other in other_firms:
        other_slot = settings.logo(other)
        rect = slot_to_rect(other_slot, scale, canvas.width, canvas.height, height_mm, other_slot.clear_pad_x, other_slot.clear_pad_y)
        if rect is not None:
            clear_rect(canvas, *rect)
            cleaned.append(other)

    clear_rect_slot = slot_to_rect(slot, scale, canvas.width, canvas.height, height_mm, slot.clear_pad_x, slot.clear_pad_y)
    if clear_rect_slot is None:
        return (False, "logo konumu geçersiz (mm değerlerini kontrol edin)")
    clear_rect(canvas, *clear_rect_slot)

    draw_rect = slot_to_rect(slot, scale, canvas.width, canvas.height, height_mm, 0.0, 0.0)
    if draw_rect is None:
        return (False, "logo çizim alanı geçersiz")

    clipped = not slot.fits(width_mm, height_mm)
    if clipped:
        # A slot placed for a larger sheet than this capture is the usual cause.
        # It still gets stamped, but the user is told, because a half-printed
        # logo is easy to miss in a folder of hundreds of captures.
        compat.console_log(
            "logo: {0} slotu {1}x{2} mm kağıda sığmıyor, kırpıldı "
            "(x+genişlik={3}, kağıt={1})".format(
                firm,
                width_mm,
                height_mm,
                slot.x + slot.w,
            )
        )

    try:
        logo = load_rgba(slot.image)
    except Exception as exc:
        return (False, "logo okunamadı: " + str(exc))
    if logo is None or logo.width == 0:
        return (False, "logo okunamadı")

    scaled = _scale_to(logo, draw_rect[2], draw_rect[3])
    paste_rgba(canvas, scaled, draw_rect[0], draw_rect[1])

    write_png(png_path, canvas, dpi or settings.get_int("Capture/Dpi", 300))
    notes = []
    if cleaned:
        notes.append("temizlenen: " + ", ".join(cleaned))
    if clipped:
        notes.append("UYARI: konum kağıttan taşıyor, kırpıldı")
    suffix = (" (" + "; ".join(notes) + ")") if notes else ""
    return (True, os.path.basename(png_path) + suffix)


def _scale_to(raster: Raster, width: int, height: int) -> Raster:
    """Nearest-neighbour scale of a whole raster."""
    if raster.width == width and raster.height == height:
        return raster
    out = Raster(width, height)
    for y in range(height):
        src_y = int((y + 0.5) * raster.height / height)
        if src_y >= raster.height:
            src_y = raster.height - 1
        for x in range(width):
            src_x = int((x + 0.5) * raster.width / width)
            if src_x >= raster.width:
                src_x = raster.width - 1
            out.set(x, y, raster.get(src_x, src_y))
    return out


def stamp_folder(
    firm: str,
    folder: str = "",
    recursive: bool = True,
) -> Tuple[bool, str, str]:
    """Stamp ``firm``'s logo onto every PNG below ``folder``.

    Returns ``(ok, summary, message)``.  Failures are listed individually
    rather than aborting the batch, because a folder of production captures is
    rarely uniform - some are locked, some are a different format.
    """
    from mrfreecad.settings import get_settings

    settings = get_settings()
    slot = settings.logo(firm)
    if not slot.image or not os.path.isfile(slot.image):
        return (
            False,
            "",
            "{0} logosu için görsel ayarlanmamış.\n\nMrFreeTool > Ayarlar > Logo bölümünden "
            "PNG dosyasını seçin.".format(firm),
        )

    if not folder:
        doc = compat.active_document()
        folder = os.path.dirname(str(doc.FileName or os.getcwd())) if doc is not None else os.getcwd()
    if not os.path.isdir(folder):
        return (False, "", "Klasör bulunamadı:\n" + str(folder))

    if recursive:
        pngs = []
        for dirpath, dirnames, filenames in os.walk(folder):
            dirnames.sort()
            for name in sorted(filenames):
                if name.lower().endswith(".png"):
                    pngs.append(os.path.join(dirpath, name))
    else:
        pngs = [os.path.join(folder, name) for name in sorted(os.listdir(folder)) if name.lower().endswith(".png")]

    if not pngs:
        return (False, "", "Seçilen klasörde PNG dosyası bulunamadı:\n" + str(folder))

    done = 0
    failures: List[str] = []
    for png in pngs:
        ok, note = stamp_one(png, firm)
        if ok:
            done += 1
        else:
            failures.append(os.path.basename(png) + " (" + note + ")")

    lines = [
        "=" * 59,
        "  {0} LOGO İŞLEMİ TAMAMLANDI".format(firm.upper()),
        "=" * 59,
        "",
        "Klasör       : " + str(folder),
        "Bulunan PNG  : " + str(len(pngs)),
        "Güncellenen  : " + str(done),
        "Hata         : " + str(len(failures)),
        "",
        "Logo         : " + slot.image,
        "Konum (mm)   : x={0}, y={1}, w={2}, h={3}".format(
            _fmt(slot.x), _fmt(slot.y), _fmt(slot.w), _fmt(slot.h)
        ),
        "Temizleme    : {0} mm yatay / {1} mm dikey".format(_fmt(slot.clear_pad_x), _fmt(slot.clear_pad_y)),
    ]
    paper_w = settings.get_float("Capture/PaperWidthMm", DEFAULT_PAPER_MM[0])
    paper_h = settings.get_float("Capture/PaperHeightMm", DEFAULT_PAPER_MM[1])
    if slot.fits(paper_w, paper_h):
        lines.append("Sığdırma     : konum {0}x{1} mm kağıda sığıyor".format(_fmt(paper_w), _fmt(paper_h)))
    else:
        lines.append(
            "Sığdırma     : UYARI - konum {0}x{1} mm kağıda SIĞMIYOR, logo kırpılacak.".format(
                _fmt(paper_w), _fmt(paper_h)
            )
        )
    if failures:
        lines.append("")
        lines.append("Başarısız dosyalar:")
        lines.extend("  • " + item for item in failures)
    return (done > 0, "\n".join(lines), "{0} PNG güncellendi.".format(done))


def _fmt(value: float) -> str:
    from mrfreecad.naming import to_decimal

    return to_decimal(value, 2)
