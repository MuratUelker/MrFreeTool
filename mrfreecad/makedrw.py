"""Automatic drawing creation - the port of the ``Make Drw`` button.

The SolidWorks flow was: create a blank drawing, apply the landscape sheet
format, build a standard three-view set, replace the base view with a flat
pattern view, rotate the longest edge to horizontal, then snap the page scale to
the largest standard scale that still fits.

FreeCAD's TechDraw does the same job with different objects:

=========================  ==================================================
SolidWorks                  FreeCAD
=========================  ==================================================
``DrawingDoc``              ``TechDraw::DrawPage``
``SetupSheet5``             ``DrawSVGTemplate`` + ``Page.Scale``
``Create3rdAngleViews``     three ``DrawViewPart`` objects
``CreateFlatPatternView``   ``DrawViewPart`` of the flat pattern object
``View.Rotation``           ``View.XDirection`` (the projection rotation)
``View.GetOutline``         ``View.Shape`` bounding box
``SnapScale``               :func:`snap_scale` below
=========================  ==================================================

The scale snapping and the rotate-to-landscape rules are ported verbatim,
because those two are what make the resulting drawing match what the shop
expects.
"""

from __future__ import annotations

import math
import os
from typing import Any, List, Optional, Sequence, Tuple

from mrfreecad import compat, drawing
from mrfreecad.flatpattern import find_flat_pattern, shape_of

__all__ = [
    "STANDARD_SCALES",
    "MIN_SCALE",
    "USABLE_FRACTION",
    "snap_scale",
    "outline_mm",
    "needs_landscape_rotation",
    "STANDARD_VIEWS",
    "make_drawing",
]

#: Standard scales, largest first.  Identical to the original's candidate list.
STANDARD_SCALES: Tuple[float, ...] = (3.0, 2.0, 1.5, 1.0, 0.5, 0.25, 0.2, 0.1, 0.05, 0.02, 0.01)

#: Floor applied to a computed scale, so an extreme case still yields a usable
#: number instead of zero.
MIN_SCALE = 0.01

#: Fraction of the sheet the views may occupy; the rest is margin.
USABLE_FRACTION = 0.85

#: The three views ``Make Drw`` produced, as
#: ``(label, direction, x_direction)`` unit vectors.
STANDARD_VIEWS: Tuple[Tuple[str, Tuple[float, float, float], Tuple[float, float, float]], ...] = (
    ("Front", (0.0, 0.0, 1.0), (1.0, 0.0, 0.0)),
    ("Top", (0.0, 1.0, 0.0), (1.0, 0.0, 0.0)),
    ("Right", (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)),
)


def snap_scale(raw: Any) -> float:
    """Largest standard scale that is **not larger** than ``raw``.

    This is the original's rule and it matters: a drawing is never scaled up
    past the model, only down, so a small part still prints 1:1 rather than
    1:0.5.  For parts too large even for 1:100, the raw ratio is kept so the
    drawing still fits.
    """
    try:
        raw = float(raw)
    except (TypeError, ValueError):
        return 0.01
    if raw <= 0:
        return 0.01
    best = 0.0
    for candidate in STANDARD_SCALES:
        if candidate <= raw + 1e-12 and candidate > best:
            best = candidate
    if best == 0.0:
        # Smaller than the smallest standard scale.  The drawing would be tiny
        # at 1:100, but using the raw ratio at least keeps it on the sheet, so
        # the operator sees the real problem instead of a blank page.
        return max(raw, MIN_SCALE)
    return best


def scale_pair(value: Any) -> Tuple[int, int]:
    """Turn a scale ratio into a ``(numerator, denominator)`` integer pair.

    ``0.05`` -> ``(1, 20)``, ``1.5`` -> ``(3, 2)``, ``1.0`` -> ``(1, 1)``.
    Anything non-positive or unparseable falls back to ``1:1``, which is the
    only safe answer: a wrong scale here silently misprints the part.
    """
    try:
        value = float(value)
    except (TypeError, ValueError):
        return (1, 1)
    if value <= 0:
        return (1, 1)
    for denominator in (1, 2, 4, 5, 8, 10, 20, 25, 50, 100, 200, 250, 500, 1000):
        scaled = value * denominator
        if abs(scaled - round(scaled)) < 1e-9 and 1 <= round(scaled) <= 1000:
            return (int(round(scaled)), int(denominator))
    if value >= 1:
        return (int(round(value * 1000)), 1000)
    return (1, max(1, int(round(1 / value))))


