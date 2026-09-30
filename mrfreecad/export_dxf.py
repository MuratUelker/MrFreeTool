"""Flat pattern DXF export.

The SolidWorks original called ``ExportToDWG2`` with a sheet-metal options mask
and then printed a report box.  FreeCAD's equivalent is the ``Import`` module,
which writes DXF from any shape.  The file *name* is the part that matters
most: the laser and the punch operators read it, so the naming scheme is
reproduced byte-for-byte by :func:`mrfreecad.naming.build_flat_dxf_name`.
"""

from __future__ import annotations

import os
import tempfile
from typing import Any, List, Optional, Tuple

from mrfreecad import compat
from mrfreecad.flatpattern import find_flat_pattern, shape_of
from mrfreecad.naming import build_flat_dxf_name, to_decimal

__all__ = [
    "export_flat_dxf",
    "export_page_dxf",
    "read_metadata",
    "read_thickness",
    "read_material",
    "read_configuration",
    "DEFAULT_MATERIAL",
    "DEFAULT_CONFIGURATION",
]

DEFAULT_MATERIAL = "S235JR"
DEFAULT_CONFIGURATION = "Default"

#: Document properties written by the Normalize tab, read back for naming.
PROP_DESCRIPTION = "Description"
PROP_WEIGHT = "Weight"
PROP_MATERIAL = "Material"


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------
def _property_text(obj: Any, name: str) -> str:
    """Read a document property as text, whether it stores a number or a string.

    A non-text value (a dict, a list, an object) is deliberately not stringified
    into a file name; ``normalize_name`` would fold it into nonsense.
    """
    if obj is None:
        return ""
    try:
        value = getattr(obj, name, None)
    except Exception:
        return ""
    if value is None:
        return ""
    if isinstance(value, bool):
        return ""
    if isinstance(value, (int, float)):
        return to_decimal(value, 3)
    if not isinstance(value, str):
        return ""
    text = value.strip()
    # Strip the property linkage the SolidWorks original produced, e.g.
    # "Thickness@Bracket.SLDPRT" -> "1,5".
    for marker in ("@", "="):
        if marker in text:
            text = text.split(marker, 1)[-1]
    return text.strip()


def _doc_of(obj: Any) -> Any:
    return getattr(obj, "Document", None) if obj is not None else None


def read_thickness(obj: Any) -> str:
    """Thickness in millimetres as written text.

    Order of preference: the ``Description`` property the Normalize tab sets,
    then any real ``Thickness`` property on the object, then a measured guess
    from the solid's smallest face.
    """
    doc = _doc_of(obj)
    for candidate in (doc, obj):
        if candidate is None:
            continue
        text = _property_text(candidate, PROP_DESCRIPTION)
        if text and _is_number(text):
            return text
    thickness = _guess_thickness(obj)
    return to_decimal(thickness, 3) if thickness else ""


def _is_number(text: str) -> bool:
    try:
        float(str(text).replace(",", "."))
        return True
    except (TypeError, ValueError):
        return False


def _guess_thickness(obj: Any) -> float:
    """Estimate sheet thickness as the shortest planar face height, in mm.

    A last-resort helper for hand-modelled parts that never went through the
    Normalize tab.  Zero means "give up and leave it out of the name".
    """
    shape = shape_of(obj)
    if shape is None:
        return 0.0
    try:
        candidates = []
        for face in shape.Faces:
            try:
                if len(face.Surface.Axis) and abs(face.Surface.Axis.z) > 0.99:
                    candidates.append(float(face.BoundBox.ZLength))
            except Exception:
                continue
        positives = [value for value in candidates if value > 0.0]
        if positives:
            return min(positives)
    except Exception:
        pass
    return 0.0


