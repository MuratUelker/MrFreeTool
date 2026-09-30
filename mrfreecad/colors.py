"""Per-face colour randomisation and restore - the ``RandomizeC`` / ``RestoreC`` buttons.

The original randomised ``MaterialPropertyValues`` on every body of a part and
every component of an assembly, then removed the overrides to restore the
document appearance.

FreeCAD's equivalent is the view provider's ``ShapeColor``/``DiffuseColor``,
where a per-face list is the analogue of per-body overrides.  The tool keeps
the *original* colours so restore is exact rather than approximate, which the
original could not do - it relied on ``RemoveMaterialProperty`` resetting to
the document default.
"""

from __future__ import annotations

import random
from typing import Any, Dict, List, Optional, Tuple

from mrfreecad import compat

__all__ = ["randomize_colors", "restore_colors", "COLOR_KEY", "random_color"]

#: Property on the view provider where a saved palette is stashed.
COLOR_KEY = "MrFreeOriginalColors"


def _view_provider(obj: Any):
    """The view provider for ``obj``, or ``None`` in a headless run."""
    if obj is None or not compat.HAS_GUI:
        return None
    try:
        return obj.ViewObject
    except Exception:
        return None


def _pack(rgb: Tuple[float, float, float], alpha: float = 0.0) -> int:
    """FreeCAD packs a colour as ``0xRRGGBBAA``."""
    r = max(0, min(255, int(rgb[0] * 255)))
    g = max(0, min(255, int(rgb[1] * 255)))
    b = max(0, min(255, int(rgb[2] * 255)))
    a = max(0, min(255, int(alpha * 255)))
    return (r << 24) | (g << 16) | (b << 8) | a


def _unpack(value: int) -> Tuple[Tuple[float, float, float], float]:
    return (
        (((value >> 24) & 0xFF) / 255.0, ((value >> 16) & 0xFF) / 255.0, ((value >> 8) & 0xFF) / 255.0),
        (value & 0xFF) / 255.0,
    )


def random_color(seed: Optional[int] = None) -> Tuple[float, float, float]:
    """A random colour in the same range the original used.

    The original drew each channel from ``0.4 + Rnd * 0.6``, i.e. 40%..100% of
    full scale, so no face comes out near-black.  Same range, so results are
    equally legible.
    """
    rng = random.Random(seed)
    return tuple(0.4 + rng.random() * 0.6 for _ in range(3))  # type: ignore[return-value]


def _targets(obj: Any = None, doc: Any = None) -> List[Any]:
    """Objects to colour: the whole document, or the given object and children."""
    compat.require_freecad("Colour change")

    if obj is not None:
        collected = [obj]
        try:
            for child in obj.OutList:
                if child not in collected and hasattr(child, "Shape"):
                    collected.append(child)
        except Exception:
            pass
        return collected

    if doc is None:
        doc = compat.active_document()
    if doc is None:
        return []
    return [item for item in doc.Objects if hasattr(item, "Shape")]


def _save_originals(vp: Any, per_face: List[int], whole: int) -> None:
    try:
        vp.addProperty("App::PropertyIntegerList", COLOR_KEY, "MrFreeTool", "Colours before randomize")
        vp.setPropertyStatus(COLOR_KEY, "Hidden,ReadOnly")
    except Exception:
        pass
    try:
        vp.setPropertyStatus(COLOR_KEY, "Hidden")
    except Exception:
        pass
    try:
        setattr(vp, COLOR_KEY, per_face + [whole])
    except Exception as exc:
        compat.console_log("could not store original colours: " + str(exc))


def randomize_colors(obj: Any = None, seed: Optional[int] = None, per_face: bool = True) -> Tuple[bool, str]:
    """Give every face of the target a random colour.

    The previous colours are stashed on the view provider so
    :func:`restore_colors` can put them back exactly.  Returns ``(ok, message)``.
    """
    targets = _targets(obj)
    if not targets:
        return (False, "Renklendirilecek nesne yok.")

    coloured = 0
    faces_total = 0
    for target in targets:
        vp = _view_provider(target)
        if vp is None:
            continue
        shape = getattr(target, "Shape", None)
        face_count = 0
        if shape is not None:
            try:
                face_count = len(shape.Faces)
            except Exception:
                face_count = 0

        current_whole = 0
        current_faces: List[int] = []
        try:
            current_whole = int(vp.ShapeColor)
            current_faces = [int(c) for c in (vp.DiffuseColor or [])]
        except Exception:
            pass
        if not current_faces and face_count:
            try:
                current_faces = [current_whole] * face_count
            except Exception:
                current_faces = []
        if not any((current_faces, current_whole)):
            continue

        _save_originals(vp, current_faces, current_whole)

        if per_face and face_count:
            colours = []
            for _ in range(face_count):
                colours.append(_pack(random_color(seed)))
            try:
                vp.DiffuseColor = colours
            except Exception as exc:
                compat.console_log("per-face colour failed on {0}: {1}".format(target.Label, exc))
                continue
            faces_total += face_count
        else:
            try:
                vp.ShapeColor = _pack(random_color(seed))
            except Exception:
                continue
            faces_total += 1
        coloured += 1

    if not coloured:
        return (False, "Hiçbir nesne renklendirilemedi (GUI gerekli).")

    return (
        True,
        "Renklendirildi: " + str(coloured) + " nesne / " + str(faces_total) + " yüzey.\n"
        "Eski renkler saklandı; 'Renkleri geri al' ile birebir geri alınır.",
    )


def restore_colors(obj: Any = None) -> Tuple[bool, str]:
    """Restore the colours saved by :func:`randomize_colors`.

    Falls back to clearing the per-face override when no palette was stashed,
    which reproduces the original's ``RemoveMaterialProperty`` behaviour for
    documents coloured before this tool ever saw them.
    """
    targets = _targets(obj)
    if not targets:
        return (False, "Nesne yok.")

    restored = 0
    for target in targets:
        vp = _view_provider(target)
        if vp is None:
            continue
        saved = None
        try:
            saved = getattr(vp, COLOR_KEY, None)
        except Exception:
            saved = None
        if not saved:
            try:
                vp.DiffuseColor = []
                restored += 1
            except Exception:
                pass
            continue
        try:
            values = [int(v) for v in saved]
            vp.DiffuseColor = values[:-1] if len(values) > 1 else []
            vp.ShapeColor = values[-1]
            try:
                vp.setPropertyStatus(COLOR_KEY, "Hidden")
            except Exception:
                pass
            restored += 1
        except Exception as exc:
            compat.console_log("restore failed on {0}: {1}".format(target.Label, exc))

    if not restored:
        return (False, "Geri alınacak renk bulunamadı.")
    return (True, "Renkler geri alındı: " + str(restored) + " nesne.")
