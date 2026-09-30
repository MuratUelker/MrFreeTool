# MrFreeTool - FreeCAD workbench entry point.
#
# FreeCAD imports this file for every folder in the Mod search path on start-up.
# It must never raise: a broken add-on should log and disable itself, not stop
# FreeCAD from opening the user's drawing.

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

try:
    import FreeCAD

    FreeCAD.Console.PrintLog("MrFreeTool: mod yükleniyor...\n")
except Exception:  # pragma: no cover - FreeCAD always present in practice
    FreeCAD = None

try:
    import FreeCADGui

    from mrfreecad.gui.workbench import MrFreeWorkbench

    FreeCADGui.addWorkbench(MrFreeWorkbench())
except Exception as exc:  # pragma: no cover - headless or missing Qt
    if FreeCAD is not None:
        FreeCAD.Console.PrintError("MrFreeTool yüklenemedi (GUI): {0}\n".format(exc))
