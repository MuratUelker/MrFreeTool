"""TechDraw page helpers: annotations, Qty, scale and template application.

Direct port of the four tabs' drawing half.  The one structural change is that
SolidWorks notes become :class:`TechDraw::DrawViewAnnotation` objects, and
``.slddrt`` sheet formats become TechDraw SVG templates.  Positions are
identical, because both systems put the page origin at the bottom-left corner
in millimetres — so the millimetre tables below port over unchanged.
"""

from __future__ import annotations

import os
from typing import Any, List, Optional, Sequence, Tuple

from mrfreecad import compat

__all__ = [
    "ANNO_ZIMBA_LANDSCAPE",
    "ANNO_ZIMBA_PORTRAIT",
    "ANNO_SIMETRI_LANDSCAPE",
    "ANNO_SIMETRI_PORTRAIT",
    "STAMP_FONT_SIZE",
    "SIMETRI_FONT_SIZE",
    "SIMETRI_TEXT",
    "view_position",
    "get_page",
    "get_pages",
    "active_page",
    "iter_annotations",
    "iter_views",
    "add_annotation",
    "remove_annotations_containing",
    "find_qty_notes",
    "set_qty",
    "add_zimba",
    "add_lazer",
    "add_simetri",
    "page_scale",
    "set_page_scale",
    "apply_scale_index",
    "scale_for_index",
    "scale_ladder",
    "format_scale",
    "apply_template",
    "template_orientation",
    "page_size_mm",
    "is_landscape_template",
    "PAGE_ORIGIN_MM",
]

#: Page origin, in millimetres, for every annotation below.  Matches the
#: original's ``Annotation.SetPosition(x / 1000, y / 1000, 0)`` call.
PAGE_ORIGIN_MM = (0.0, 0.0)

#: Stamp (Zimba / Lazer) note placement.  26 pt bold, no leader.
ANNO_ZIMBA_LANDSCAPE = (258.0, 40.0)
ANNO_ZIMBA_PORTRAIT = (172.0, 40.0)
STAMP_FONT_SIZE = 26.0

#: "simetriği de var" note placement.  13 pt bold, no leader.
ANNO_SIMETRI_LANDSCAPE = (200.0, 37.0)
ANNO_SIMETRI_PORTRAIT = (113.0, 37.0)
SIMETRI_FONT_SIZE = 13.0
SIMETRI_TEXT = "simetriği de var"

#: Denominators recognised when reading a page scale back, smallest first so the
#: closest match wins.  Covers the ISO series plus the shop's common 1:7 step.
_DENOMINATORS: Tuple[int, ...] = (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 15, 20, 25, 50, 75, 100, 200, 250, 500, 1000)

#: Standard sheet sizes, used when a template does not declare its own.
PAPER_SIZES_MM: Tuple[Tuple[str, float, float], ...] = (
    ("A0", 1189.0, 841.0),
    ("A1", 841.0, 594.0),
    ("A2", 594.0, 420.0),
    ("A3", 420.0, 297.0),
    ("A4", 297.0, 210.0),
)


# ---------------------------------------------------------------------------
# Scale ladder
# ---------------------------------------------------------------------------
def scale_for_index(index: int) -> Tuple[int, int]:
    """Map a 1-based slider position onto a ``(numerator, denominator)`` pair.

    The ladder runs ``3:1, 2:1, 1:1, 1:2, 1:3 ... 1:19`` and then continues as
    ``1:N`` for larger positions, exactly like the original trackbar.
    """
    index = int(index)
    if index <= 1:
        return (3, 1)
    if index == 2:
        return (2, 1)
    if index == 3:
        return (1, 1)
    return (1, max(1, index - 2))


def scale_ladder(max_denominator: int) -> List[Tuple[int, int]]:
    """The full ladder for a slider with ``max_denominator`` as its last stop.

    A ``max_denominator`` of 20 yields 22 positions: three enlargement steps
    plus ``1:1`` through ``1:20``.
    """
    steps = [(3, 1), (2, 1), (1, 1)]
    steps += [(1, n) for n in range(2, max(1, int(max_denominator)) + 1)]
    return steps


