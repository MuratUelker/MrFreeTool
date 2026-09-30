"""Part normalisation: thickness, K-factor, relief and document properties.

Port of the ``Normalize`` tab.  The original had two mechanisms:

* ``Norm Part`` applied K-factor 0.5, automatic tear relief, wrote the
  ``Description`` / ``Weight`` / ``Material`` document properties, forced
  millimetre-kilogram units and applied a background scene;
* a row of thickness buttons inserted a base flange at a preset
  thickness/K-factor pair, and a ``t`` button read the thickness back.

FreeCAD has no sheet-metal feature tree, so the flange insertion cannot be
ported literally.  What *is* portable, and what actually matters downstream,
is the metadata: the K-factor, the bend radius, the thickness and the material
are what the DXF file name, the laser and the ERP read.  So this module writes
them as **real, typed document properties** with expression bindings, which is
the FreeCAD idiom and is better than a stringly-typed SolidWorks property.

The thickness / K-factor table is carried over exactly, because it encodes the
shop's process values.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

from mrfreecad import compat
from mrfreecad.naming import to_decimal

__all__ = [
    "THICKNESS_PRESETS",
    "preset_for_thickness",
    "preset_for_label",
    "PRESET_LABELS",
    "PROP_K_FACTOR",
    "PROP_BEND_RADIUS",
    "PROP_THICKNESS",
    "PROP_DESCRIPTION",
    "PROP_WEIGHT",
    "PROP_MATERIAL",
    "PROP_RELIEF",
    "norm_part",
    "apply_preset",
    "read_thickness_property",
    "ensure_property",
    "read_property",
]

#: ``(label, thickness_mm, k_factor, bend_radius_mm)``.
#:
#: Values are taken from the SolidWorks original: the thickness buttons each
#: paired a thickness with a K-factor, and the ``t`` button applied a matching
#: bend radius per thickness.  The pairings are the shop's process values and
#: are reproduced without change.
THICKNESS_PRESETS: Tuple[Tuple[str, float, float, float], ...] = (
    ("0,5", 0.5, 0.05, 1.5),
    ("0,7", 0.7, 0.05, 1.0),
    ("0,8", 0.8, 0.15, 1.0),
    ("1", 1.0, 0.24, 1.0),
    ("1,2", 1.2, 0.31, 1.0),
    ("1,5", 1.5, 0.17, 1.0),
    ("2", 2.0, 0.105, 1.0),
)

#: Order the buttons are laid out in, left to right.
PRESET_LABELS: Tuple[str, ...] = ("0,5", "0,8", "1", "1,2", "1,5", "2", "0,7")

PROP_K_FACTOR = "MrFreeKFactor"
PROP_BEND_RADIUS = "MrFreeBendRadius"
PROP_THICKNESS = "MrFreeThickness"
PROP_DESCRIPTION = "Description"
PROP_WEIGHT = "Weight"
PROP_MATERIAL = "Material"
PROP_RELIEF = "MrFreeRelief"

#: Custom property types added to the document.
_STRING_PROPS = (PROP_DESCRIPTION, PROP_WEIGHT, PROP_MATERIAL, PROP_RELIEF)


def preset_for_thickness(thickness: Any) -> Optional[Tuple[str, float, float, float]]:
    """The preset matching ``thickness`` in millimetres, or ``None``."""
    try:
        target = round(float(thickness), 4)
    except (TypeError, ValueError):
        return None
    for preset in THICKNESS_PRESETS:
        if abs(preset[1] - target) < 1e-4:
            return preset
    return None


def preset_for_label(label: Optional[str]) -> Optional[Tuple[str, float, float, float]]:
    """The preset with the given button label (``"0,5"``), or ``None``.

    The GUI addresses presets by their label because that is what the buttons
    carry, and the label uses a comma decimal separator while the value is
    read in millimetres.
    """
    wanted = (label or "").strip().replace(".", ",")
    for preset in THICKNESS_PRESETS:
        if preset[0] == wanted:
            return preset
    return None


# ---------------------------------------------------------------------------
# Document properties
# ---------------------------------------------------------------------------
def ensure_property(obj: Any, name: str, kind: str = "App::PropertyLength", group: str = "MrFreeTool") -> Any:
    """Add a custom property to ``obj`` if it is not already there.

    Existing properties of a matching name are left alone, so a document that
    already carries ``Description`` keeps whatever the user put there.
    """
    if obj is None:
        return None
    if hasattr(obj, name):
        return getattr(obj, name)
    try:
        obj.addProperty(kind, name, group, "MrFreeTool sheet-metal metadata")
    except Exception as exc:
        compat.console_log("addProperty({0}) failed: {1}".format(name, exc))
        return None
    return getattr(obj, name, None)


def read_property(obj: Any, name: str, default: Any = None) -> Any:
    """Read a property, returning ``default`` when it is absent or unset."""
    if obj is None:
        return default
    try:
        value = getattr(obj, name, None)
    except Exception:
        return default
    if value is None or value == "":
        return default
    return value


def _set_property(obj: Any, name: str, kind: str, value: Any) -> bool:
    if obj is None:
        return False
    prop = ensure_property(obj, name, kind)
    if prop is None:
        return False
    try:
        if kind == "App::PropertyString":
            setattr(obj, name, str(value))
        else:
            setattr(obj, name, float(value))
        return True
    except Exception as exc:
        compat.console_log("set {0} failed: {1}".format(name, exc))
        return False


def read_thickness_property(obj: Any) -> Optional[float]:
    """Thickness in millimetres, from ``MrFreeThickness`` then ``Thickness``."""
    for name in (PROP_THICKNESS, "Thickness"):
        value = read_property(obj, name)
        if value is None:
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if number > 0:
            return number
    return None


def _bind_expression(obj: Any, target: str, source_obj: Any, source_prop: str) -> bool:
    """Bind ``target`` to ``source_obj.<source_prop>`` via an expression.

    Keeps the metadata live - change the thickness and the description follows
    - which is what the SolidWorks linked properties achieved.
    """
    if obj is None or source_obj is None:
        return False
    label = str(getattr(source_obj, "Label", "") or "").replace("<<", "").replace(">>", "")
    if not label:
        return False
    if not hasattr(obj, "setExpression"):
        return False
    try:
        obj.setExpression(target, "<<{0}>>.{1}".format(label, source_prop))
        return True
    except Exception as exc:
        compat.console_log("bind {0} failed: {1}".format(target, exc))
        return False


# ---------------------------------------------------------------------------
# Norm Part
# ---------------------------------------------------------------------------
def norm_part(
    obj: Any = None,
    k_factor: Optional[float] = None,
    relief: str = "Tear",
    material: str = "",
    unit_schema: int = 0,
) -> Tuple[bool, str]:
    """Normalise the active model.

    Writes the metadata the rest of the toolchain reads: thickness, K-factor,
    bend radius, relief type, and the ``Description`` / ``Weight`` /
    ``Material`` document properties.  The description is bound by expression to
    the thickness, so it cannot drift.

    Returns ``(ok, message)``.
    """
    from mrfreecad.settings import get_settings

    compat.require_freecad("Norm part")
    settings = get_settings()
    if k_factor is None:
        k_factor = settings.get_float("Normalize/KFactor", 0.5)

    doc = compat.active_document()
    if doc is None:
        return (False, "Açık bir doküman yok.")

    if obj is None:
        selected = compat.selection()
        obj = selected[0] if selected else doc.ActiveObject
    if obj is None:
        return (False, "Normalize edilecek nesne yok.")

    applied: List[str] = []
    skipped: List[str] = []

    thickness = read_thickness_property(obj)
    preset = preset_for_thickness(thickness) if thickness else None

    if thickness is not None:
        _set_property(obj, PROP_THICKNESS, "App::PropertyLength", thickness)
        applied.append("Thickness = " + to_decimal(thickness) + " mm")
    else:
        skipped.append("Thickness (parçada kalınlık özelliği yok)")

    _set_property(obj, PROP_K_FACTOR, "App::PropertyFloat", float(k_factor))
    applied.append("K-Factor = " + to_decimal(k_factor, 4))

    if preset is not None:
        _set_property(obj, PROP_BEND_RADIUS, "App::PropertyLength", preset[3])
        applied.append("Bend radius = " + to_decimal(preset[3]) + " mm")
    else:
        skipped.append("Bend radius (bu kalınlık için ön tanım yok)")

    _set_property(obj, PROP_RELIEF, "App::PropertyString", str(relief))
    applied.append("Auto relief = " + str(relief))

    # Description carries the thickness, because the DXF file name and the
    # drawing title block both read it from there.
    thickness_text = to_decimal(thickness) if thickness is not None else ""
    _set_property(doc, PROP_DESCRIPTION, "App::PropertyString", thickness_text)
    applied.append("Description = " + (thickness_text or "(boş)"))
    if thickness is not None:
        _bind_expression(doc, PROP_DESCRIPTION, obj, PROP_THICKNESS)

    mass = _estimate_mass_kg(obj)
    _set_property(doc, PROP_WEIGHT, "App::PropertyString", to_decimal(mass, 3) if mass else "")
    applied.append("Weight = " + (to_decimal(mass, 3) + " kg" if mass else "(hesaplanamadı)"))

    if material:
        _set_property(doc, PROP_MATERIAL, "App::PropertyString", material)
        applied.append("Material = " + material)

    _apply_unit_schema(unit_schema)
    applied.append("Units = mm/kg (schema {0})".format(unit_schema))

    scene = settings.get_str("Normalize/Scene")
    if scene:
        if _apply_scene(scene):
            applied.append("Background = " + scene)
        else:
            skipped.append("Background (" + scene + " bulunamadı)")

    try:
        doc.recompute()
    except Exception:
        pass

    lines = ["=" * 59, "  NORMALİZE RAPORU", "=" * 59, "", "Nesne : " + str(getattr(obj, "Label", obj)), ""]
    lines.append("Uygulanan:")
    lines.extend("  ✓ " + item for item in applied)
    if skipped:
        lines.append("")
        lines.append("Atlanan:")
        lines.extend("  • " + item for item in skipped)
    return (True, "\n".join(lines))


def _estimate_mass_kg(obj: Any) -> Optional[float]:
    """Mass in kg from the solid's volume at 7.85 g/cm^3 (steel)."""
    shape = getattr(obj, "Shape", None)
    if shape is None:
        return None
    try:
        volume_mm3 = float(shape.Volume)
    except Exception:
        return None
    if volume_mm3 <= 0:
        return None
    return volume_mm3 * 7.85e-6


