"""MrFreeTool settings dialog.

Same fields as the original's ``SettingsForm``, plus the logo placement that the
SolidWorks version scraped out of the sheet format file and that FreeCAD has to
have configured explicitly.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from mrfreecad import compat
from mrfreecad.settings import FIRMS, get_settings

__all__ = ["SettingsDialog", "open_settings"]


def _spin(minimum: int, maximum: int, value: int, suffix: str = ""):
    box = compat.QtWidgets.QSpinBox()
    box.setRange(int(minimum), int(maximum))
    box.setValue(int(value))
    if suffix:
        box.setSuffix(suffix)
    return box


def _line(text: str = "") -> Any:
    edit = compat.QtWidgets.QLineEdit(str(text))
    return edit


def _browse_row(label: str, edit: Any, filter: str, caption: str) -> Any:
    row = compat.QtWidgets.QHBoxLayout()
    row.addWidget(compat.QtWidgets.QLabel(label))
    row.addWidget(edit, 1)
    button = compat.QtWidgets.QPushButton("...")
    button.setFixedWidth(30)

    def browse() -> None:
        from mrfreecad.gui.dialogs import pick_file

        chosen = pick_file(caption, filter, edit.text())
        if chosen:
            edit.setText(chosen)

    button.clicked.connect(browse)
    row.addWidget(button)
    return row


def _check(text: str, checked: bool) -> Any:
    box = compat.QtWidgets.QCheckBox(text)
    box.setChecked(bool(checked))
    return box


class SettingsDialog:
    """Modal settings editor.

    Written as a factory function rather than a subclass so the module imports
    cleanly without Qt; :func:`open_settings` is the only entry point.
    """

    def __init__(self, parent: Any = None):
        compat.require_qapplication("The settings dialog")
        QtWidgets = compat.qt_widgets("The settings dialog")
        self.settings = get_settings()
        data = self.settings.as_dict()

        self.dialog = QtWidgets.QDialog(parent)
        self.dialog.setWindowTitle("MrFreeTool Ayarları")
        self.dialog.setModal(True)
        self.dialog.resize(720, 640)

        outer = QtWidgets.QVBoxLayout(self.dialog)
        tabs = QtWidgets.QTabWidget()
        outer.addWidget(tabs)

        # -- Drawing ------------------------------------------------------
        drawing_tab = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(drawing_tab)

        self.max_scale = _spin(3, 200, int(data["Scale/MaxDenominator"]))
        form.addRow("Maks. ölçek paydası (1:N)", self.max_scale)

        self.max_qty = _spin(1, 999, int(data["Drawing/MaxQty"]))
        form.addRow("Maks. adet", self.max_qty)

        self.qty = _spin(1, 999, int(data["Drawing/Qty"]))
        form.addRow("Adet", self.qty)

        self.landscape = _line(data["Template/DefaultLandscape"])
        form.addRow(_browse_row("Yatay şablon", self.landscape, "SVG (*.svg)", "TechDraw şablonu seçin (yatay)"))

        self.portrait = _line(data["Template/DefaultPortrait"])
        form.addRow(_browse_row("Dikey şablon", self.portrait, "SVG (*.svg)", "TechDraw şablonu seçin (dikey)"))

        self.ayazsa = _line(data["Template/Ayazsa"])
        form.addRow(_browse_row("Ayazsa şablonu", self.ayazsa, "SVG (*.svg)", "Ayazsa şablonu seçin"))

        self.karadeniz = _line(data["Template/Karadeniz"])
        form.addRow(_browse_row("Karadeniz şablonu", self.karadeniz, "SVG (*.svg)", "Karadeniz şablonu seçin"))

        tabs.addTab(drawing_tab, "Drawing")

        # -- Dxf ----------------------------------------------------------
        dxf_tab = QtWidgets.QWidget()
        dxf_form = QtWidgets.QFormLayout(dxf_tab)
        self.laser = _check("Lazer (Zımba değil)", bool(data["Dxf/LaserDefault"]))
        dxf_form.addRow(self.laser)
        self.bend_lines = _check("Büküm çizgileri", bool(data["Dxf/BendLinesDefault"]))
        dxf_form.addRow(self.bend_lines)
        self.rotation = _check("%R (döndürülmüş)", bool(data["Dxf/Rotation"]))
        dxf_form.addRow(self.rotation)
        self.simetri = _check("Simetriği de var", bool(data["Dxf/Simetri"]))
        dxf_form.addRow(self.simetri)
        self.dxf_dir = _line(data["Dxf/OutputDir"])
        dxf_form.addRow(_browse_row("Çıktı klasörü", self.dxf_dir, "Klasör", "DXF çıktı klasörü seçin"))
        tabs.addTab(dxf_tab, "Dxf")

        # -- Capture ------------------------------------------------------
        capture_tab = QtWidgets.QWidget()
        capture_form = QtWidgets.QFormLayout(capture_tab)
        self.paper_w = _spin(100, 2000, int(data["Capture/PaperWidthMm"]), " mm")
        capture_form.addRow("Kağıt genişliği", self.paper_w)
        self.paper_h = _spin(100, 2000, int(data["Capture/PaperHeightMm"]), " mm")
        capture_form.addRow("Kağıt yüksekliği", self.paper_h)
        self.dpi = _spin(72, 1200, int(data["Capture/Dpi"]), " dpi")
        capture_form.addRow("Çözünürlük", self.dpi)
        self.trim = _check("İçeriğe göre kırp", bool(data["Capture/TrimToContent"]))
        capture_form.addRow(self.trim)
        self.fit = _spin(50, 100, int(float(data["Capture/FitFraction"]) * 100), " %")
        capture_form.addRow("Doldurma oranı", self.fit)
        self.prefix = _line(data["Capture/Prefix"])
        capture_form.addRow("Dosya ön eki", self.prefix)
        self.pdf_name = _line(data["Pdf/FileName"])
        capture_form.addRow("PDF dosya adı", self.pdf_name)
        tabs.addTab(capture_tab, "Capture")

        # -- Normalize ----------------------------------------------------
        norm_tab = QtWidgets.QWidget()
        norm_form = QtWidgets.QFormLayout(norm_tab)
        self.kfactor = _spin(1, 900, int(float(data["Normalize/KFactor"]) * 1000), " /1000")
        norm_form.addRow("K-Factor", self.kfactor)
        self.relief = _check("Otomatik delme (Tear)", bool(data["Normalize/AutoReliefTear"]))
        norm_form.addRow(self.relief)
        self.scene = _line(data["Normalize/Scene"])
        norm_form.addRow(_browse_row("Arka plan görseli", self.scene, "Görsel (*.png *.jpg)", "Arka plan seçin"))
        tabs.addTab(norm_tab, "Normalize")

        # -- Logo ---------------------------------------------------------
        logo_tab = QtWidgets.QWidget()
        logo_layout = QtWidgets.QVBoxLayout(logo_tab)
        logo_layout.addWidget(
            compat.QtWidgets.QLabel(
                "Logo konumu, kağıt üzerinde milimetre cinsindendir.\n"
                "Sol-alt köşe (0,0) referans alınır; yukarı doğru artar."
            )
        )
        self.logo_widgets: Dict[str, Dict[str, Any]] = {}
        for firm in FIRMS:
            slot = self.settings.logo(firm)
            group = compat.QtWidgets.QGroupBox(firm)
            grid = compat.QtWidgets.QFormLayout(group)
            image = _line(slot.image)
            grid.addRow(_browse_row("Görsel", image, "Görsel (*.png *.jpg *.bmp)", firm + " logosu seçin"))
            x = _spin(-2000, 2000, int(slot.x), " mm")
            y = _spin(-2000, 2000, int(slot.y), " mm")
            w = _spin(1, 2000, int(slot.w), " mm")
            h = _spin(1, 2000, int(slot.h), " mm")
            pad_x = _spin(0, 50, int(slot.clear_pad_x * 10), " /10 mm")
            pad_y = _spin(0, 50, int(slot.clear_pad_y * 10), " /10 mm")
            grid.addRow("X", x)
            grid.addRow("Y", y)
            grid.addRow("Genişlik", w)
            grid.addRow("Yükseklik", h)
            grid.addRow("Temizleme (yatay)", pad_x)
            grid.addRow("Temizleme (dikey)", pad_y)
            self.logo_widgets[firm] = {
                "image": image,
                "x": x,
                "y": y,
                "w": w,
                "h": h,
                "pad_x": pad_x,
                "pad_y": pad_y,
            }
            logo_layout.addWidget(group)
        logo_layout.addStretch(1)
        tabs.addTab(logo_tab, "Logo")

        # -- Buttons ------------------------------------------------------
        buttons = QtWidgets.QDialogButtonBox()
        ok = buttons.addButton("Kaydet", QtWidgets.QDialogButtonBox.AcceptRole)
        cancel = buttons.addButton("İptal", QtWidgets.QDialogButtonBox.RejectRole)
        outer.addWidget(buttons)
        ok.clicked.connect(self.dialog.accept)
        cancel.clicked.connect(self.dialog.reject)

    def values(self) -> Dict[str, Any]:
        """Collect the form into the settings dictionary shape."""
        data = self.settings.as_dict()
        data["Scale/MaxDenominator"] = self.max_scale.value()
        data["Drawing/MaxQty"] = self.max_qty.value()
        data["Drawing/Qty"] = self.qty.value()
        data["Template/DefaultLandscape"] = self.landscape.text().strip()
        data["Template/DefaultPortrait"] = self.portrait.text().strip()
        data["Template/Ayazsa"] = self.ayazsa.text().strip()
        data["Template/Karadeniz"] = self.karadeniz.text().strip()
        data["Dxf/LaserDefault"] = self.laser.isChecked()
        data["Dxf/BendLinesDefault"] = self.bend_lines.isChecked()
        data["Dxf/Rotation"] = self.rotation.isChecked()
        data["Dxf/Simetri"] = self.simetri.isChecked()
        data["Dxf/OutputDir"] = self.dxf_dir.text().strip()
        data["Capture/PaperWidthMm"] = self.paper_w.value()
        data["Capture/PaperHeightMm"] = self.paper_h.value()
        data["Capture/Dpi"] = self.dpi.value()
        data["Capture/TrimToContent"] = self.trim.isChecked()
        data["Capture/FitFraction"] = self.fit.value() / 100.0
        data["Capture/Prefix"] = self.prefix.text().strip()
        data["Pdf/FileName"] = self.pdf_name.text().strip()
        data["Normalize/KFactor"] = self.kfactor.value() / 1000.0
        data["Normalize/AutoReliefTear"] = self.relief.isChecked()
        data["Normalize/Scene"] = self.scene.text().strip()
        for firm, widgets in self.logo_widgets.items():
            prefix = "Logo/" + firm + "/"
            data[prefix + "Image"] = widgets["image"].text().strip()
            data[prefix + "X"] = widgets["x"].value()
            data[prefix + "Y"] = widgets["y"].value()
            data[prefix + "W"] = widgets["w"].value()
            data[prefix + "H"] = widgets["h"].value()
            data[prefix + "PadX"] = widgets["pad_x"].value() / 10.0
            data[prefix + "PadY"] = widgets["pad_y"].value() / 10.0
        return data

    def exec(self) -> int:
        """Show the dialog; returns Qt's Accepted/Rejected code."""
        return compat.exec_dialog(self.dialog)


def open_settings() -> bool:
    """Open the settings dialog and persist on OK.  Returns True when saved."""
    if not compat.HAS_GUI:
        compat.console_log("Ayarlar penceresi için FreeCAD GUI gerekir.")
        return False
    dialog = SettingsDialog(compat.get_main_window())
    accepted = dialog.exec()
    if accepted == int(compat.qt_widgets("The settings dialog").QDialog.Accepted):
        get_settings().apply(dialog.values())
        get_settings().flush()
        return True
    return False