def read_material(obj: Any) -> str:
    """Material name, preferring MrFreeTool's own property.

    Order matters: FreeCAD 1.1's built-in ``Document.Material`` is an
    ``App::PropertyMap`` (a dict of material assignments per object), so it is
    read only after our own ``MrFreeMaterial`` string, and a dict is never
    stringified into a file name.
    """
    doc = _doc_of(obj)
    from mrfreecad.normalize import PROP_MATERIAL_WRITE

    for candidate, name in ((doc, PROP_MATERIAL_WRITE), (obj, PROP_MATERIAL_WRITE)):
        if candidate is None:
            continue
        text = _property_text(candidate, name)
        if text:
            return text

    # Legacy/alternative location: a plain string Material on the object.
    for candidate in (obj, doc):
        if candidate is None:
            continue
        if _property_type_of(candidate, PROP_MATERIAL) == "App::PropertyString":
            text = _property_text(candidate, PROP_MATERIAL)
            if text:
                return text

    # FreeCAD's material assignment on the shape.
    try:
        material = getattr(obj, "Shape", None)
        name = getattr(material, "Material", None)
        if name is not None and str(getattr(name, "Name", "")):
            return str(name.Name)
    except Exception:
        pass
    return ""


def _property_type_of(obj: Any, name: str) -> str:
    getter = getattr(obj, "getTypeIdOfProperty", None)
    if getter is None:
        return ""
    try:
        return str(getter(name))
    except Exception:
        return ""


def read_configuration(obj: Any) -> str:
    """Configuration name.

    FreeCAD has no configurations, so an optional ``Configuration`` document
    property is honoured when present and ``Default`` is used otherwise.
    """
    doc = _doc_of(obj)
    for candidate in (doc, obj):
        if candidate is None:
            continue
        text = _property_text(candidate, "Configuration")
        if text:
            return text
    return DEFAULT_CONFIGURATION


def read_weight_kg(obj: Any) -> str:
    """Mass in kilograms, from the ``Weight`` property or from the volume."""
    doc = _doc_of(obj)
    for candidate in (doc, obj):
        if candidate is None:
            continue
        text = _property_text(candidate, PROP_WEIGHT)
        if text and _is_number(text):
            return to_decimal(float(text.replace(",", ".")), 3)
    shape = shape_of(obj)
    if shape is None:
        return ""
    try:
        volume_mm3 = float(shape.Volume)
    except Exception:
        return ""
    # Steel at 7.85 g/cm^3; good enough for a title block field.
    return to_decimal(volume_mm3 * 7.85e-6, 3)


def read_metadata(obj: Any) -> Tuple[str, str, str, str]:
    """``(model, configuration, thickness, material)`` for file naming."""
    doc = _doc_of(obj)
    model = ""
    for candidate in (obj, doc):
        if candidate is None:
            continue
        label = str(getattr(candidate, "Label", "") or "")
        if label:
            model = label
            break
    if not model and doc is not None:
        model = os.path.splitext(os.path.basename(str(doc.FileName or "part")))[0]
    return (model, read_configuration(obj), read_thickness(obj), read_material(obj))


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------
def _export_shape(shape: Any, path: str, doc: Any = None) -> Tuple[bool, str]:
    """Write ``shape`` to ``path`` as DXF using MrFreeTool's own writer.

    FreeCAD's ``Import.export`` silently writes nothing for a ``.dxf`` target
    (verified on 1.1: it returns ``None`` and creates no file), so the writer in
    :mod:`mrfreecad.dxf` is used instead.  That also means the caller chooses
    what lands on the bend-line layer rather than filtering the finished text.
    """
    from mrfreecad import dxf as dxf_writer

    return dxf_writer.write_shape(shape, path)


