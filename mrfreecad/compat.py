"""FreeCAD / PySide version shims.

MrFreeTool supports the whole 0.20 -> 1.x range, which means it has to deal
with two very different Qt bindings and a handful of API renames.  All of that
is funnelled through this module so the rest of the package can be written
against one stable surface.

Import rules obeyed by the whole package:

* :mod:`mrfreecad.compat` may import :mod:`FreeCAD` and PySide, nothing else
  from the package.
* Every other ``mrfreecad.*`` module imports FreeCAD lazily inside functions,
  or through the helpers defined here, so that the pure-Python half of the
  package (naming, presets, settings) can be unit tested without FreeCAD.
"""

from __future__ import annotations

import os
import sys
from typing import Any, Optional

__all__ = [
    "HAS_FREECAD",
    "HAS_GUI",
    "HAS_QT",
    "QT_VERSION",
    "QtCore",
    "QtGui",
    "QtWidgets",
    "QtSvg",
    "align",
    "exec_dialog",
    "require_freecad",
    "require_gui",
    "require_qt",
    "require_qapplication",
    "app",
    "gui",
    "qt_core",
    "qt_gui",
    "qt_widgets",
    "get_main_window",
    "active_document",
    "active_object",
    "selection",
    "find_object",
    "console_log",
    "report_to_user",
    "reload_addon",
    "user_app_data_dir",
    "qimage_to_bytes",
    "bytes_to_qimage",
]


# ---------------------------------------------------------------------------
# FreeCAD
# ---------------------------------------------------------------------------
try:  # pragma: no cover - exercised only inside FreeCAD
    import FreeCAD as _FreeCADModule

    HAS_FREECAD = True
except Exception:  # pragma: no cover - plain CPython / unit tests
    _FreeCADModule = None  # type: ignore[assignment]
    HAS_FREECAD = False


def app():
    """The ``FreeCAD`` module, guaranteed non-``None`` once checked.

    Callers must guard with :func:`require_freecad` first; this exists so the
    module is not reachable as a bare global that can be ``None`` mid-flow.
    """
    if _FreeCADModule is None:
        raise RuntimeError("The FreeCAD Python API is not available.")
    return _FreeCADModule


def require_qt(feature: str = "This feature") -> None:
    """Raise unless PySide is importable.

    Widget construction needs only PySide, not a running FreeCAD, so this is
    the check for dialogs and panels.  It is deliberately weaker than
    :func:`require_gui`, which additionally needs ``FreeCADGui``.
    """
    if not HAS_QT:
        raise RuntimeError("{0} needs PySide, which ships with the FreeCAD GUI.".format(feature))


def require_qapplication(feature: str = "This feature") -> None:
    """Raise unless a ``QApplication`` instance exists.

    Building a widget with no application aborts the process from inside Qt,
    which no Python ``try`` can catch, so the precondition is checked before
    any widget is created rather than around it.
    """
    require_qt(feature)
    if qt_widgets(feature).QApplication.instance() is None:
        raise RuntimeError(
            "{0} needs a running Qt application. Call it from inside the "
            "FreeCAD GUI, not from a standalone interpreter.".format(feature)
        )


def require_gui(feature: str = "This feature") -> None:
    """Raise unless the FreeCAD GUI (``FreeCADGui``) is available."""
    if not HAS_GUI:
        raise RuntimeError(
            "{0} needs the FreeCAD GUI. Run it from the graphical FreeCAD, "
            "not from freecadcmd.".format(feature)
        )


def gui():
    """The ``FreeCADGui`` module, imported on demand."""
    require_gui("FreeCADGui access")
    import FreeCADGui  # type: ignore

    return FreeCADGui


def require_freecad(feature: str = "This feature") -> None:
    """Raise a helpful error when a FreeCAD-only command is called outside it."""
    if not HAS_FREECAD:
        raise RuntimeError(
            "{0} needs the FreeCAD Python API. Run it from inside FreeCAD "
            "(Python console or macro), not from a standalone interpreter.".format(feature)
        )


def console_log(message: str) -> None:
    """Write to the FreeCAD report view, falling back to stderr."""
    text = "[MrFreeTool] " + str(message)
    if HAS_FREECAD:
        try:
            app().Console.PrintMessage(text + "\n")
            return
        except Exception:
            pass
    print(text, file=sys.stderr)


# ---------------------------------------------------------------------------
# PySide (Qt5 bindings on FreeCAD <= 0.21, Qt6 bindings on FreeCAD >= 1.0)
# ---------------------------------------------------------------------------
QtCore: Any = None
QtGui: Any = None
QtWidgets: Any = None
QtSvg: Any = None
QT_VERSION = 0
QT_BINDING = ""

for _binding in ("PySide6", "PySide2"):
    try:  # pragma: no cover - depends on the host
        QtCore = __import__(_binding + ".QtCore", fromlist=["QtCore"])
        QtGui = __import__(_binding + ".QtGui", fromlist=["QtGui"])
        QtWidgets = __import__(_binding + ".QtWidgets", fromlist=["QtWidgets"])
        QT_VERSION = 6 if _binding == "PySide6" else 5
        QT_BINDING = _binding
        break
    except Exception:
        continue

if QtSvg is None and QT_BINDING:  # pragma: no cover - depends on the host
    try:
        QtSvg = __import__(QT_BINDING + ".QtSvg", fromlist=["QtSvg"])
    except Exception:
        QtSvg = None

HAS_QT = QtWidgets is not None
HAS_GUI = HAS_QT and HAS_FREECAD


def qt_widgets(feature: str = "This feature"):
    """``QtWidgets``, guaranteed non-``None`` once checked."""
    if QtWidgets is None:
        raise RuntimeError("{0} needs PySide, which ships with the FreeCAD GUI.".format(feature))
    return QtWidgets


