"""Persistent MrFreeTool settings.

The SolidWorks original kept its settings under
``HKEY_CURRENT_USER\\Software\\MrSWTool``.  FreeCAD has its own preference
tree, so MrFreeTool stores the identical set of values under
``BaseApp/Preferences/Mod/MrFreeTool`` via :class:`FreeCAD.ParamGet`.  That
keeps them inside the user's FreeCAD configuration rather than scattering JSON
files around, and lets ``freecad --write-config`` style tooling work.

The values themselves are ported 1:1:

===========================  ==========================================
SolidWorks registry value    MrFreeTool preference
===========================  ==========================================
``MaxScaleDenominator``      ``Scale/MaxDenominator``
``DefaultSheetFormatYatay``  ``Template/DefaultLandscape``
``DefaultSheetFormatDikey``  ``Template/DefaultPortrait``
``AyazsaSheetFormat``        ``Template/Ayazsa``
``KaradenizSheetFormat``     ``Template/Karadeniz``
``DxfLazerDefault``          ``Dxf/LaserDefault``
``DxfBendLinesDefault``      ``Dxf/BendLinesDefault``
``MaxQty``                   ``Drawing/MaxQty``
===========================  ==========================================

A :class:`SettingsStore` is a thin, typed facade over the raw parameter group.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from mrfreecad import compat

__all__ = [
    "PARAM_PATH",
    "DEFAULTS",
    "FIRMS",
    "DEFAULT_LOGO_SLOTS",
    "SettingsStore",
    "get_settings",
    "logo_slot",
    "user_template_dir",
    "builtin_templates",
    "LogoSlot",
]

#: FreeCAD parameter tree the settings live in.
PARAM_PATH = "User parameter:BaseApp/Preferences/Mod/MrFreeTool"

#: Built-in fallback values, used both as defaults and by the settings dialog.
DEFAULTS: Dict[str, Any] = {
    # Drawing ------------------------------------------------------------
    "Scale/MaxDenominator": 20,
    "Drawing/MaxQty": 10,
    "Drawing/Qty": 1,
    "Drawing/ScaleDenominator": 1,
    # Templates (FreeCAD analogue of the .slddrt sheet formats) ---------
    "Template/DefaultLandscape": "",
    "Template/DefaultPortrait": "",
    "Template/Ayazsa": "",
    "Template/Karadeniz": "",
    # Dxf ----------------------------------------------------------------
    "Dxf/LaserDefault": True,
    "Dxf/BendLinesDefault": True,
    "Dxf/OutputDir": "",
    "Dxf/Rotation": False,
    "Dxf/Simetri": False,
    # Normalize ----------------------------------------------------------
    "Normalize/KFactor": 0.5,
    "Normalize/AutoReliefTear": True,
    "Normalize/UnitSchema": 0,  # FreeCAD "Standard (mm, kg, s, degree)"
    "Normalize/Scene": "",
    # Screen cap / PDF ---------------------------------------------------
    "Capture/PaperWidthMm": 297.0,
    "Capture/PaperHeightMm": 210.0,
    "Capture/Dpi": 300,
    "Capture/TrimToContent": True,
    "Capture/FitFraction": 0.92,
    "Capture/BackgroundTolerance": 20,
    "Capture/Prefix": "screencap",
    "Pdf/FileName": "montaj talimat\u0131.pdf",
}

#: Logo placement slots, in millimetres on the paper, origin bottom-left.
#:
#: These are only *starting* values: the true position comes from the shop's own
#: TechDraw template, which cannot be read programmatically, so the position is
#: confirmed in the settings dialog.  The defaults therefore assume an A3
#: landscape sheet (420 x 297 mm) rather than A4, and sit inside it without
#: clipping.
DEFAULT_LOGO_SLOTS: Dict[str, Dict[str, float]] = {
    "Ayazsa": {"x": 330.0, "y": 40.0, "w": 80.0, "h": 20.0},
    "Karadeniz": {"x": 330.0, "y": 40.0, "w": 80.0, "h": 20.0},
}

#: Known firms for logo stamping.  Order matters: when stamping, every *other*
#: firm slot is cleaned before the selected logo is drawn.
FIRMS: Tuple[str, ...] = ("Ayazsa", "Karadeniz")


@dataclass
class LogoSlot:
    """A logo image placed at a fixed position on the paper, in mm."""

    firm: str
    image: str = ""
    x: float = 0.0
    y: float = 0.0
    w: float = 80.0
    h: float = 20.0
    #: Extra cleanup border in mm (x direction) applied before drawing.
    clear_pad_x: float = 2.0
    #: Extra cleanup border in mm (y direction) applied before drawing.
    clear_pad_y: float = 0.3

    def as_dict(self) -> Dict[str, float]:
        return {"x": self.x, "y": self.y, "w": self.w, "h": self.h}

    def fits(self, paper_w_mm: float, paper_h_mm: float) -> bool:
        """True when the slot lies entirely inside the sheet.

        Worth checking explicitly: a slot positioned for A3 but stamped onto an
        A4 capture is silently clipped at the edge, which produces a
        half-printed logo rather than an error.
        """
        return (
            self.x >= 0.0
            and self.y >= 0.0
            and (self.x + self.w) <= paper_w_mm
            and (self.y + self.h) <= paper_h_mm
        )


def logo_slot(firm: str) -> LogoSlot:
    """Default placement for ``firm`` (no image attached)."""
    values = DEFAULT_LOGO_SLOTS.get(firm, DEFAULT_LOGO_SLOTS["Ayazsa"])
    return LogoSlot(firm=firm, **dict(values))  # type: ignore[arg-type]


class SettingsStore:
    """Typed accessor over the FreeCAD parameter group.

    Falls back to an in-memory dictionary when FreeCAD is not importable, so
    unit tests and read-only tooling keep working.
    """

    def __init__(self, param_path: str = PARAM_PATH):
        self._param_path = param_path
        self._group = None
        self._memory: Dict[str, Any] = {}
        if compat.HAS_FREECAD:
            try:
                self._group = compat.app().ParamGet(param_path)
            except Exception as exc:  # pragma: no cover - defensive
                compat.console_log("settings: ParamGet failed, using memory: {0}".format(exc))
                self._group = None

    # -- raw access -------------------------------------------------------
    @property
    def persistent(self) -> bool:
        """True when values survive a FreeCAD restart."""
        return self._group is not None

    def _get(self, key: str, default: Any) -> Any:
        if self._group is None:
            return self._memory.get(key, default)
        try:
            return self._group.Get(key, default)
        except Exception:  # pragma: no cover - defensive
            return default

    def _set(self, key: str, value: Any) -> None:
        if self._group is None:
            self._memory[key] = value
            return
        try:
            self._group.SetString(key, str(value))
        except Exception as exc:  # pragma: no cover - defensive
            compat.console_log("settings: write of {0} failed: {1}".format(key, exc))

    # -- typed accessors --------------------------------------------------
    def get_int(self, key: str, default: Optional[int] = None) -> int:
        if default is None:
            default = int(DEFAULTS.get(key, 0))
        try:
            return int(self._get(key, default))
        except (TypeError, ValueError):
            return int(default)

    def get_float(self, key: str, default: Optional[float] = None) -> float:
        if default is None:
            default = float(DEFAULTS.get(key, 0.0))
        try:
            return float(self._get(key, default))
        except (TypeError, ValueError):
            return float(default)

    def get_bool(self, key: str, default: Optional[bool] = None) -> bool:
        if default is None:
            default = bool(DEFAULTS.get(key, False))
        raw = self._get(key, default)
        if isinstance(raw, str):
            return raw.strip().lower() in ("1", "true", "yes", "on")
        try:
            return bool(int(raw))
        except (TypeError, ValueError):
            return bool(raw)

    def get_str(self, key: str, default: Optional[str] = None) -> str:
        if default is None:
            default = str(DEFAULTS.get(key, ""))
        value = self._get(key, default)
        return "" if value is None else str(value)

    def set(self, key: str, value: Any) -> None:
        self._set(key, value)

    def set_int(self, key: str, value: int) -> None:
        self._set(key, int(value))

    def set_float(self, key: str, value: float) -> None:
        self._set(key, float(value))

    def set_bool(self, key: str, value: bool) -> None:
        self._set(key, 1 if value else 0)

    def set_str(self, key: str, value: str) -> None:
        self._set(key, "" if value is None else str(value))

    # -- domain helpers ---------------------------------------------------
    def logo(self, firm: str) -> LogoSlot:
        """Read the stored logo placement for ``firm``."""
        slot = logo_slot(firm)
        prefix = "Logo/" + firm + "/"
        slot.image = self.get_str(prefix + "Image")
        slot.x = self.get_float(prefix + "X", slot.x)
        slot.y = self.get_float(prefix + "Y", slot.y)
        slot.w = self.get_float(prefix + "W", slot.w)
        slot.h = self.get_float(prefix + "H", slot.h)
        slot.clear_pad_x = self.get_float(prefix + "PadX", slot.clear_pad_x)
        slot.clear_pad_y = self.get_float(prefix + "PadY", slot.clear_pad_y)
        return slot

    def set_logo(self, slot: LogoSlot) -> None:
        """Persist a logo placement."""
        prefix = "Logo/" + slot.firm + "/"
        self.set_str(prefix + "Image", slot.image)
        self.set_float(prefix + "X", slot.x)
        self.set_float(prefix + "Y", slot.y)
        self.set_float(prefix + "W", slot.w)
        self.set_float(prefix + "H", slot.h)
        self.set_float(prefix + "PadX", slot.clear_pad_x)
        self.set_float(prefix + "PadY", slot.clear_pad_y)

    def as_dict(self) -> Dict[str, Any]:
        """Snapshot of every known default plus any stored logo slots."""
        data: Dict[str, Any] = dict(DEFAULTS)
        for key in DEFAULTS:
            if isinstance(DEFAULTS[key], bool):
                data[key] = self.get_bool(key)
            elif isinstance(DEFAULTS[key], int):
                data[key] = self.get_int(key)
            elif isinstance(DEFAULTS[key], float):
                data[key] = self.get_float(key)
            else:
                data[key] = self.get_str(key)
        for firm in FIRMS:
            slot = self.logo(firm)
            data["Logo/" + firm] = slot.as_dict()
            data["Logo/" + firm + "/Image"] = slot.image
        return data

    def apply(self, values: Dict[str, Any]) -> None:
        """Write back a dictionary produced by :meth:`as_dict` (settings dialog)."""
        for firm in FIRMS:
            prefix = "Logo/" + firm + "/"
            slot = LogoSlot(
                firm=firm,
                image=str(values.get(prefix + "Image", "")),
                x=float(values.get(prefix + "X", 0.0)),
                y=float(values.get(prefix + "Y", 0.0)),
                w=float(values.get(prefix + "W", 40.0)),
                h=float(values.get(prefix + "H", 15.0)),
                clear_pad_x=float(values.get(prefix + "PadX", 2.0)),
                clear_pad_y=float(values.get(prefix + "PadY", 0.3)),
            )
            self.set_logo(slot)
        for key, default in DEFAULTS.items():
            if key not in values:
                continue
            value = values[key]
            if isinstance(default, bool):
                self.set_bool(key, bool(value))
            elif isinstance(default, int):
                self.set_int(key, int(value))
            elif isinstance(default, float):
                self.set_float(key, float(value))
            else:
                self.set_str(key, str(value))

    def flush(self) -> None:
        """Ask FreeCAD to write the parameter tree to ``user.cfg`` now."""
        if compat.HAS_FREECAD:
            try:
                compat.app().saveParameter()
            except Exception:  # pragma: no cover - best effort
                pass

    # -- convenience used all over the package ---------------------------
    def max_scale_denominator(self) -> int:
        value = self.get_int("Scale/MaxDenominator", 20)
        return value if value >= 3 else 20

    def set_max_scale_denominator(self, value: int) -> None:
        self.set_int("Scale/MaxDenominator", max(3, int(value)))

    def max_qty(self) -> int:
        return max(1, self.get_int("Drawing/MaxQty", 10))

    def set_max_qty(self, value: int) -> None:
        self.set_int("Drawing/MaxQty", max(1, int(value)))

    def qty(self) -> int:
        return max(1, self.get_int("Drawing/Qty", 1))

    def set_qty(self, value: int) -> None:
        self.set_int("Drawing/Qty", max(1, int(value)))

    def template(self, which: str) -> str:
        """Path of a stored TechDraw template.

        ``which`` is one of ``landscape``, ``portrait``, ``ayazsa``,
        ``karadeniz``.
        """
        key = {
            "landscape": "Template/DefaultLandscape",
            "portrait": "Template/DefaultPortrait",
            "ayazsa": "Template/Ayazsa",
            "karadeniz": "Template/Karadeniz",
        }.get(which.lower(), "")
        return self.get_str(key) if key else ""

    def set_template(self, which: str, path: str) -> None:
        key = {
            "landscape": "Template/DefaultLandscape",
            "portrait": "Template/DefaultPortrait",
            "ayazsa": "Template/Ayazsa",
            "karadeniz": "Template/Karadeniz",
        }.get(which.lower(), "")
        if key:
            self.set_str(key, path)


#: Process-wide settings instance, created lazily by :func:`get_settings`.
_SETTINGS: Optional[SettingsStore] = None


def get_settings() -> SettingsStore:
    """Return the shared :class:`SettingsStore`."""
    global _SETTINGS
    if _SETTINGS is None:
        _SETTINGS = SettingsStore()
    return _SETTINGS


def user_template_dir() -> str:
    """Directory FreeCAD ships TechDraw templates in."""
    if not compat.HAS_FREECAD:
        return ""
    try:
        return os.path.join(str(compat.app().getResourceDir()), "Mod", "TechDraw", "Templates")
    except Exception:  # pragma: no cover - defensive
        return ""


def builtin_templates(landscape: bool = True) -> List[str]:
    """TechDraw templates bundled with FreeCAD, best candidates first.

    FreeCAD keeps most templates in ``ISO/`` and ``ASME/`` subdirectories with
    only a couple loose in the root, so the search has to recurse - a
    non-recursive scan finds almost nothing and leaves *Make Drw* without a
    fallback.

    Ranking matters because a blank template is the one to fall back on: it
    carries the paper size but no title block, which is the right default for a
    drawing the user is about to stamp their own notes onto.  Named sizes are
    preferred so the sheet size is a deliberate choice rather than whatever was
    first on disk.
    """
    directory = user_template_dir()
    if not directory or not os.path.isdir(directory):
        return []

    found: List[str] = []
    for dirpath, dirnames, filenames in os.walk(directory):
        dirnames.sort()
        for name in sorted(filenames):
            if not name.lower().endswith(".svg"):
                continue
            if _template_orientation(name) != ("landscape" if landscape else "portrait"):
                continue
            found.append(os.path.join(dirpath, name))

    found.sort(key=_template_rank)
    return found


def _template_rank(path: str) -> Tuple[int, int, str]:
    """Sort key: neutral English templates first, then named size, then blank.

    Three things are ranked, in order:

    1. ``localized`` — FreeCAD ships translated copies under
       ``ISO/localized/<lang>/``; English is the sane default for a shop whose
       other documents are in English.
    2. paper size — a named size (A3, A4, ...) beats an unsized sheet, so the
       sheet size is a deliberate choice rather than whatever came first.
    3. ``blank`` — a blank template carries the frame without someone else's
       title block, which is the right default for a drawing that is about to be
       stamped with the user's own notes.
    """
    lowered = path.lower()
    name = os.path.basename(lowered)
    localized = "localized" in lowered
    has_size = any(tag in name for tag in ("a0", "a1", "a2", "a3", "a4", "ansia", "ansib", "ansic"))
    is_blank = "blank" in name

    if has_size and not is_blank:
        content = 0
    elif has_size and is_blank:
        content = 1
    else:
        content = 2
    return (1 if localized else 0, content, name)


def _template_orientation(name: str) -> Optional[str]:
    """``'landscape'``, ``'portrait'`` or ``None`` for a template file name.

    A name that says neither is treated as usable for both, so an untitled
    sheet is not excluded just because it omits the orientation.
    """
    lowered = name.lower()
    if any(tag in lowered for tag in ("portrait", "vert", "_p.")):
        return "portrait"
    if any(tag in lowered for tag in ("landscape", "yatay", "dikey")):
        return "landscape"
    return None