def _apply_unit_schema(schema: int) -> bool:
    """Set FreeCAD's display unit schema.  0 is Standard (mm, kg, s, deg)."""
    if not compat.HAS_FREECAD:
        return False
    try:
        params = compat.app().ParamGet("User parameter:BaseApp/Preferences/Units")
        params.SetInt("UserSchema", int(schema))
        return True
    except Exception as exc:
        compat.console_log("unit schema change failed: " + str(exc))
        return False


def _apply_scene(scene: str) -> bool:
    """Background image.  FreeCAD has no per-document background file setting,
    so the equivalent is the preference that points at a 3D background image."""
    if not compat.HAS_FREECAD or not os.path.isfile(scene):
        return False
    try:
        params = compat.app().ParamGet("User parameter:BaseApp/Preferences/View")
        params.SetString("BackgroundImage", scene)
        return True
    except Exception as exc:
        compat.console_log("background scene failed: " + str(exc))
        return False


# ---------------------------------------------------------------------------
# Thickness presets
# ---------------------------------------------------------------------------
def apply_preset(
    thickness: float,
    obj: Any = None,
    k_factor: Optional[float] = None,
) -> Tuple[bool, str]:
    """Apply a thickness preset's K-factor and bend radius to a model.

    Also stores the thickness itself, so a later export or drawing picks it up.
    Returns ``(ok, message)``.
    """
    compat.require_freecad("Thickness preset")

    preset = preset_for_thickness(thickness)
    if preset is None:
        available = ", ".join(label for label, _t, _k, _r in THICKNESS_PRESETS)
        return (False, "Bu kalınlık için ön tanım yok: " + to_decimal(thickness) + "\n\nSeçenekler: " + available)

    label, preset_thickness, preset_k, preset_radius = preset
    if k_factor is None:
        k_factor = preset_k

    doc = compat.active_document()
    if doc is None:
        return (False, "Açık bir doküman yok.")

    if obj is None:
        selected = compat.selection()
        obj = selected[0] if selected else doc.ActiveObject
    if obj is None:
        return (False, "Uygulanacak nesne yok.")

    _set_property(obj, PROP_THICKNESS, "App::PropertyLength", preset_thickness)
    _set_property(obj, PROP_K_FACTOR, "App::PropertyFloat", float(k_factor))
    _set_property(obj, PROP_BEND_RADIUS, "App::PropertyLength", preset_radius)
    _set_property(doc, PROP_DESCRIPTION, "App::PropertyString", to_decimal(preset_thickness))
    _bind_expression(doc, PROP_DESCRIPTION, obj, PROP_THICKNESS)

    try:
        doc.recompute()
    except Exception:
        pass

    message = (
        "Uygulandı: " + label + " mm\n"
        "  Thickness    : " + to_decimal(preset_thickness) + " mm\n"
        "  K-Factor     : " + to_decimal(k_factor, 4) + "\n"
        "  Bend radius  : " + to_decimal(preset_radius) + " mm\n"
        "  Nesne        : " + str(getattr(obj, "Label", obj))
    )
    return (True, message)
