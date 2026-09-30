"""Tests for the command registry and the public API in :mod:`mrfreecad`.

Wiring is the part most likely to rot: a command name that exists in the menu
but not in the registry fails only when a user clicks it.  These tests make
that a build failure instead.
"""

import unittest

from tests import _bootstrap  # noqa: F401  (path setup)

import mrfreecad
from mrfreecad import commands as cmd


class RegistryTests(unittest.TestCase):
    def test_every_grouped_command_resolves(self):
        for _group, _label, names in mrfreecad.DEFAULT_COMMAND_GROUPS:
            for name in names:
                with self.subTest(command=name):
                    self.assertIsNotNone(
                        mrfreecad.get_command(name), "{0} is not registered".format(name)
                    )

    def test_every_grouped_command_is_callable(self):
        for _group, _label, names in mrfreecad.DEFAULT_COMMAND_GROUPS:
            for name in names:
                with self.subTest(command=name):
                    self.assertTrue(callable(mrfreecad.get_command(name)))

    def test_commands_resolve_through_the_cmd_resolver(self):
        for name in mrfreecad.list_commands():
            with self.subTest(command=name):
                self.assertTrue(callable(cmd.resolve(name)))

    def test_thickness_preset_commands_exist_for_every_label(self):
        from mrfreecad import normalize

        for label in normalize.PRESET_LABELS:
            name = "normalize.apply_thickness:" + label
            with self.subTest(command=name):
                self.assertTrue(callable(cmd.resolve(name)))

    def test_get_command_returns_none_for_an_unknown_name(self):
        # get_command is the non-raising lookup; resolve and run raise.
        self.assertIsNone(mrfreecad.get_command("nope.does_not_exist"))

    def test_resolve_raises_for_an_unknown_name(self):
        with self.assertRaises(KeyError):
            cmd.resolve("nope.does_not_exist")

    def test_run_rejects_unknown_names(self):
        with self.assertRaises(KeyError):
            mrfreecad.run("nope.does_not_exist")

    def test_group_ids_are_unique(self):
        ids = [group[0] for group in mrfreecad.DEFAULT_COMMAND_GROUPS]
        self.assertEqual(len(set(ids)), len(ids))

    def test_group_labels_match_the_original_tabs(self):
        # The panel tabs are generated from these, so they must stay the same
        # four names the original Windows tool used.
        labels = [group[1] for group in mrfreecad.DEFAULT_COMMAND_GROUPS]
        self.assertEqual(labels, ["Drawing", "Dxf", "Normalize", "Browse"])

    def test_no_command_is_listed_twice(self):
        names = list(mrfreecad.list_commands())
        self.assertEqual(len(set(names)), len(names))

    def test_preset_command_names_do_not_collide(self):
        labels = [name.split(":", 1)[1] for name, _handler in cmd.preset_commands()]
        self.assertEqual(len(set(labels)), len(labels))


class OperationResultTests(unittest.TestCase):
    def test_success_and_failure_constructors(self):
        ok = mrfreecad.OperationResult.success("done", "details", "Title")
        self.assertTrue(ok)
        self.assertTrue(bool(ok))
        bad = mrfreecad.OperationResult.failure("nope")
        self.assertFalse(bad)
        self.assertFalse(bool(bad))

    def test_report_contains_the_essentials(self):
        result = mrfreecad.OperationResult.success("mesaj", "detay", "Başlık")
        report = result.report()
        self.assertIn("BAŞLIK", report)
        self.assertIn("mesaj", report)
        self.assertIn("detay", report)

    def test_str_joins_message_and_details(self):
        result = mrfreecad.OperationResult(True, "T", "mesaj", "detay")
        self.assertIn("mesaj", str(result))
        self.assertIn("detay", str(result))

    def test_empty_result_is_still_reportable(self):
        self.assertIn("MRFREETOOL", mrfreecad.OperationResult().report().upper())


class PanelStateTests(unittest.TestCase):
    def setUp(self):
        self.state = cmd.PanelState()

    def test_defaults(self):
        self.assertEqual(self.state.qty, 1)
        self.assertTrue(self.state.laser)
        self.assertEqual(self.state.scale_index, 3)

    def test_sync_and_persist_round_trip(self):
        from mrfreecad.settings import get_settings

        settings = get_settings()
        saved = settings.as_dict()
        self.addCleanup(settings.apply, saved)

        self.state.qty = 7
        self.state.laser = False
        self.state.bend_lines = False
        self.state.persist()

        fresh = cmd.PanelState()
        fresh.sync_from_settings()

        self.assertEqual(fresh.qty, 7)
        self.assertFalse(fresh.laser)
        self.assertFalse(fresh.bend_lines)


class PresetCommandTests(unittest.TestCase):
    def test_unknown_label_produces_a_readable_failure(self):
        from mrfreecad import OperationResult

        result = cmd.normalize_thickness("9,9")
        self.assertIsInstance(result, OperationResult)
        self.assertFalse(result.ok)
        self.assertIn("Seçenekler", result.message)


class HeadlessCommandTests(unittest.TestCase):
    """Every command must return a failed result outside FreeCAD, not crash.

    This is a real safety property, not a formality: a command that reaches a
    dialog or a Qt widget with no application aborts the *process* from inside
    Qt, which takes the user's whole session with it.
    """

    def setUp(self):
        from mrfreecad.settings import get_settings

        self.state = cmd.panel_state()
        self._folder = self.state.folder
        self.addCleanup(setattr, self.state, "folder", self._folder)
        self.state.folder = ""

    def test_no_command_aborts_without_freecad(self):
        from mrfreecad import compat

        if compat.HAS_FREECAD:  # pragma: no cover - only inside FreeCAD
            self.skipTest("running inside FreeCAD")

        for name in mrfreecad.list_commands():
            with self.subTest(command=name):
                result = mrfreecad.run(name)
                self.assertFalse(result.ok, "{0} claimed success headlessly".format(name))
                self.assertTrue(result.message, "{0} gave no message".format(name))

    def test_reset_ref_reports_a_missing_folder_instead_of_dialoguing(self):
        from mrfreecad import compat

        if compat.HAS_FREECAD:  # pragma: no cover - only inside FreeCAD
            self.skipTest("running inside FreeCAD")
        result = mrfreecad.run("browse.reset_ref")
        self.assertFalse(result.ok)

    def test_make_pdf_reports_no_captures(self):
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            self.state.folder = tmp
            result = mrfreecad.run("browse.make_pdf")
            self.assertFalse(result.ok)
            self.assertIn("screencap", result.message + result.details)

    def test_export_dxf_reports_that_it_needs_freecad(self):
        from mrfreecad import compat

        if compat.HAS_FREECAD:  # pragma: no cover - only inside FreeCAD
            self.skipTest("running inside FreeCAD")
        result = mrfreecad.run("dxf.export_flat_dxf")
        self.assertFalse(result.ok)
        # Whatever the wording, it must name FreeCAD, since that is the actual
        # precondition the user is missing.
        self.assertIn("freecad", (result.message + result.details).lower())

    def test_failures_carry_a_traceback_in_the_details(self):
        from mrfreecad import compat

        if compat.HAS_FREECAD:  # pragma: no cover - only inside FreeCAD
            self.skipTest("running inside FreeCAD")
        result = mrfreecad.run("drawing.make_drawing")
        self.assertFalse(result.ok)
        self.assertIn("Traceback", result.details)


if __name__ == "__main__":
    unittest.main()