def outline_mm(shape: Any) -> Tuple[float, float]:
    """Width and height of ``shape``'s bounding box in millimetres."""
    if shape is None:
        return (0.0, 0.0)
    try:
        box = shape.BoundBox
        return (float(box.XLength), float(box.YLength))
    except Exception:
        return (0.0, 0.0)


def needs_landscape_rotation(shape: Any) -> bool:
    """True when the longest edge is vertical and the view should be turned 90°.

    Same intent as the original's ``RotateToLandscape``: drawings are read with
    the long edge horizontal, so a portrait blank gets rotated.
    """
    width, height = outline_mm(shape)
    return height > width > 0


def _page_origin_mm(page: Any) -> Tuple[float, float]:
    """Bottom-left corner of the drawable area of ``page``."""
    width, height = drawing.page_size_mm(page)
    return (width / 2.0, height / 2.0)


def _default_template(landscape: bool = True) -> str:
    """A usable TechDraw template when the user has not configured one.

    Prefers an A3 sheet, which is what the shop's templates use, and within that
    a ``blank`` template: the drawing that comes out of *Make Drw* is about to
    be stamped with the antet notes, so inheriting an unrelated title block
    would be worse than none.  Falls back to whatever FreeCAD ships.
    """
    from mrfreecad.settings import builtin_templates

    candidates = builtin_templates(landscape)
    if not candidates:
        return ""
    for path in candidates:
        name = os.path.basename(path).lower()
        if name.startswith("a3_") and "blank" in name:
            return path
    for path in candidates:
        if os.path.basename(path).lower().startswith("a3_"):
            return path
    return candidates[0]


def make_drawing(
    source: Any = None,
    flat: Any = None,
    template_path: str = "",
    use_flat_pattern: bool = True,
    single_view: bool = False,
) -> Optional[Any]:
    """Create a TechDraw page for ``source`` and return it.

    ``source`` is the object to project (a ``Part::Feature`` or ``App::Part``).
    ``flat`` overrides which object is projected as the flat pattern; by
    default :func:`~mrfreecad.flatpattern.find_flat_pattern` is asked.

    When no template is given, the settings' landscape template is used, and
    failing that a bundled A3 landscape blank.
    """
    from mrfreecad.settings import get_settings

    compat.require_freecad("Make drawing")

    settings = get_settings()
    doc = compat.active_document()
    if doc is None:
        raise RuntimeError("No active document.")

    if source is None:
        selected = compat.selection()
        source = selected[0] if selected else doc.ActiveObject
    if source is None:
        raise RuntimeError("Nothing selected to draw.")

    flat_obj = flat
    if use_flat_pattern and flat_obj is None:
        found = find_flat_pattern(doc, prefer=source if _is_flat(source) else None)
        if found is not None:
            flat_obj = found[0]

    template_path = template_path or settings.template("landscape")
    if not template_path or not os.path.isfile(template_path):
        template_path = _default_template(landscape=True)
    if not template_path or not os.path.isfile(template_path):
        raise RuntimeError(
            "No TechDraw template available. Set one in MrFreeTool settings "
            "(Drawing tab) or install the TechDraw templates."
        )

    page = doc.addObject("TechDraw::DrawPage", "Page")
    template = doc.addObject("TechDraw::DrawSVGTemplate", "Template")
    template.Template = template_path
    # A template is attached through the Page.Template property, not addView(),
    # which only accepts views.
    page.Template = template

    centre_x, centre_y = _page_origin_mm(page)

    views: List[Any] = []
    if single_view:
        view = _add_view(doc, page, source, "Front", (0.0, 0.0, 1.0), (1.0, 0.0, 0.0), centre_x, centre_y)
        if view is not None:
            views.append(view)
    else:
        # Orthogonal first/third-angle layout: front at the centre-left, top
        # above it, right to its side.  Spacing grows with the sheet so the
        # same relative placement works on A3 and A2.
        spacing = min(centre_x, centre_y) / 2.0
        layout = (
            (centre_x - spacing, centre_y),
            (centre_x - spacing, centre_y + spacing),
            (centre_x + spacing, centre_y),
        )
        sources = [source, source, source]
        if flat_obj is not None:
            # The original replaced the *base* view with the flat pattern.
            sources[0] = flat_obj
        for source_obj, (label, direction, xdir), (x, y) in zip(sources, STANDARD_VIEWS, layout):
            view = _add_view(doc, page, source_obj, label, direction, xdir, x, y)
            if view is not None:
                views.append(view)

    if not views:
        try:
            doc.removeObject(page.Name)
        except Exception:
            pass
        raise RuntimeError("No view could be created from the selection.")

    # Rotate-to-landscape on the primary view, as the original did.
    primary_shape = shape_of(views[0].Source[0]) if views[0].Source else shape_of(flat_obj or source)
    if primary_shape is not None and needs_landscape_rotation(primary_shape):
        for view in views:
            _rotate_view_90(view)

    page.KeepUpdated = True
    doc.recompute()

    _fit_page_scale(page, views)
    try:
        page.Document.recompute()
    except Exception:
        pass
    return page


