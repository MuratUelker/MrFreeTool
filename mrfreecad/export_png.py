"""PNG export: TechDraw pages and 3D views.

Two distinct jobs, both present in the original:

* **Export Png** wrote the current drawing sheet to PNG at 300 dpi, sized to
  the paper, with every view hidden so only the sheet's own graphics remained.
  The FreeCAD equivalent renders the page's SVG.
* **Screen Cap** captured the 3D viewport.  That lives in
  :mod:`mrfreecad.screencap` because it needs background trimming.

Rendering strategy for a page, in order of preference:

1. ask TechDraw for an SVG and rasterise it with Qt's SVG renderer - exact,
   resolution independent, and works for a page that is not on screen;
2. grab the page's MDI widget - captures exactly what the user sees, including
   anything the SVG route drops.
"""

from __future__ import annotations

import os
import tempfile
from typing import Any, Optional, Tuple

from mrfreecad import compat
from mrfreecad.raster import Raster, canvas_px, fit_into_canvas, load_rgba, write_png

__all__ = ["export_page_png", "export_view_png", "render_page_svg", "DEFAULT_DPI"]

DEFAULT_DPI = 300


def _page_svg(page: Any, path: str) -> bool:
    """Write ``page`` to ``path`` as SVG.

    ``TechDrawGui.exportPageAsSvg`` needs the GUI, so a headless run falls back
    to writing the page's own SVG template - not the same thing, but better
    than failing without explanation, and the caller reports which path was
    taken.
    """
    if compat.HAS_GUI:
        try:
            import TechDrawGui  # type: ignore

            TechDrawGui.exportPageAsSvg(page, path)
            if os.path.isfile(path) and os.path.getsize(path) > 0:
                return True
        except Exception as exc:
            compat.console_log("exportPageAsSvg failed: " + str(exc))
    # Headless: the template is the only vector content we can reach.
    try:
        template_path = ""
        for view in getattr(page, "Views", []) or []:
            if getattr(view, "TypeId", "") == "TechDraw::DrawSVGTemplate":
                template_path = str(view.Template)
                break
        if template_path and os.path.isfile(template_path):
            with open(template_path, "r", encoding="utf-8", errors="replace") as src:
                content = src.read()
            with open(path, "w", encoding="utf-8") as dst:
                dst.write(content)
            return True
    except Exception as exc:
        compat.console_log("template SVG fallback failed: " + str(exc))
    return False


def render_page_svg(svg_path: str, width_px: int, height_px: int) -> Optional[Raster]:
    """Rasterise an SVG file to a :class:`Raster` of the given size."""
    if not compat.HAS_QT or compat.QtSvg is None:
        compat.console_log("Qt SVG renderer unavailable; cannot rasterise the page.")
        return None
    try:
        renderer = compat.QtSvg.QSvgRenderer(svg_path)
        if not renderer.isValid():
            return None
        image = compat.QtGui.QImage(width_px, height_px, compat.QtGui.QImage.Format_RGBA8888)
        image.fill(0xFFFFFFFF)
        painter = compat.QtGui.QPainter(image)
        try:
            renderer.render(painter)
        finally:
            painter.end()
        return _raster_from_qimage(image)
    except Exception as exc:
        compat.console_log("SVG render failed: " + str(exc))
        return None


def _raster_from_qimage(image: Any) -> Optional[Raster]:
    """Copy a ``QImage`` into a :class:`Raster`."""
    try:
        width, height = image.width(), image.height()
        buffer = compat.qimage_to_bytes(image)
        expected = width * height * 4
        if len(buffer) < expected:
            return None
        return Raster(width, height, bytearray(buffer[:expected]))
    except Exception as exc:
        compat.console_log("QImage -> Raster failed: " + str(exc))
        return None


def _grab_mdi(page: Any) -> Optional[Raster]:
    """Grab the on-screen widget showing ``page``, if it is open."""
    if not compat.HAS_GUI:
        return None
    try:
        import FreeCADGui  # type: ignore

        gui_doc = FreeCADGui.getDocument(page.Document.Name)
        view = gui_doc.getViewOfObject(page)
        if view is None:
            return None
        widget = view.widget() if hasattr(view, "widget") else None
        if widget is None or not hasattr(widget, "grab"):
            return None
        pixmap = widget.grab()
        image = pixmap.toImage().convertToFormat(compat.QtGui.QImage.Format_RGBA8888)
        return _raster_from_qimage(image)
    except Exception as exc:
        compat.console_log("MDI grab failed: " + str(exc))
        return None


