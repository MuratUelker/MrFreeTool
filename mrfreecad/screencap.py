"""Screen capture and assembly-sheet PDF generation.

Ports the ``Screen Cap`` and ``make pdf`` buttons.

``Screen Cap`` wrote ``screencap01.png``, ``screencap02.png`` ... in the part's
folder, each an A4 page at 300 dpi with the model centred and the background
forced to white.  ``make pdf`` then collected those files in numeric order and
stitched them into ``montaj talimatı.pdf``.

The PDF is built with ``QPdfWriter`` from Qt, which ships with FreeCAD, so
there is no ReportLab or Pillow dependency to install.
"""

from __future__ import annotations

import os
from typing import Any, List, Optional, Tuple

from mrfreecad import compat
from mrfreecad.naming import collect_screen_caps, next_screen_cap_path
from mrfreecad.raster import Raster, canvas_px, content_bbox, fit_into_canvas, load_rgba, write_png

__all__ = ["screen_cap", "make_pdf", "MAX_CAPTURE_INDEX", "PDF_QUALITY"]

#: The original scanned for a free index in 1..999.
MAX_CAPTURE_INDEX = 999

#: JPEG quality for the PDF's embedded images, matching the original.
PDF_QUALITY = 90


def screen_cap(
    path: str = "",
    width_mm: Optional[float] = None,
    height_mm: Optional[float] = None,
    dpi: int = 0,
    trim: Optional[bool] = None,
    fit_fraction: Optional[float] = None,
    tolerance: Optional[int] = None,
    folder: str = "",
    prefix: Optional[str] = None,
) -> Tuple[bool, str, str]:
    """Capture the active 3D view onto an A4 page.

    The order of operations matches the original: capture at a generous size,
    flood the background white to find the content box, then recompose centred
    on the exact paper canvas.  Returns ``(ok, path, message)``.
    """
    from mrfreecad.settings import get_settings

    compat.require_freecad("Screen capture")
    if not compat.HAS_GUI:
        return (False, "", "Screen capture için FreeCAD GUI gerekir.")

    settings = get_settings()
    if width_mm is None:
        width_mm = settings.get_float("Capture/PaperWidthMm", 297.0)
    if height_mm is None:
        height_mm = settings.get_float("Capture/PaperHeightMm", 210.0)
    if not dpi:
        dpi = settings.get_int("Capture/Dpi", 300)
    if trim is None:
        trim = settings.get_bool("Capture/TrimToContent", True)
    if fit_fraction is None:
        fit_fraction = settings.get_float("Capture/FitFraction", 0.92)
    if tolerance is None:
        tolerance = settings.get_int("Capture/BackgroundTolerance", 20)
    if prefix is None:
        prefix = settings.get_str("Capture/Prefix", "screencap")

    doc = compat.gui().ActiveDocument
    if doc is None:
        return (False, "", "Açık bir doküman yok.")
    # saveImage lives on the view, not on the document.
    view = getattr(doc, "ActiveView", None)
    if view is None or not hasattr(view, "saveImage"):
        return (False, "", "3B görünüm (viewport) alınamadı.")

    canvas_w, canvas_h = canvas_px(width_mm, height_mm, dpi)
    if canvas_w <= 0 or canvas_h <= 0:
        return (False, "", "Geçersiz kağıt boyutu.")

    if not folder:
        folder = os.path.dirname(str(doc.FileName or os.getcwd()))
    if not path:
        path = next_screen_cap_path(folder, prefix)

    # Capture at the paper resolution, with a white background so the flood
    # fill has something definite to work with.
    try:
        view.setCameraType("Orthographic")
    except Exception:
        pass

    handle, raw_path = _temp_path(".png")
    os.close(handle)
    try:
        try:
            ok = view.saveImage(raw_path, canvas_w, canvas_h, "White")
        except Exception:
            ok = False
        if not ok or not os.path.isfile(raw_path):
            return (False, path, "Görünüm kaydedilemedi.")

        raster = load_rgba(raw_path)
    except Exception as exc:
        return (False, path, "Görünüm okunamadı: " + str(exc))
    finally:
        _remove(raw_path)

    if raster is None or raster.width == 0:
        return (False, path, "Görünüm okunamadı.")

    box: Optional[Tuple[int, int, int, int]] = None
    if trim:
        box = content_bbox(raster, int(tolerance))

    if box is not None:
        # Small breathing room, as the original's 8 px inflation.
        x0, y0, w, h = box
        x0 = max(0, x0 - 8)
        y0 = max(0, y0 - 8)
        x1 = min(raster.width, x0 + w + 16)
        y1 = min(raster.height, y0 + h + 16)
        box = (x0, y0, max(1, x1 - x0), max(1, y1 - y0))
    else:
        box = (0, 0, raster.width, raster.height)

    margin = max(0.0, min(0.5, 1.0 - float(fit_fraction)))
    page = fit_into_canvas(raster, canvas_w, canvas_h, box, margin=margin)
    write_png(path, page, dpi)

    message = "Screen cap kaydedildi:\n{0}\n\nKağıt: {1} x {2} mm @ {3} dpi".format(
        path, round(width_mm, 1), round(height_mm, 1), dpi
    )
    if not trim:
        message += "\n(içerik kırpılmadı)"
    return (True, path, message)