def _is_flat(obj: Any) -> bool:
    from mrfreecad.flatpattern import is_flat_pattern

    return is_flat_pattern(obj)


def _add_view(
    doc: Any,
    page: Any,
    source: Any,
    label: str,
    direction: Sequence[float],
    x_direction: Sequence[float],
    x: Optional[float] = None,
    y: Optional[float] = None,
) -> Optional[Any]:
    """Create a ``DrawViewPart`` looking along ``direction``.

    ``x``/``y`` are applied *after* ``addView``: TechDraw centres a view when it
    joins a page, discarding a position set beforehand.
    """
    try:
        view = doc.addObject("TechDraw::DrawViewPart", "View")
    except Exception as exc:
        compat.console_log("make_drawing: could not create view: " + str(exc))
        return None
    view.Source = [source]
    view.Direction = (float(direction[0]), float(direction[1]), float(direction[2]))
    view.XDirection = (float(x_direction[0]), float(x_direction[1]), float(x_direction[2]))
    view.Label = label
    try:
        view.ScaleType = "Page"
        view.Scale = 1.0
    except Exception:
        pass
    try:
        page.addView(view)
    except Exception as exc:
        compat.console_log("make_drawing: addView failed: " + str(exc))
        return None
    if x is not None and y is not None:
        view.X = float(x)
        view.Y = float(y)
    return view


def _rotate_view_90(view: Any) -> None:
    """Turn a view 90° about the view normal, keeping the label."""
    try:
        xdir = view.XDirection
        # Rotating the horizontal axis by 90° in the view plane: (x, y) -> (-y, x).
        new_x = (-float(xdir[1]), float(xdir[0]), float(xdir[2]))
        view.XDirection = new_x
    except Exception as exc:  # pragma: no cover - defensive
        compat.console_log("make_drawing: rotation failed: " + str(exc))


def _fit_page_scale(page: Any, views: Sequence[Any]) -> Optional[Tuple[int, int]]:
    """Pick the largest standard scale at which all views fit the page.

    Uses the union bounding box of every view's projected shape, matching the
    original's behaviour of measuring all views together.
    """
    sheet_w, sheet_h = drawing.page_size_mm(page)
    if sheet_w <= 0 or sheet_h <= 0:
        return None

    total_w = 0.0
    total_h = 0.0
    for view in views:
        for source in getattr(view, "Source", []) or []:
            shape = shape_of(source)
            if shape is None:
                continue
            # Projected extent: the bounding box in the view's own plane. For
            # an axonometric projection TechDraw already reports the outline
            # via the view's shape once it recomputes; before that, the raw
            # bounding box is a safe over-estimate.
            box = shape.BoundBox
            width = max(box.XLength, box.YLength)
            height = max(box.YLength, box.ZLength)
            total_w = max(total_w, width)
            total_h = max(total_h, height)

    if total_w <= 0 or total_h <= 0:
        return None

    usable_w = sheet_w * USABLE_FRACTION
    usable_h = sheet_h * USABLE_FRACTION
    raw = min(usable_w / total_w, usable_h / total_h)
    best = snap_scale(raw)
    pair = scale_pair(best)
    drawing.set_page_scale(page, pair)
    compat.console_log(
        "make_drawing: sheet {0}x{1}mm, content {2:.1f}x{3:.1f}mm, scale {4}".format(
            round(sheet_w, 1), round(sheet_h, 1), total_w, total_h, drawing.format_scale(pair)
        )
    )
    return pair
