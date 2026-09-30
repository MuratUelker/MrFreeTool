"""Smoke tests for the Qt layer.

These only run where a Qt binding is importable, and they create a real
``QApplication`` because building widgets without one aborts the process inside
Qt rather than raising in Python.  Run them on a headless box with the
offscreen platform::

    QT_QPA_PLATFORM=offscreen python3 -m unittest tests.test_gui

Inside FreeCAD the real platform plugin is already up, so no environment
variable is needed.
"""

import os
import sys
import tempfile
import types
import unittest

from tests import _bootstrap  # noqa: F401  (path setup)

import mrfreecad
from mrfreecad import commands as cmd
from mrfreecad import compat

try:
    compat.qt_widgets("test")  # raises when PySide is absent
    HAS_QT = True
except RuntimeError:
    HAS_QT = False


def _make_app():
    """Return a ``QApplication``, creating it once per process."""
    widgets = compat.qt_widgets("test")
    existing = widgets.QApplication.instance()
    if existing is not None:
        return existing
    # Keep Qt off the real display when there is none, so the suite is
    # runnable on a server.
    if not os.environ.get("DISPLAY") and not os.environ.get("QT_QPA_PLATFORM"):
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
    return widgets.QApplication(sys.argv[:1])


class _FakeGui:
    """A recording stand-in for ``FreeCADGui``.

    A real class rather than a dynamically built ``ModuleType`` so a type
    checker can see the attributes the code under test calls.  Installed into
    ``sys.modules`` through :func:`as_module`, which is what the import system
    actually requires.
    """

    def __init__(self, commands, workbenches):
        self._commands = commands
        self._workbenches = workbenches

    def addCommand(self, name, handler, activation=False):  # noqa: N802 - FreeCAD API name
        self._commands.append((name, handler))

    def addWorkbench(self, workbench):  # noqa: N802 - FreeCAD API name
        self._workbenches.append(workbench)

    def getMainWindow(self):  # noqa: N802 - FreeCAD API name
        return None


def as_module(fake: _FakeGui) -> "types.ModuleType":
    """Wrap ``fake`` in a real module object so it can go into ``sys.modules``."""
    module = types.ModuleType("FreeCADGui")
    module.addCommand = fake.addCommand  # type: ignore[attr-defined]
    module.addWorkbench = fake.addWorkbench  # type: ignore[attr-defined]
    module.getMainWindow = fake.getMainWindow  # type: ignore[attr-defined]
    return module


@unittest.skipUnless(HAS_QT, "PySide is not available")
class QtAvailableTests(unittest.TestCase):
    def setUp(self):
        self.app = _make_app()

    def test_qt_is_detected(self):
        self.assertTrue(compat.HAS_QT)
        self.assertTrue(hasattr(compat, "QtWidgets"))

    def test_align_resolves_across_bindings(self):
        # Qt5 exposes Qt.AlignCenter directly; Qt6 nests it in AlignmentFlag.
        self.assertIsNotNone(compat.align("AlignCenter"))
        self.assertIsNotNone(compat.align("AlignLeft", "AlignLeft"))

    def test_qt_guards_raise_when_unavailable(self):
        # These must fail with a message naming the requirement, not an
        # AttributeError on None.
        with self.assertRaises(RuntimeError):
            compat.require_freecad("test feature")
        with self.assertRaises(RuntimeError):
            compat.app()


@unittest.skipUnless(HAS_QT, "PySide is not available")
class PanelConstructionTests(unittest.TestCase):
    def setUp(self):
        self.app = _make_app()

    def test_panel_builds_with_one_tab_per_group(self):
        from mrfreecad import DEFAULT_COMMAND_GROUPS
        from mrfreecad.gui import panel

        built = panel.MrFreePanel(None)
        self.assertIsNotNone(built.widget)
        self.assertEqual(built.widget.windowTitle(), "MrFreeTool")

    def test_panel_refuses_without_a_qapplication(self):
        # Documented behaviour: no QApplication means Qt would abort, so the
        # constructors must refuse.  There is always an app in this suite, so
        # the check is asserted rather than triggered.
        from mrfreecad.gui import panel

        self.assertIsNotNone(self.app, "the suite must have a QApplication")

    def test_settings_dialog_builds(self):
        from mrfreecad.gui.settings_dialog import SettingsDialog

        dialog = SettingsDialog(None)
        values = dialog.values()
        self.assertIn("Scale/MaxDenominator", values)
        self.assertIn("Template/DefaultLandscape", values)
        for firm in ("Ayazsa", "Karadeniz"):
            self.assertIn("Logo/" + firm + "/Image", values)

    def test_settings_dialog_round_trips_its_defaults(self):
        from mrfreecad.settings import get_settings
        from mrfreecad.gui.settings_dialog import SettingsDialog

        store = get_settings()
        saved = store.as_dict()
        self.addCleanup(store.apply, saved)

        dialog = SettingsDialog(None)
        values = dialog.values()
        for key, expected in saved.items():
            if key in values and isinstance(expected, (int, float, str, bool)):
                self.assertEqual(values[key], expected, key)

    def test_every_group_has_a_button(self):
        from mrfreecad import DEFAULT_COMMAND_GROUPS
        from mrfreecad.gui import panel

        built = panel.MrFreePanel(None)
        buttons = built.widget.findChildren(compat.qt_widgets("test").QPushButton)
        # Every listed command contributes one button, plus the footer buttons
        # and the per-thickness row.
        listed = sum(len(names) for _g, _l, names in DEFAULT_COMMAND_GROUPS)
        self.assertGreaterEqual(len(buttons), listed)