def export_page_png(
    page: Any = None,
    path: str = "",
    dpi: int = DEFAULT_DPI,
    prefer_screen: bool = False,
) -> Tuple[bool, str, str]:
    """Render a TechDraw page to a PNG on the sheet's own paper size.

    Returns ``(ok, path, message)``.
    """
    from mrfreecad import drawing as drawing_mod

    if page is None:
        page = drawing_mod.active_page()
    if page is None:
        return (False, "", "Açık bir çizim (TechDraw sayfası) yok.")

    doc = page.Document
    if not path:
        base = os.path.splitext(os.path.basename(str(doc.FileName or "drawing")))[0]
        directory = os.path.dirname(str(doc.FileName or os.getcwd()))
        path = os.path.join(directory, base + ".png")

    width_mm, height_mm = drawing_mod.page_size_mm(page)
    width_px, height_px = canvas_px(width_mm, height_mm, dpi)

    raster: Optional[Raster] = None
    if prefer_screen:
        raster = _grab_mdi(page)

    used_screen = raster is not None
    if raster is None:
        handle, svg_path = tempfile.mkstemp(suffix=".svg", prefix="mrfree_page_")
        os.close(handle)
        try:
            if not _page_svg(page, svg_path):
                return (
                    False,
                    path,
                    "Sayfa PNG'ye çevrilemedi: TechDraw SVG dışa aktarımı "
                    "başarısız ve sayfa ekranda değil.\n\n"
                    "Sayfayı bir kez görüntüleyip tekrar deneyin ya da "
                    "headless çalışıyorsanız GUI ile açın.",
                )
            raster = render_page_svg(svg_path, width_px, height_px)
        finally:
            try:
                os.remove(svg_path)
            except OSError:
                pass

    if raster is None:
        return (False, path, "Sayfa raster'e çevrilemedi (Qt SVG yok?).")

    # A grabbed widget is window-sized, not paper-sized: scale it onto the sheet.
    if used_screen and (raster.width, raster.height) != (width_px, height_px):
        raster = fit_into_canvas(raster, width_px, height_px, margin=0.0)

    write_png(path, raster, dpi)
    message = "PNG dışa aktarıldı:\n{0}\n\nSayfa: {1} x {2} mm @ {3} dpi".format(
        path, round(width_mm, 1), round(height_mm, 1), dpi
    )
    if used_screen:
        message += "\n(not: ekrandan alındı)"
    return (True, path, message)


def export_view_png(
    path: str = "",
    width_px: int = 1600,
    height_px: int = 1200,
    transparent: bool = False,
) -> Tuple[bool, str, str]:
    """Capture the active 3D view to PNG.

    Thin wrapper over ``Gui.ActiveDocument.ActiveView.saveImage``; the trimming
    and sheet composition live in :mod:`mrfreecad.screencap`.
    """
    compat.require_freecad("View capture")
    if not compat.HAS_GUI:
        return (False, path, "3B görünüm yakalama için FreeCAD GUI gerekir.")

    if not path:
        doc = compat.gui().ActiveDocument
        if doc is None:
            return (False, "", "Açık bir doküman yok.")
        base = os.path.splitext(os.path.basename(str(doc.FileName or "view")))[0]
        directory = os.path.dirname(str(doc.FileName or os.getcwd()))
        path = os.path.join(directory, base + ".png")

    view = getattr(compat.gui().ActiveDocument, "ActiveView", None)
    if view is None:
        return (False, path, "3B görünüm (viewport) alınamadı.")

    background = "Transparent" if transparent else "White"
    try:
        ok = view.saveImage(path, int(width_px), int(height_px), background)
    except Exception as exc:
        return (False, path, "Görünüm kaydedilemedi: " + str(exc))
    if not ok or not os.path.isfile(path):
        return (False, path, "Görünüm kaydedilemedi.")
    return (True, path, "PNG kaydedildi:\n" + path)
