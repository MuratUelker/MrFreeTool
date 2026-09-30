"""MrFreeTool GUI package.

The Qt-dependent modules in here are imported lazily through
:pep:`562` module ``__getattr__``, so ``import mrfreecad.gui`` is cheap and
cannot fail on a headless box.  The ``TYPE_CHECKING`` block below declares the
same names for type checkers, which cannot follow a lazy ``__getattr__``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:  # pragma: no cover - import-time aid for type checkers
    from mrfreecad.gui.dialogs import show_report
    from mrfreecad.gui.panel import open_panel, toggle_panel
    from mrfreecad.gui.settings_dialog import open_settings
    from mrfreecad.gui.workbench import deactivate, initialize

__all__ = ["open_panel", "toggle_panel", "open_settings", "show_report", "initialize", "deactivate"]

#: Which module each lazily resolved name lives in.
_SOURCES = {
    "open_panel": "mrfreecad.gui.panel",
    "toggle_panel": "mrfreecad.gui.panel",
    "open_settings": "mrfreecad.gui.settings_dialog",
    "show_report": "mrfreecad.gui.dialogs",
    "initialize": "mrfreecad.gui.workbench",
    "deactivate": "mrfreecad.gui.workbench",
}


def __getattr__(name: str) -> Callable[..., Any]:
    """Resolve a GUI entry point on first use.

    Importing on demand is what keeps the Qt import - and the Qt requirement -
    out of the headless code paths.
    """
    source = _SOURCES.get(name)
    if source is None:
        raise AttributeError("module 'mrfreecad.gui' has no attribute " + repr(name))
    import importlib

    return getattr(importlib.import_module(source), name)


def __dir__() -> list:
    return sorted(__all__)