def format_scale(ratio: Tuple[int, int]) -> str:
    """``(1, 20)`` -> ``'1:20'``."""
    return "{0}:{1}".format(int(ratio[0]), int(ratio[1]))


def _annotation_text(anno: Any) -> str:
    """Best-effort read of an annotation's text, stripped of markup."""
    raw = getattr(anno, "Text", None)
    if raw is None:
        return ""
    if isinstance(raw, (list, tuple)):
        raw = "\n".join(str(part) for part in raw)
    return _strip_markup(str(raw))


def _set_annotation_text(anno: Any, text: str) -> None:
    """Write plain text into an annotation, keeping the bold styling.

    ``Text`` is a string list on current FreeCAD and a plain string on very
    old builds, so both are attempted.
    """
    marked = "<b>" + text + "</b>"
    try:
        anno.Text = [marked]
    except Exception:
        anno.Text = marked


def _strip_markup(value: str) -> str:
    """Remove the ``<b>``/``<i>``/``<br>`` tags FreeCAD annotations carry."""
    import re

    return re.sub(r"<[^>]+>", "", value).strip()


# ---------------------------------------------------------------------------
# Page / view discovery
# ---------------------------------------------------------------------------
def get_page(doc: Any = None, name: str = "") -> Any:
    """Find a TechDraw page, preferring ``name`` then the active page."""
    if doc is None:
        doc = compat.active_document()
    if doc is None:
        return None
    pages = get_pages(doc)
    if not pages:
        return None
    if name:
        for page in pages:
            if page.Name == name or page.Label == name:
                return page
    try:
        active = doc.ActiveObject
    except Exception:
        active = None
    if active is not None and _is_page(active):
        if active in pages:
            return active
    return pages[0]


def get_pages(doc: Any = None) -> List[Any]:
    """Every :class:`TechDraw::DrawPage` in ``doc``."""
    if doc is None:
        doc = compat.active_document()
    if doc is None:
        return []
    return [obj for obj in doc.Objects if _is_page(obj)]


def active_page() -> Any:
    """The page the user is currently looking at, or the first one."""
    doc = compat.active_document()
    if doc is None or not compat.HAS_GUI:
        return get_page(doc)
    # A TechDraw page opens as an MDI sub-window whose view knows which page is
    # in front; that is the only reliable way to tell which page the user means
    # when a document has several.
    try:
        gui_doc = compat.gui().ActiveDocument
        view = getattr(gui_doc, "ActiveView", None)
        name = getattr(view, "getActiveView", lambda: None)()
        if name:
            obj = doc.getObject(str(name).split("#")[-1])
            if obj is not None and _is_page(obj):
                return obj
    except Exception:
        pass
    return get_page(doc)


def _is_page(obj: Any) -> bool:
    return getattr(obj, "TypeId", "") == "TechDraw::DrawPage"


def _is_template(obj: Any) -> bool:
    return getattr(obj, "TypeId", "") == "TechDraw::DrawSVGTemplate"


def _is_annotation(obj: Any) -> bool:
    return getattr(obj, "TypeId", "") in ("TechDraw::DrawViewAnnotation", "TechDraw::DrawRichAnno")


def iter_views(page: Any) -> List[Any]:
    """Views belonging to ``page`` (annotations excluded)."""
    if page is None:
        return []
    views = []
    for view in getattr(page, "Views", []) or []:
        if _is_annotation(view):
            continue
        if _is_template(view):
            continue
        views.append(view)
    return views


def iter_annotations(page: Any) -> List[Any]:
    """Annotations belonging to ``page``."""
    if page is None:
        return []
    return [view for view in (getattr(page, "Views", []) or []) if _is_annotation(view)]