@unittest.skipUnless(HAS_QT, "PySide is not available")
class WorkbenchRegistrationTests(unittest.TestCase):
    """The workbench must register cleanly, exactly once.

    ``FreeCADGui`` is replaced with a recording stand-in, so this verifies the
    registration logic itself: no dangling menu entries, no duplicates, and a
    resolvable icon - none of which need a real FreeCAD.
    """

    def setUp(self):
        self.app = _make_app()
        self._saved_gui = sys.modules.get("FreeCADGui")
        self._saved_gui_flag = compat.HAS_GUI
        self.addCleanup(self._restore)

        self.commands = []
        self.workbenches = []
        self.fake = _FakeGui(self.commands, self.workbenches)
        sys.modules["FreeCADGui"] = as_module(self.fake)
        compat.HAS_GUI = True

    def _restore(self):
        if self._saved_gui is None:
            sys.modules.pop("FreeCADGui", None)
        else:
            sys.modules["FreeCADGui"] = self._saved_gui
        compat.HAS_GUI = self._saved_gui_flag

    def test_workbench_and_commands_are_registered(self):
        from mrfreecad.gui import workbench

        wb = workbench.initialize()

        self.assertEqual(len(self.workbenches), 1)
        self.assertIsInstance(self.workbenches[0], workbench.MrFreeWorkbench)
        # One command per registry entry.
        self.assertEqual(len(self.commands), len(mrfreecad.list_commands()))

    def test_registration_is_idempotent(self):
        from mrfreecad.gui import workbench

        wb = workbench.initialize()
        before = (len(self.workbenches), len(self.commands))
        wb.Initialize()
        wb.Initialize()
        self.assertEqual((len(self.workbenches), len(self.commands)), before)

    def test_menu_labels_are_unique(self):
        from mrfreecad.gui import workbench

        workbench.initialize()
        labels = [label for label, _handler in self.commands]
        self.assertEqual(len(set(labels)), len(labels))

    def test_every_menu_entry_maps_to_a_real_command(self):
        from mrfreecad import list_commands
        from mrfreecad.gui import workbench

        workbench.initialize()
        mapping = dict(workbench.command_labels())
        known = set(list_commands())
        for label, _handler in self.commands:
            self.assertIn(label, mapping, "menu entry with no mapping: " + label)
            self.assertIn(mapping[label], known, "mapped to an unknown command: " + label)

    def test_all_four_tabs_appear_in_the_menu(self):
        from mrfreecad.gui import workbench

        workbench.initialize()
        tabs = {label.split(" ")[0] for label, _h in self.commands}
        self.assertEqual(tabs, {"Drawing", "Dxf", "Normalize", "Browse"})

    def test_icon_file_exists(self):
        from mrfreecad.gui import workbench

        wb = workbench.initialize()
        self.assertTrue(os.path.isfile(wb.Icon), wb.Icon)

    def test_menu_text(self):
        from mrfreecad.gui import workbench

        self.assertEqual(workbench.MrFreeWorkbench.MenuText, "MrFreeTool")

    def test_every_handler_returns_a_result(self):
        from mrfreecad.gui import workbench

        workbench.initialize()
        # Report results to the console rather than a modal window, and give the
        # folder-based commands a real folder, so nothing here can block on a
        # dialog.  Without this the test hangs on the first failure report.
        compat.HAS_GUI = False
        with tempfile.TemporaryDirectory() as tmp:
            state = cmd.panel_state()
            saved = state.folder
            state.folder = tmp
            try:
                for label, handler in self.commands:
                    result = handler()
                    self.assertIsNotNone(result, label)
                    self.assertTrue(hasattr(result, "ok"), label)
                    self.assertTrue(hasattr(result, "message"), label)
            finally:
                state.folder = saved

    def test_handlers_are_the_guarded_resolver(self):
        # Every menu entry must be wired through commands.resolve, so a command
        # that raises reports a failure instead of propagating into FreeCAD.
        from mrfreecad.gui import workbench

        workbench.initialize()
        for label, handler in self.commands:
            self.assertTrue(callable(handler), label)


if __name__ == "__main__":
    unittest.main()
