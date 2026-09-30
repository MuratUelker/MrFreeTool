"""Qt dialogs: the scrollable report window and file pickers.

The original showed long reports in a modal window with a scrollbar rather than
a ``MessageBox``, because a reference-repair report can easily exceed the screen
height.  Same reason here.
"""

from __future__ import annotations

import os
from typing import Optional

from mrfreecad import compat

__all__ = ["show_report", "show_text", "pick_folder", "pick_file", "ask_yes_no"]


def show_report(result) -> None:
    """Display an :class:`~mrfreecad.OperationResult` in a scrollable window."""
    if not compat.HAS_QT:
        compat.console_log(result.report())
        return
    show_text(result.title, result.report())


def show_text(title: str, text: str) -> None:
    """Modal, scrollable, read-only text window with a close button."""
    if not compat.HAS_QT:
        compat.console_log(text)
        return
    if compat.qt_widgets("Report window").QApplication.instance() is None:
        # No QApplication means Qt would abort the process, not raise.
        compat.console_log(text)
        return

    QtCore = compat.qt_core("Report window")
    QtGui = compat.qt_gui("Report window")
    QtWidgets = compat.qt_widgets("Report window")

    dialog = QtWidgets.QDialog()
    dialog.setWindowTitle(str(title))
    dialog.resize(760, 560)
    parent = compat.get_main_window()
    if parent is not None:
        dialog.setParent(parent, QtCore.Qt.Window)

    layout = QtWidgets.QVBoxLayout(dialog)

    text_edit = QtWidgets.QPlainTextEdit()
    text_edit.setReadOnly(True)
    text_edit.setPlainText(str(text))
    text_edit.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
    font = QtGui.QFont("Monospace")
    font.setStyleHint(QtGui.QFont.TypeWriter)
    text_edit.setFont(font)
    text_edit.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse | QtCore.Qt.TextSelectableByKeyboard)
    layout.addWidget(text_edit)

    buttons = QtWidgets.QDialogButtonBox()
    copy = buttons.addButton("Kopyala", QtWidgets.QDialogButtonBox.ActionRole)
    close = buttons.addButton("Kapat", QtWidgets.QDialogButtonBox.AcceptRole)
    layout.addWidget(buttons)

    def do_copy() -> None:
        clipboard = QtWidgets.QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(str(text))

    copy.clicked.connect(do_copy)
    close.clicked.connect(dialog.accept)
    compat.exec_dialog(dialog)


def pick_folder(title: str, start: str = "") -> str:
    """Folder chooser; returns ``""`` when cancelled."""
    if not compat.HAS_QT:
        return ""
    dialogs = compat.qt_widgets("Folder chooser")
    parent = compat.get_main_window()
    if start and not os.path.isdir(start):
        start = ""
    folder = dialogs.QFileDialog.getExistingDirectory(parent, title, start or "")
    return folder or ""


def pick_file(title: str, patterns: str = "Tüm dosyalar (*.*)", start: str = "") -> str:
    """File chooser; returns ``""`` when cancelled."""
    if not compat.HAS_QT:
        return ""
    dialogs = compat.qt_widgets("File chooser")
    parent = compat.get_main_window()
    if start and not os.path.isfile(start):
        start = os.path.dirname(start) if start else ""
    selected, _filter = dialogs.QFileDialog.getOpenFileName(parent, title, start or "", patterns)
    return selected or ""


def ask_yes_no(title: str, text: str, default_no: bool = True) -> bool:
    """Yes/no question.  Defaults to *No* so a stray Enter is not destructive."""
    if not compat.HAS_GUI:
        return False
    boxes = compat.qt_widgets("Message box")
    parent = compat.get_main_window()
    buttons = boxes.QMessageBox.Yes | boxes.QMessageBox.No
    default = boxes.QMessageBox.No if default_no else boxes.QMessageBox.Yes
    box = boxes.QMessageBox(boxes.QMessageBox.Question, title, text, buttons, default)
    if parent is not None:
        box.setParent(parent)
    return compat.exec_dialog(box) == int(boxes.QMessageBox.Yes)