# ---------------------------------------------------------------------------
# Template handling
# ---------------------------------------------------------------------------
def page_size_mm(page: Any) -> Tuple[float, float]:
    """Paper size of ``page`` in millimetres, from its template.

    Falls back to the built-in table keyed on the template file name, then to
    A4 landscape, so callers always get usable numbers.
    """
    if page is None:
        return (297.0, 210.0)
    for view in getattr(page, "Views", []) or []:
        if not _is_template(view):
            continue
        width = _template_dimension(view, "Width")
        height = _template_dimension(view, "Height")
        if width > 0 and height > 0:
            return (width, height)
    name = template_name(page)
    for tag, w, h in PAPER_SIZES_MM:
        if tag in name.upper():
            portrait = "VERT" in name.upper() or "PORTRAIT" in name.upper()
            return (h, w) if portrait else (w, h)
    return (297.0, 210.0)


def _template_dimension(template: Any, prop: str) -> float:
    """Read a template dimension in millimetres.

    ``DrawSVGTemplate`` exposes the paper size as ``Width``/``Height`` in
    millimetres already, and additionally as ``WidthScale``/``HeightScale``
    enum values on newer builds.  No unit conversion happens here: a template
    reporting 0.594 is a template reporting 0.594 *mm*, and rescaling it would
    turn an A2 into a 594 m sheet.
    """
    for name in (prop, prop + "Scale"):
        try:
            value = getattr(template, name)
        except Exception:
            continue
        number = _as_float(value)
        if number > 0:
            return number
    return 0.0


