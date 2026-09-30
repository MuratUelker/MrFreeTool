"""Type stubs for ``FreeCADGui``.

FreeCAD bundles this module with its own interpreter; it cannot be pip
installed.  See ``FreeCAD.pyi`` for why only the used surface is declared.

Most of the API is reached through ``mrfreecad.compat.gui()``, which imports
this lazily, so the stub only needs the names that module touches.
"""

from typing import Any, Callable, List, Optional, Sequence

class Selection:
    @staticmethod
    def getSelectionEx() -> List[Any]: ...
    @staticmethod
    def clearSelection() -> None: ...
    @staticmethod
    def addSelection(doc: str, name: str) -> None: ...

class View:
    def saveImage(self, path: str, width: int, height: int, background: str = "White") -> bool: ...
    def fitAll(self) -> None: ...
    def setCameraType(self, kind: str) -> None: ...
    def getActiveView(self) -> Optional[str]: ...

class GuiDocument:
    """A document as seen by the GUI layer: adds the 3D view.

    Inherits the data-side attributes from :class:`FreeCAD.Document` and adds
    the view, which is why code that needs both reaches for the GUI document.
    """

    ActiveView: Optional[View]
    Name: str
    Label: str
    FileName: str

    def getViewOfObject(self, obj: Any) -> Optional[Any]: ...

ActiveDocument: Optional[GuiDocument]

def getMainWindow() -> Any: ...
def addWorkbench(workbench: Any) -> None:
    """Register a workbench *instance* (the object with Initialize/Activated)."""

def addCommand(name: str, handler: Callable[[], Any], activation: bool = False) -> Any: ...
def updateGui() -> None: ...
def export(objs: Sequence[Any], path: str) -> None: ...
def getDocument(name: str) -> GuiDocument: ...