def make_pdf(
    folder: str = "",
    path: str = "",
    prefix: Optional[str] = None,
) -> Tuple[bool, str, str]:
    """Combine ``screencapNN.png`` files into a single PDF.

    Pages keep each capture's own pixel aspect, letterboxed onto the paper
    orientation, so a portrait capture stays portrait.  Returns
    ``(ok, path, message)``.
    """
    from mrfreecad.settings import get_settings

    settings = get_settings()
    if prefix is None:
        prefix = settings.get_str("Capture/Prefix", "screencap")
    if not folder:
        doc = compat.active_document()
        if doc is None:
            return (False, "", "Açık bir doküman yok.")
        folder = os.path.dirname(str(doc.FileName or os.getcwd()))

    if not os.path.isdir(folder):
        return (False, "", "Klasör bulunamadı:\n" + str(folder))

    captures = collect_screen_caps(folder, prefix)
    if not captures:
        return (
            False,
            "",
            "Screen Cap ile kaydedilmiş PNG bulunamadı:\n{0}01.png, {0}02.png, ...".format(prefix),
        )

    if not path:
        path = os.path.join(folder, settings.get_str("Pdf/FileName", "montaj talimatı.pdf"))

    rasters: List[Raster] = []
    for image in captures:
        try:
            rasters.append(load_rgba(image))
        except Exception as exc:
            compat.console_log("skipping unreadable capture {0}: {1}".format(image, exc))
    if not rasters:
        return (False, path, "Capture dosyaları okunamadı.")

    ok, message = _write_pdf(rasters, path)
    if not ok:
        return (False, path, message)
    return (True, path, "PDF oluşturuldu:\n{0}\n\nSayfa sayısı: {1}".format(path, len(rasters)))


def _write_pdf(rasters: List[Raster], path: str) -> Tuple[bool, str]:
    """Write ``rasters`` as a multi-page PDF using Qt."""
    if not compat.HAS_QT:
        return (False, "PDF yazmak için Qt gerekli (FreeCAD GUI ile çalıştırın).")

    first = rasters[0]
    portrait = first.height > first.width
    try:
        writer = compat.QtGui.QPdfWriter(path)
    except Exception as exc:
        return (False, "QPdfWriter oluşturulamadı: " + str(exc))
    writer.setResolution(1200)
    if portrait:
        writer.setPageSize(compat.QtGui.QPageSize(compat.QtGui.QPageSize.A4))
        writer.setPageOrientation(compat.QtGui.QPageLayout.Portrait)
    else:
        writer.setPageSize(compat.QtGui.QPageSize(compat.QtGui.QPageSize.A4))
        writer.setPageOrientation(compat.QtGui.QPageLayout.Landscape)

    try:
        painter = compat.QtGui.QPainter(writer)
    except Exception as exc:
        return (False, "QPainter başlatılamadı: " + str(exc))

    try:
        for raster in rasters:
            if not writer.newPage():
                return (False, "PDF sayfası açılamadı.")
            rect = writer.pageLayout().paintRectPixels(writer.resolution())
            image = _qimage_from_raster(raster)
            if image is None:
                continue
            # Letterbox: keep the aspect ratio, centre on the page.
            scale = min(rect.width() / float(raster.width), rect.height() / float(raster.height))
            target_w = max(1, int(raster.width * scale))
            target_h = max(1, int(raster.height * scale))
            x = rect.x() + (rect.width() - target_w) // 2
            y = rect.y() + (rect.height() - target_h) // 2
            painter.drawImage(x, y, image)
    except Exception as exc:
        return (False, "PDF yazılamadı: " + str(exc))
    finally:
        painter.end()

    if not os.path.isfile(path):
        return (False, "PDF dosyası oluşmadı.")
    return (True, "")


def _qimage_from_raster(raster: Raster):
    """Wrap a :class:`Raster` as a ``QImage`` sharing the same buffer."""
    if not compat.HAS_QT:
        return None
    try:
        return compat.bytes_to_qimage(bytes(raster.pixels), raster.width, raster.height)
    except Exception as exc:
        compat.console_log("Raster -> QImage failed: " + str(exc))
        return None


# ---------------------------------------------------------------------------
# Small filesystem helpers
# ---------------------------------------------------------------------------
def _temp_path(suffix: str) -> Tuple[int, str]:
    import tempfile

    handle, path = tempfile.mkstemp(suffix=suffix, prefix="mrfree_cap_")
    return (handle, path)


def _remove(path: str) -> None:
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except OSError:
        pass