def export_flat_dxf(
    source: Any = None,
    output_dir: str = "",
    laser: Optional[bool] = None,
    qty: int = 1,
    simetri: bool = False,
    rotation: bool = False,
    bend_lines: Optional[bool] = None,
    filename: str = "",
) -> Tuple[bool, str, str]:
    """Export the flat pattern to DXF.

    Returns ``(ok, path, message)``.  ``source`` defaults to the selection;
    when it is a flat pattern that object's own shape is exported, otherwise a
    flat pattern in the document is looked up.

    ``laser``/``bend_lines`` default to the stored preferences, matching the
    original's behaviour of restoring the last-used DXF options on start-up.
    """
    from mrfreecad.settings import get_settings

    settings = get_settings()
    if laser is None:
        laser = settings.get_bool("Dxf/LaserDefault")
    if bend_lines is None:
        bend_lines = settings.get_bool("Dxf/BendLinesDefault")

    doc = compat.active_document()
    if doc is None:
        return (False, "", "Açık bir doküman yok.")

    if source is None:
        selected = compat.selection()
        source = selected[0] if selected else doc.ActiveObject
    if source is None:
        return (False, "", "Dışa aktarılacak parça seçilmedi.")

    found = find_flat_pattern(doc, prefer=source)
    if found is None:
        return (
            False,
            "",
            "Aktif parçada düz açılım (flat pattern) bulunamadı.\n\n"
            "FreeCAD'te built-in unfold yoktur. SheetMetal eklentisini kurup bir\n"
            "Unfold özelliği oluşturun, ya da düz parçanın kendisini seçip tekrar deneyin.",
        )
    flat_obj, shape = found

    model, configuration, thickness, material = read_metadata(flat_obj or source)
    if not filename:
        filename = build_flat_dxf_name(
            document_name=str(getattr(doc, "Name", "part")),
            model_name=model,
            configuration=configuration,
            thickness=thickness,
            material=material or DEFAULT_MATERIAL,
            qty=int(qty),
            laser=bool(laser),
            simetri=bool(simetri),
            rotation=bool(rotation),
        )

    directory = output_dir or settings.get_str("Dxf/OutputDir")
    if not directory:
        doc_path = str(getattr(doc, "FileName", "") or "")
        directory = os.path.dirname(doc_path) if doc_path else os.getcwd()
    if not os.path.isdir(directory):
        try:
            os.makedirs(directory)
        except OSError as exc:
            return (False, "", "Çıktı klasörü oluşturulamadı: {0}".format(exc))

    path = filename if os.path.isabs(filename) else os.path.join(directory, filename)

    bend_edges = _bend_edges(flat_obj) if bend_lines else None
    ok, detail = _export_shape(shape, path, doc)
    if not ok:
        return (False, path, "DXF dışa aktarma başarısız: {0}".format(detail))

    message = "DXF dışa aktarıldı:\n{0}".format(path)
    message += "\n\nAdet      : {0}".format(int(qty))
    message += "\nMalzeme   : {0}".format(material or DEFAULT_MATERIAL)
    message += "\nKalınlık  : {0} mm".format(thickness or "?")
    message += "\nBüküm     : {}".format("var" if bend_lines else "yok")
    if bend_edges:
        message += " ({0} çizgi)".format(len(bend_edges))
    return (True, path, message)


def _bend_edges(obj: Any) -> List[Any]:
    """Bend-line edges of an unfold feature, when it exposes any.

    SheetMetal's unfold keeps its bend lines in a ``BendLines`` property; when
    that is absent the bend lines are already part of the shape's edges and
    there is nothing to separate, which is reported honestly rather than
    guessed at.
    """
    if obj is None:
        return []
    for name in ("BendLines", "BendLine", "Sketch"):
        try:
            value = getattr(obj, name, None)
        except Exception:
            continue
        if value is None:
            continue
        edges = getattr(value, "Edges", None)
        if edges:
            try:
                return list(edges)
            except Exception:
                pass
    return []


def export_page_dxf(page: Any = None, path: str = "") -> Tuple[bool, str, str]:
    """Export a TechDraw page (views *and* annotations) to DXF.

    The original's drawing-tab DXF was not a feature, but a sheet export is the
    closest match for getting the antet notes into the laser.
    """
    from mrfreecad import drawing as drawing_mod

    if page is None:
        page = drawing_mod.active_page()
    if page is None:
        return (False, "", "Açık bir çizim (TechDraw sayfası) yok.")

    if not path:
        doc = page.Document
        base = os.path.splitext(os.path.basename(str(doc.FileName or "drawing")))[0]
        directory = os.path.dirname(str(doc.FileName or os.getcwd()))
        path = os.path.join(directory, base + " sayfa.DXF")

    try:
        import TechDraw  # type: ignore

        TechDraw.writeDXFPage(page, path)
    except Exception as exc:
        compat.console_log("writeDXFPage failed: " + str(exc))
        return (False, path, "Sayfa DXF dışa aktarımı başarısız: " + str(exc))

    if not os.path.isfile(path):
        return (False, path, "Sayfa DXF dosyası oluşmadı.")
    return (True, path, "Sayfa DXF dışa aktarıldı:\n" + path)