def qt_core(feature: str = "This feature"):
    """``QtCore``, guaranteed non-``None`` once checked."""
    if QtCore is None:
        raise RuntimeError("{0} needs PySide, which ships with the FreeCAD GUI.".format(feature))
    return QtCore


def qt_gui(feature: str = "This feature"):
    """``QtGui``, guaranteed non-``None`` once checked."""
    if QtGui is None:
        raise RuntimeError("{0} needs PySide, which ships with the FreeCAD GUI.".format(feature))
    return QtGui


def _shiboken():
    """The shiboken module matching the active binding, or ``None``."""
    if not QT_BINDING:
        return None
    name = "shiboken6" if QT_VERSION == 6 else "shiboken2"
    try:
        return __import__(name)
    except Exception:
        return None


def qimage_to_bytes(image: Any) -> bytes:
    """Copy a ``QImage``'s RGBA8888 pixel data out as ``bytes``.

    Qt does not expose the buffer portably, so this goes through shiboken,
    which is what every FreeCAD add-on ends up doing.  The Qt5 and Qt6 shiboken
    modules are tried in turn because the binding and the shiboken major
    version have to agree.
    """
    shiboken = _shiboken()
    if shiboken is None:
        return b""
    pointer = image.constBits()
    try:
        return bytes(shiboken.getBytes(pointer, image.sizeInBytes()))
    except Exception:
        # Some builds only expose the deprecated sip API on the buffer.
        try:
            return bytes(pointer)
        except Exception:
            return b""


def bytes_to_qimage(data: bytes, width: int, height: int):
    """Wrap raw RGBA ``data`` in a ``QImage`` sharing the same memory."""
    qt = qt_gui("QImage creation")
    image = qt.QImage(width, height, qt.QImage.Format_RGBA8888)
    shiboken = _shiboken()
    if shiboken is None:
        return None
    try:
        shiboken.setBytes(image.bits(), data, len(data))
    except Exception:
        try:
            shiboken.setBytes(image.bits(), data)
        except Exception:
            return None
    return image


def align(*names: str):
    """Resolve a Qt alignment flag across Qt5/Qt6 enum scopes.

    ``Qt.AlignCenter`` is a top level name on Qt5 but lives on
    ``Qt.AlignmentFlag`` on Qt6.  Callers pass the leaf name and get whatever
    the running binding provides.
    """
    if not HAS_QT:
        return None
    scope = QtCore.Qt
    for candidate in ("AlignmentFlag", "Alignment"):
        inner = getattr(scope, candidate, None)
        if inner is None:
            continue
        for name in names:
            value = getattr(inner, name, None)
            if value is not None:
                return value
    for name in names:  # pragma: no cover - defensive
        value = getattr(scope, name, None)
        if value is not None:
            return value
    return None


def exec_dialog(dialog) -> int:
    """``exec_()`` on Qt5, ``exec()`` on Qt6."""
    runner = getattr(dialog, "exec", None) or getattr(dialog, "exec_")
    return int(runner())


def get_main_window():
    """Return ``Gui.getMainWindow()`` or ``None`` when headless."""
    if not HAS_GUI:
        return None
    try:
        return gui().getMainWindow()
    except Exception:
        return None


def report_to_user(title: str, text: str, error: bool = False) -> None:
    """Show a report to the user.

    Falls back to the FreeCAD report view when there is no GUI, so headless
    runs still get their output instead of silence.
    """
    if HAS_GUI:
        try:
            mw = get_main_window()
            if mw is not None:
                if error:
                    QtWidgets.QMessageBox.critical(mw, title, text)
                else:
                    QtWidgets.QMessageBox.information(mw, title, text)
                return
        except Exception:
            pass
    console_log("{0}\n{1}".format(title, text))


# ---------------------------------------------------------------------------
# Document / selection helpers
# ---------------------------------------------------------------------------
def active_document(allow_none: bool = True):
    """The active document, or ``None``."""
    require_freecad("Active document access")
    try:
        doc = app().ActiveDocument
    except Exception:
        doc = None
    if doc is None and not allow_none:
        raise RuntimeError("No active document.")
    return doc


def selection():
    """The current selection as a list (empty list when there is no GUI)."""
    require_freecad("Selection access")
    try:
        selected = gui().Selection.getSelectionEx()
    except Exception:
        return []
    objects = []
    for entry in selected or []:
        obj = getattr(entry, "Object", None)
        if obj is not None:
            objects.append(obj)
    return objects


def active_object():
    """First selected object, or the active object of the active document."""
    picked = selection()
    if picked:
        return picked[0]
    doc = active_document()
    if doc is None:
        return None
    try:
        return doc.ActiveObject
    except Exception:
        return None


def find_object(doc, name: str):
    """``doc.getObject`` that never raises."""
    if doc is None or not name:
        return None
    try:
        return doc.getObject(name)
    except Exception:
        return None


def reload_addon(module_name: str = "mrfreecad") -> None:
    """Reload the package and all its submodules (development helper)."""
    if not HAS_FREECAD:
        return
    import importlib

    mods = sorted(
        (name for name in list(sys.modules) if name == module_name or name.startswith(module_name + ".")),
        key=len,
        reverse=True,
    )
    for name in mods:
        try:
            importlib.reload(sys.modules[name])
        except Exception as exc:  # pragma: no cover - best effort
            console_log("reload failed for {0}: {1}".format(name, exc))


def user_app_data_dir() -> str:
    """Directory MrFreeTool may write its own files to."""
    if HAS_FREECAD:
        try:
            return str(app().getUserAppDataDir())
        except Exception:
            pass
    return os.path.join(os.path.expanduser("~"), ".freecad", "MrFreeTool")
