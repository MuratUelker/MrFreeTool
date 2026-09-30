"""FreeCAD workbench registration for MrFreeTool.

``InitGui.py`` calls :func:`initialize` on start-up and :func:`deactivate` on
shutdown.  A missing Qt import must never take FreeCAD's start-up down with it,
so everything is guarded and failures are reported to the report view.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

from mrfreecad import DEFAULT_COMMAND_GROUPS, compat
from mrfreecad import commands as cmd
from mrfreecad.version import VERSION_STRING

__all__ = ["MrFreeWorkbench", "ICON_DIR", "command_labels", "initialize", "deactivate"]

#: Repository root, i.e. the Mod folder FreeCAD loaded.  workbench.py lives in
#: <root>/mrfreecad/gui, so the root is three levels up.
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ICON_DIR = os.path.join(_ROOT, "icons")


def _icon(name: str) -> str:
    return os.path.join(ICON_DIR, name + ".svg")


def _label_for(name: str) -> str:
    from mrfreecad.commands import command_label

    return command_label(name)


class MrFreeWorkbench:
    """The workbench: toolbar button, menu, and the panel window."""

    MenuText = "MrFreeTool"
    ToolTip = "MrFreeTool - sheet metal üretim yardımcıları"
    Icon = _icon("mrfreetool")

    def __init__(self) -> None:
        self.__class__.Icon = _icon("mrfreetool")
        self.commands: Dict[str, Any] = {}
        self._registered = False
        self._commands_registered = False

    # -- lifecycle --------------------------------------------------------
    def Initialize(self) -> None:  # noqa: N802 - FreeCAD API name
        """Register the workbench and its commands with FreeCAD.

        Idempotent in both halves: the workbench is added at most once per
        instance (FreeCAD would otherwise list it twice) and the commands are
        only added on the first pass, so repeated loads do not accumulate
        duplicate entries.
        """
        if not compat.HAS_GUI:
            compat.console_log("MrFreeTool: GUI yok, komutlar Python üzerinden kullanılabilir.")
            return
        try:
            gui = compat.gui()
            if not self._registered:
                gui.addWorkbench(self)
                self._registered = True
            if self._commands_registered:
                return

            # One command per entry, labelled with its tab so the menu tree
            # mirrors the panel.  Thickness presets get their own commands
            # because the original had one button per thickness.
            for label, dotted in command_labels():
                self.commands[label] = self._handler(dotted)
                gui.addCommand(label, self.commands[label])
            self._commands_registered = True
        except Exception as exc:  # noqa: BLE001 - must not break start-up
            compat.console_log("MrFreeTool başlatılamadı: " + str(exc))

    def Activated(self) -> None:  # noqa: N802 - FreeCAD API name
        """Toolbar / menu click: show the panel."""
        try:
            from mrfreecad.gui.panel import toggle_panel

            toggle_panel()
        except Exception as exc:  # noqa: BLE001
            compat.console_log("MrFreeTool paneli açılamadı: " + str(exc))

    def Deactivated(self) -> None:  # noqa: N802 - FreeCAD API name
        """Hide the panel when another workbench is selected."""
        try:
            from mrfreecad.gui.panel import get_panel

            panel = get_panel()
            if panel is not None:
                panel.hide()
        except Exception:
            pass

    def GetClassName(self) -> str:  # noqa: N802 - legacy FreeCAD API
        return "Gui::PythonWorkbench"

    # -- helpers ----------------------------------------------------------
    def _handler(self, dotted: str):
        def handler():
            # The command itself is already guarded by commands.resolve(), so
            # nothing here can raise; the result is returned so callers (tests,
            # macros) can inspect it.
            return cmd.resolve(dotted)()

        return handler


def _thickness_labels() -> List[str]:
    from mrfreecad import normalize

    return list(normalize.PRESET_LABELS)


def command_labels() -> List[Tuple[str, str]]:
    """``(menu_label, dotted_command)`` for every command, in menu order.

    Built from the same sources as :meth:`MrFreeWorkbench.Initialize`, so the
    menu can never offer a command the registry does not have.
    """
    labels: List[Tuple[str, str]] = []
    for _group_id, group_label, command_names in DEFAULT_COMMAND_GROUPS:
        for dotted in command_names:
            labels.append((group_label + " " + _label_for(dotted), dotted))
    for label in _thickness_labels():
        labels.append(("Normalize " + label + " mm", "normalize.apply_thickness:" + label))
    return labels


# ---------------------------------------------------------------------------
# Module-level hooks used by InitGui.py
# ---------------------------------------------------------------------------
def initialize() -> MrFreeWorkbench:
    """Create and initialise the workbench instance."""
    workbench = MrFreeWorkbench()
    workbench.Initialize()
    if compat.HAS_FREECAD:
        try:
            compat.app().Console.PrintLog("MrFreeTool " + VERSION_STRING + " hazır.\n")
        except Exception:  # pragma: no cover - best effort
            pass
    return workbench


def deactivate() -> None:
    """Nothing to tear down; kept for symmetry with :func:`initialize`."""
    return None
