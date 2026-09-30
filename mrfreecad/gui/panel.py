"""The MrFreeTool panel - one tab per tab of the original Windows tool.

Built from :data:`mrfreecad.DEFAULT_COMMAND_GROUPS` so the menu, the toolbar
and this panel can never disagree about what exists.  Each tab is generated
from its command list, with the handful of controls the original's tabs shared
(Qty, Laser/Punch, "simetriği de var", bend lines, the scale slider) added
above the buttons.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

from mrfreecad import DEFAULT_COMMAND_GROUPS, compat
from mrfreecad import commands as cmd

__all__ = ["MrFreePanel", "open_panel", "toggle_panel"]

#: Extra controls shown per tab, as ``(attribute, label, kind)``.
#: ``kind`` is one of ``qty``, ``scale``, ``radio``, ``check`` or ``folder``.
_TAB_CONTROLS: Dict[str, List[Tuple[str, str, str]]] = {
    "drawing": [("qty", "Adet", "qty"), ("scale_index", "Ölçek", "scale")],
    # The radio buttons carry their own labels, so no row label is given.
    "dxf": [
        ("qty", "Adet", "qty"),
        ("laser", "", "radio"),
        ("simetri", "Simetriği de var", "check"),
        ("bend_lines", "Büküm çizgileri", "check"),
        ("rotation", "%R (döndürülmüş)", "check"),
    ],
    "normalize": [],
    "browse": [("folder", "Klasör", "folder")],
}


def _fmt_num(value: float) -> str:
    """Format a number the way the settings and reports do."""
    from mrfreecad.naming import to_decimal

    return to_decimal(value, 4)


class MrFreePanel:
    """The workbench panel.  Construct via :func:`open_panel`."""

    def __init__(self, parent: Any = None):
        # Constructing widgets without a QApplication aborts inside Qt, so the
        # precondition is checked here as well as in open_panel().
        compat.require_qapplication("The MrFreeTool panel")
        QtWidgets = compat.qt_widgets("The MrFreeTool panel")

        self.state = cmd.panel_state()
        self.state.sync_from_settings()

        self.widget = QtWidgets.QWidget(parent)
        self.widget.setWindowTitle("MrFreeTool")
        self.widget.setWindowFlags(compat.qt_core("MrFreeTool panel").Qt.Tool)
        self.widget.setAttribute(
            compat.qt_core("MrFreeTool panel").Qt.WA_DeleteOnClose, False
        )

        layout = QtWidgets.QVBoxLayout(self.widget)
        layout.setContentsMargins(6, 6, 6, 6)

        tabs = QtWidgets.QTabWidget()
        layout.addWidget(tabs)

        self.controls: Dict[str, Any] = {}

        for group_id, group_label, command_names in DEFAULT_COMMAND_GROUPS:
            tab = QtWidgets.QWidget()
            tab_layout = QtWidgets.QVBoxLayout(tab)
            tab_layout.setSpacing(4)

            for attribute, label, kind in _TAB_CONTROLS.get(group_id, []):
                control = self._make_control(attribute, label, kind)
                self.controls[attribute] = control
                if kind in ("check", "radio"):
                    # Self-labelling: lay the control straight into the tab.
                    tab_layout.addWidget(control)
                    continue
                row = QtWidgets.QHBoxLayout()
                row.addWidget(QtWidgets.QLabel(label))
                row.addWidget(control, 1)
                tab_layout.addLayout(row)

            grid = QtWidgets.QGridLayout()
            grid.setSpacing(4)
            for row_index, name in enumerate(command_names):
                button = QtWidgets.QPushButton(cmd.command_label(name))
                button.setToolTip(name)
                button.clicked.connect(self._make_runner(name))
                grid.addWidget(button, row_index // 4, row_index % 4)
            tab_layout.addLayout(grid)

            if group_id == "normalize":
                self._add_thickness_row(tab_layout)
            if group_id == "browse":
                self._add_firm_row(tab_layout)

            tab_layout.addStretch(1)
            tabs.addTab(tab, group_label)

        footer = QtWidgets.QHBoxLayout()
        self.status = QtWidgets.QLabel("Hazır")
        footer.addWidget(self.status, 1)
        settings_button = QtWidgets.QPushButton("⚙")
        settings_button.setFixedWidth(34)
        settings_button.setToolTip("Ayarlar")
        settings_button.clicked.connect(self._open_settings)
        footer.addWidget(settings_button)
        close_button = QtWidgets.QPushButton("✕")
        close_button.setFixedWidth(34)
        close_button.setToolTip("Kapat")
        close_button.clicked.connect(self.hide)
        footer.addWidget(close_button)
        layout.addLayout(footer)

    # -- controls ---------------------------------------------------------
    def _make_control(self, attribute: str, label: str, kind: str) -> Any:
        from mrfreecad import drawing as drawing_mod
        from mrfreecad.settings import get_settings

        QtWidgets = compat.qt_widgets("MrFreeTool panel")
        QtCore = compat.qt_core("MrFreeTool panel")
        settings = get_settings()

        if kind == "qty":
            box = QtWidgets.QSpinBox()
            box.setRange(1, settings.max_qty())
            box.setValue(self.state.qty)
            box.valueChanged.connect(lambda value: self._set_qty(value))
            return box

        if kind == "scale":
            ladder = drawing_mod.scale_ladder(settings.max_scale_denominator())
            box = QtWidgets.QSlider(QtCore.Qt.Horizontal)
            box.setMinimum(1)
            box.setMaximum(len(ladder))
            box.setValue(min(self.state.scale_index, len(ladder)))
            box.valueChanged.connect(lambda value: self._set_scale(value))
            return box

        if kind == "radio":
            holder = QtWidgets.QWidget()
            row = QtWidgets.QHBoxLayout(holder)
            row.setContentsMargins(0, 0, 0, 0)
            laser = QtWidgets.QRadioButton("Lazer")
            punch = QtWidgets.QRadioButton("Zımba")
            laser.setChecked(self.state.laser)
            punch.setChecked(not self.state.laser)
            laser.toggled.connect(lambda checked: self._set_flag(attribute, checked))
            row.addWidget(laser)
            row.addWidget(punch)
            return holder

        if kind == "check":
            box = QtWidgets.QCheckBox(label)
            box.setChecked(bool(getattr(self.state, attribute)))
            box.toggled.connect(lambda checked, name=attribute: self._set_flag(name, checked))
            return box

        if kind == "folder":
            holder = QtWidgets.QWidget()
            inner = QtWidgets.QHBoxLayout(holder)
            inner.setContentsMargins(0, 0, 0, 0)
            edit = QtWidgets.QLineEdit(self.state.folder)
            edit.setPlaceholderText("(aktif dokümanın klasörü)")
            edit.textChanged.connect(lambda text: self._set_folder(text))
            button = QtWidgets.QPushButton("...")
            button.setFixedWidth(30)
            button.clicked.connect(self._pick_folder)
            inner.addWidget(edit, 1)
            inner.addWidget(button)
            return holder

        raise ValueError("unknown control kind: " + kind)

    def _add_thickness_row(self, layout: Any) -> None:
        """The thickness preset buttons, laid out like the original row."""
        from mrfreecad import normalize

        QtWidgets = compat.qt_widgets("MrFreeTool panel")
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Kalınlık"))
        for label in normalize.PRESET_LABELS:
            button = QtWidgets.QPushButton(label)
            button.setFixedWidth(48)
            button.setToolTip(
                "{0} mm uygula (K-Factor {1}, büküm yarıçapı {2} mm)".format(
                    label.replace(",", "."),
                    _fmt_num(preset[2]) if (preset := normalize.preset_for_label(label)) else "?",
                    _fmt_num(preset[3]) if preset else "?",
                )
            )
            button.clicked.connect(self._make_runner("normalize.apply_thickness:" + label))
            row.addWidget(button)
        # No "read thickness" button here: the command is already a button in
        # the grid above, so a second copy here would be a duplicate.
        row.addStretch(1)
        layout.addLayout(row)

    def _add_firm_row(self, layout: Any) -> None:
        from mrfreecad.settings import FIRMS

        QtWidgets = compat.qt_widgets("MrFreeTool panel")
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Firma"))
        combo = QtWidgets.QComboBox()
        combo.addItems(list(FIRMS))
        if self.state.firm in FIRMS:
            combo.setCurrentText(self.state.firm)
        combo.currentTextChanged.connect(lambda text: self._set_firm(text))
        row.addWidget(combo, 1)
        self.controls["firm"] = combo
        layout.addLayout(row)

    # -- state plumbing ---------------------------------------------------
    def _set_qty(self, value: int) -> None:
        self.state.qty = int(value)
        self.state.persist()

    def _set_scale(self, value: int) -> None:
        from mrfreecad import drawing as drawing_mod

        self.state.scale_index = int(value)
        self.status.setText("Ölçek: " + drawing_mod.format_scale(drawing_mod.scale_for_index(int(value))))

    def _set_flag(self, name: str, value: bool) -> None:
        setattr(self.state, name, bool(value))
        self.state.persist()

    def _set_folder(self, text: str) -> None:
        self.state.folder = text.strip()

    def _set_firm(self, text: str) -> None:
        self.state.firm = text

    def _pick_folder(self) -> None:
        from mrfreecad.gui.dialogs import pick_folder

        chosen = pick_folder("Klasör seçin", self.state.folder)
        if not chosen:
            return
        self.state.folder = chosen
        holder = self.controls.get("folder")
        if holder is not None and hasattr(holder, "findChild"):
            target = holder.findChild(compat.qt_widgets("MrFreeTool panel").QLineEdit)
            if target is not None:
                target.setText(chosen)

    def _open_settings(self) -> None:
        from mrfreecad.gui.settings_dialog import open_settings

        if open_settings():
            self.status.setText("Ayarlar kaydedildi.")

    def _make_runner(self, name: str) -> Callable[[], None]:
        def run() -> None:
            try:
                handler = cmd.resolve(name)
            except KeyError as exc:
                cmd.show_result(_error_result(str(exc), name))
                return
            QtCore = compat.qt_core("MrFreeTool panel")
            self.widget.setCursor(QtCore.Qt.WaitCursor)
            try:
                result = handler()
            finally:
                self.widget.setCursor(QtCore.Qt.ArrowCursor)
            if result is not None:
                self.status.setText(result.message.splitlines()[0] if result.message else "")

        return run

    # -- lifecycle --------------------------------------------------------
    def show(self) -> None:
        self.widget.show()
        self.widget.raise_()

    def hide(self) -> None:
        self.widget.hide()

    def is_visible(self) -> bool:
        return bool(self.widget.isVisible())

    def reconfigure(self) -> None:
        """Rebuild controls after a settings change (scale ladder, Qty limit)."""
        from mrfreecad.settings import get_settings

        settings = get_settings()
        qty = self.controls.get("qty")
        if qty is not None:
            qty.setMaximum(settings.max_qty())


def _error_result(message: str, name: str):
    from mrfreecad import OperationResult

    return OperationResult.failure(message, title=name)


_PANEL: Optional[MrFreePanel] = None


def open_panel(parent: Any = None) -> MrFreePanel:
    """Create (or return) the shared panel and show it.

    Refuses to run without the FreeCAD GUI.  This is not paranoia: building a
    ``QWidget`` with no ``QApplication`` aborts the *process* from inside Qt,
    which no Python ``try`` can intercept, so the check has to happen first.
    """
    compat.require_qapplication("The MrFreeTool panel")

    global _PANEL
    if _PANEL is None:
        _PANEL = MrFreePanel(parent if parent is not None else compat.get_main_window())
    _PANEL.show()
    return _PANEL


def get_panel() -> Optional[MrFreePanel]:
    """The panel, if one exists yet."""
    return _PANEL


def toggle_panel() -> None:
    """Show the panel if hidden, hide it if shown."""
    panel = get_panel()
    if panel is None:
        open_panel()
    elif panel.is_visible():
        panel.hide()
    else:
        panel.show()
