"""Flat pattern discovery.

The SolidWorks original relied on the sheet-metal addin's *Unfold* feature and
searched the feature tree for it by name and by type name.  FreeCAD has no
built-in unfold, so this module tries the realistic sources in order and
reports honestly when none is available:

1. an explicit **SheetMetal** workbench ``Unfold`` / ``Unbender`` feature,
2. any object whose type or label marks it as an unfolding,
3. the selected object, when it is already flat (a single-face sheet),
4. nothing — the caller is told to create an unfold first.

Guessing is deliberately avoided: writing a *wrong* DXF is far more expensive
than refusing, because the file goes straight to the laser.
"""

from __future__ import annotations

from typing import Any, List, Optional, Tuple

from mrfreecad import compat
from mrfreecad.naming import normalize_name

__all__ = [
    "is_flat_pattern",
    "is_flat_pattern_label",
    "find_flat_pattern",
    "find_flat_shapes",
    "shape_of",
    "FLAT_LABEL_HINTS",
    "FLAT_TYPE_HINTS",
]

#: Type-Id prefixes/substrings that mark an unfolding feature.
FLAT_TYPE_HINTS: Tuple[str, ...] = (
    "sheetmetal::sheetmetalunfold",
    "sheetmetal::unbender",
    "sheetmetal::unfold",
    "flatpattern",
    "unfold",
    "unbender",
)

#: Label / name fragments that mark an unfolding feature, folded for compare.
FLAT_LABEL_HINTS: Tuple[str, ...] = (
    "acilim",  # açılım
    "acınım",  # açınım
    "duz acilim",  # düz açılım
    "flat pattern",
    "flat-pattern",
    "flatten",
    "unfold",
    "unbend",
    "sac acilim",  # sac açılım
)


def is_flat_pattern_label(label: str) -> bool:
    """True when ``label`` looks like a flat pattern feature name.

    The original's list was: ``Flat-Pattern``, ``Flat``, ``Açılım``, ``Açınım``
    and ``Flat Pattern``.  All of those are covered, plus the spellings that
    turn up in FreeCAD documents.
    """
    folded = normalize_name(label)
    if not folded:
        return False
    return any(normalize_name(hint) in folded for hint in FLAT_LABEL_HINTS)


def is_flat_pattern(obj: Any) -> bool:
    """True when ``obj``'s type or label marks it as an unfolding."""
    if obj is None:
        return False
    type_id = str(getattr(obj, "TypeId", "")).lower()
    if any(hint in type_id for hint in FLAT_TYPE_HINTS):
        return True
    for attribute in ("Label", "Name"):
        value = str(getattr(obj, attribute, "") or "")
        if is_flat_pattern_label(value):
            return True
    return False


def shape_of(obj: Any):
    """The ``Part.Shape`` of ``obj``, or ``None`` when it has none."""
    if obj is None:
        return None
    for attribute in ("Shape", "Proxy"):
        try:
            value = getattr(obj, attribute)
        except Exception:
            continue
        if value is None:
            continue
        shape = getattr(value, "Shape", None)
        if shape is not None and hasattr(shape, "Edges"):
            return shape
        if hasattr(value, "Edges"):
            return value
    return None


def find_flat_shapes(doc: Any = None) -> List[Tuple[Any, Any]]:
    """Every flat pattern candidate in ``doc`` as ``(object, shape)`` pairs.

    Ordered so the most likely candidate comes first: SheetMetal features
    first, then objects named like unfoldings, then single-face sheets.
    """
    if doc is None:
        doc = compat.active_document()
    if doc is None:
        return []

    strong: List[Tuple[Any, Any]] = []
    weak: List[Tuple[Any, Any]] = []

    for obj in doc.Objects:
        shape = shape_of(obj)
        if shape is None or not getattr(shape, "Edges", None):
            continue
        type_id = str(getattr(obj, "TypeId", "")).lower()
        if any(hint in type_id for hint in FLAT_TYPE_HINTS):
            strong.append((obj, shape))
        elif is_flat_pattern_label(str(getattr(obj, "Label", "") or "")) or is_flat_pattern_label(
            str(getattr(obj, "Name", "") or "")
        ):
            strong.append((obj, shape))
        elif _is_single_sheet(shape):
            weak.append((obj, shape))

    return strong + weak


def _is_single_sheet(shape: Any) -> bool:
    """True for a shape that is plausibly a flat blank: one solid, one face.

    A tolerance of a few solids is allowed because a blank with holes is still
    a single solid, while a bent part is not.
    """
    try:
        solids = shape.Solids
        if len(solids) != 1:
            return False
        faces = shape.Faces
        return 1 <= len(faces) <= 12
    except Exception:
        return False


def find_flat_pattern(doc: Any = None, prefer: Any = None) -> Optional[Tuple[Any, Any]]:
    """Best flat pattern candidate as ``(object, shape)``, or ``None``.

    ``prefer`` short-circuits the search when the caller already knows which
    object it wants.
    """
    if prefer is not None:
        shape = shape_of(prefer)
        if shape is not None:
            return (prefer, shape)

    selected = compat.selection()
    for obj in selected:
        if is_flat_pattern(obj):
            shape = shape_of(obj)
            if shape is not None:
                return (obj, shape)

    candidates = find_flat_shapes(doc)
    return candidates[0] if candidates else None