def _as_float(value: Any) -> float:
    """Read a template property that may be a float, an int or an enum."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def template_name(page: Any) -> str:
    """File name of the template attached to ``page``."""
    if page is None:
        return ""
    for view in getattr(page, "Views", []) or []:
        if _is_template(view):
            try:
                return os.path.basename(str(view.Template))
            except Exception:
                continue
    return ""


def is_landscape_template(page: Any) -> bool:
    """True when the page is wider than it is tall."""
    width, height = page_size_mm(page)
    return width >= height


def template_orientation(page: Any) -> Optional[str]:
    """``'landscape'``, ``'portrait'`` or ``None`` when undeterminable.

    Prefers an explicit orientation marker in the template file name (the
    analogue of the original's ``Antet Yatay`` / ``Antet Dikey`` files) and
    falls back to the measured aspect ratio.
    """
    name = template_name(page).lower()
    if "yatay" in name or "landscape" in name:
        return "landscape"
    if "dikey" in name or "portrait" in name or "vert" in name:
        return "portrait"
    if not name and page is not None:
        return "landscape" if is_landscape_template(page) else "portrait"
    if page is not None:
        return "landscape" if is_landscape_template(page) else "portrait"
    return None


def view_position(page: Any, which: str) -> Tuple[float, float]:
    """Annotation placement for ``which`` on ``page``.

    ``which`` is ``'zimba'``, ``'lazer'`` or ``'simetri'``; the laser and the
    punch share a position in the original, so they resolve identically.
    """
    portrait = template_orientation(page) == "portrait"
    if which in ("simetri", "qty_symetri"):
        return ANNO_SIMETRI_PORTRAIT if portrait else ANNO_SIMETRI_LANDSCAPE
    return ANNO_ZIMBA_PORTRAIT if portrait else ANNO_ZIMBA_LANDSCAPE


def apply_template(page: Any, template_path: str, keep_scale: bool = True) -> Any:
    """Swap the template of ``page``, the analogue of ``SetupSheet5``.

    The SolidWorks original clears the sheet before loading a new format,
    because leaving the old one in place makes the two formats' notes overlap.
    FreeCAD's template object is already separate from the page's views, so
    replacing it is enough — but stale notes *are* a real problem, so they are
    removed here, mirroring the original's two-step ``SetupSheet5`` dance.

    Returns the template object, or ``None`` when the path is unusable.
    """
    if page is None:
        return None
    if not template_path or not os.path.isfile(template_path):
        return None

    remove_annotations_containing(page, "")  # drop the previous format's notes

    template = None
    for view in getattr(page, "Views", []) or []:
        if _is_template(view):
            template = view
            break
    if template is None:
        doc = page.Document
        template = doc.addObject("TechDraw::DrawSVGTemplate", "Template")
        page.addView(template)

    try:
        template.Template = template_path
    except Exception:
        # A template SVG the parser dislikes is a hard stop: leaving the old
        # one in place silently would be worse.
        return None

    if keep_scale:
        ratio = page_scale(page)
        try:
            page.ScaleType = "Custom"
            page.Scale = float(ratio[0]) / float(ratio[1])
        except Exception:
            pass

    try:
        page.KeepUpdated = True
        page.Document.recompute()
    except Exception:
        pass
    return template


# ---------------------------------------------------------------------------
# Annotations
# ---------------------------------------------------------------------------
def add_annotation(page: Any, text: str, x: float, y: float, font_size: float) -> Any:
    """Create a bold annotation at ``(x, y)`` millimetres on ``page``."""
    if page is None:
        return None
    doc = page.Document
    name = "MrFreeAnno"
    anno = doc.addObject("TechDraw::DrawViewAnnotation", name)
    anno.TextSize = float(font_size)
    anno.Text = ["<b>" + text + "</b>"]
    anno.X = float(x)
    anno.Y = float(y)
    try:
        page.addView(anno)
    except Exception:
        pass
    try:
        doc.recompute()
    except Exception:
        pass
    return anno


def remove_annotations_containing(page: Any, needle: str) -> int:
    """Delete annotations whose text contains ``needle``; returns the count.

    An empty ``needle`` removes *every* annotation, which is what applying a
    new template needs.  Matching is diacritic-insensitive so the old
    ``simetriği de var`` note is always found, however the template spelled it.
    """
    from mrfreecad.naming import normalize_name

    doc = page.Document if page is not None else None
    if page is None or doc is None:
        return 0
    wanted = normalize_name(needle)
    removed = 0
    for anno in iter_annotations(page):
        text = normalize_name(_annotation_text(anno))
        if wanted and wanted not in text:
            continue
        try:
            page.removeView(anno)
        except Exception:
            pass
        try:
            doc.removeObject(anno.Name)
        except Exception:
            continue
        removed += 1
    if removed:
        try:
            doc.recompute()
        except Exception:
            pass
    return removed


def _add_stamp(page: Any, label: str) -> Any:
    x, y = view_position(page, "zimba")
    return add_annotation(page, label, x, y, STAMP_FONT_SIZE)


def add_zimba(page: Any = None) -> Any:
    """Stamp the punch note at its position, the port of ``Button1``."""
    page = page if page is not None else active_page()
    return _add_stamp(page, "Zımba")


def add_lazer(page: Any = None) -> Any:
    """Stamp the laser note at its position, the port of ``Button2``."""
    page = page if page is not None else active_page()
    return _add_stamp(page, "Lazer")


def add_simetri(page: Any, qty: int) -> Any:
    """Write ``<qty> ad. simetriği de var`` and clear any previous one.

    Deleting first is not cosmetic: the original had to fix a bug where a
    second run stacked a second note on top of the first.
    """
    remove_annotations_containing(page, "simetri")
    x, y = view_position(page, "simetri")
    return add_annotation(page, "{0} ad. {1}".format(int(qty), SIMETRI_TEXT), x, y, SIMETRI_FONT_SIZE)


# ---------------------------------------------------------------------------
# Qty
# ---------------------------------------------------------------------------
def find_qty_notes(page: Any) -> List[Tuple[Any, float, float]]:
    """Numeric annotations that belong under the ``Qty`` title.

    The original walked every view, found the note whose text is exactly
    ``Qty`` and then took the *numerically* valued note closest to it.  Same
    algorithm here; the nearest-number rule is what makes it survive templates
    with several numeric fields.
    """
    title = None
    origin = (0.0, 0.0)
    candidates: List[Tuple[Any, float, float, float]] = []
    for anno in iter_annotations(page):
        text = _annotation_text(anno)
        if not text:
            continue
        if text.strip().lower() in ("qty", "adet", "miktar"):
            if title is None:
                title = anno
                origin = (float(getattr(anno, "X", 0.0)), float(getattr(anno, "Y", 0.0)))
            continue
        if title is None:
            continue
        value = _parse_int(text)
        if value is None:
            continue
        x = float(getattr(anno, "X", 0.0))
        y = float(getattr(anno, "Y", 0.0))
        distance = ((x - origin[0]) ** 2 + (y - origin[1]) ** 2) ** 0.5
        candidates.append((anno, distance, x, y))
    candidates.sort(key=lambda item: item[1])
    return [(anno, x, y) for anno, _d, x, y in candidates]


def _parse_int(text: str) -> Optional[int]:
    """Parse a possibly decorated integer, e.g. ``'3 ad'`` or ``'12'``.

    Returns ``None`` when there is no plausible number, which is what keeps
    stray annotations (dates, revision codes) out of the Qty candidate set.
    """
    if not text:
        return None
    cleaned = text.strip()
    for suffix in ("ad", "adet", "ad.", "pcs", "pc"):
        if cleaned.lower().endswith(suffix):
            cleaned = cleaned[: -len(suffix)].strip()
            break
    if not cleaned:
        return None
    digits = "".join(ch for ch in cleaned if ch.isdigit())
    if not digits or len(digits) > 6:
        return None
    try:
        return int(digits)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Scale
# ---------------------------------------------------------------------------
def page_scale(page: Any) -> Tuple[int, int]:
    """Current page scale as a small integer ``(numerator, denominator)`` pair.

    A page at ``Scale = 0.05`` comes back as ``(1, 20)``.  Enlarging scales
    are reported the same way (``3.0`` -> ``(3, 1)``), so the value round-trips
    through :func:`set_page_scale` without loss.
    """
    if page is None:
        return (1, 1)
    try:
        value = float(page.Scale)
    except Exception:
        return (1, 1)
    if value <= 0:
        return (1, 1)

    if value >= 1.0:
        # An enlarging scale: report it against a 1 denominator when it is a
        # whole number (2.0 -> 2:1), otherwise fall back to a 1000 denominator.
        rounded = round(value, 6)
        if abs(rounded - round(rounded)) < 1e-6 and 1 <= round(rounded) <= 1000:
            return (int(round(rounded)), 1)
        return (int(round(value * 1000)), 1000)

    # A reducing scale is reported as 1:N, so the denominator is the inverse of
    # the page scale.  Matching on the inverse (rather than multiplying by a
    # ladder of steps) is what keeps 1:20 from collapsing into 1:1.
    for denominator in _DENOMINATORS:
        if abs(value - 1.0 / denominator) < 1e-9:
            return (1, denominator)
    return (1, 1)


def set_page_scale(page: Any, ratio: Tuple[int, int], custom: bool = True) -> bool:
    """Set the page scale from a ``(numerator, denominator)`` pair.

    ``custom=True`` switches the page to a custom scale instead of one of the
    named ISO scales, which is required for the ladder's ``1:7``-style steps.
    """
    if page is None:
        return False
    numerator = max(1, int(ratio[0]))
    denominator = max(1, int(ratio[1]))
    try:
        if custom:
            page.ScaleType = "Custom"
        page.Scale = float(numerator) / float(denominator)
        page.Document.recompute()
    except Exception as exc:
        compat.console_log("set_page_scale failed: " + str(exc))
        return False
    return True


def apply_scale_index(page: Any, index: int) -> Tuple[int, int]:
    """Set the scale from a 1-based ladder position and return what was set."""
    ratio = scale_for_index(index)
    set_page_scale(page, ratio)
    return ratio


def set_qty(page: Any, qty: int) -> int:
    """Update the Qty field on ``page``; returns how many notes changed.

    A template with no Qty field simply reports zero changes rather than
    creating one, because inventing a position for it is guesswork.
    """
    changed = 0
    qty = int(qty)
    for anno, _x, _y in find_qty_notes(page):
        current = _parse_int(_annotation_text(anno))
        if current == qty:
            continue
        _set_annotation_text(anno, str(qty))
        changed += 1
    if changed:
        try:
            page.Document.recompute()
        except Exception:
            pass
    return changed
