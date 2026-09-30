"""Tests for :mod:`mrfreecad.refrepair` - external link repair.

Real ``.FCStd`` files are zip archives containing ``Document.xml``, so the tests
build genuine minimal archives rather than mocking the reader.  That means the
extraction, the rewrite and the atomicity guarantee are all exercised for real.
"""

import os
import shutil
import tempfile
import unittest
import zipfile

from tests import _bootstrap  # noqa: F401  (path setup)

from mrfreecad import refrepair


DOCUMENT_TEMPLATE = """<?xml version="1.0" encoding="utf-8"?>
<Document SchemaVersion="4" ProgramVersion="1.0">
  <Properties>
    <Property name="Label" type="App::PropertyString"><String value="{label}"/></Property>
  </Properties>
  <Objects Count="{count}">
{objects}  </Objects>
</Document>
"""

LINK_OBJECT = """    <Object name="Link{index}" type="App::FeaturePython">
      <Properties>
        <Property name="LinkedObject" type="App::PropertyXLink">
          <XLink file="{path}"/>
        </Property>
      </Properties>
    </Object>
"""


def write_fcstd(path, label="Part", links=(), extra_files=()):
    """Create a minimal but genuine ``.FCStd`` archive.

    ``links`` is a sequence of external file paths recorded as XLinks.
    """
    objects = "".join(
        LINK_OBJECT.format(index=index, path=target) for index, target in enumerate(links)
    )
    document = DOCUMENT_TEMPLATE.format(label=label, count=len(links), objects=objects)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("Document.xml", document)
        archive.writestr("GuiDocument.xml", "<Document/>")
        for name, payload in extra_files:
            archive.writestr(name, payload)
    return path


class ReadReferencesTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        self.addCleanup(self._tmp.cleanup)

    def test_extracts_the_link_table(self):
        part = write_fcstd(os.path.join(self.root, "a.FCStd"), links=["/proj/Bracket.FCStd"])
        self.assertEqual(refrepair.read_references(part), ["/proj/Bracket.FCStd"])

    def test_several_links_keep_their_order(self):
        part = write_fcstd(
            os.path.join(self.root, "a.FCStd"),
            links=["/p/One.FCStd", "/p/Two.FCStd", "/p/Three.FCStd"],
        )
        self.assertEqual(
            refrepair.read_references(part),
            ["/p/One.FCStd", "/p/Two.FCStd", "/p/Three.FCStd"],
        )

    def test_duplicate_links_are_reported_once(self):
        part = write_fcstd(
            os.path.join(self.root, "a.FCStd"), links=["/p/One.FCStd", "/p/One.FCStd"]
        )
        self.assertEqual(refrepair.read_references(part), ["/p/One.FCStd"])

    def test_self_reference_is_ignored(self):
        part = write_fcstd(os.path.join(self.root, "a.FCStd"), links=[os.path.join(self.root, "a.FCStd")])
        self.assertEqual(refrepair.read_references(part), [])

    def test_windows_backslashes_are_normalised(self):
        part = write_fcstd(os.path.join(self.root, "a.FCStd"), links=["C:\\proj\\Bracket.FCStd"])
        self.assertEqual(refrepair.read_references(part), ["C:/proj/Bracket.FCStd"])

    def test_no_links_yields_empty(self):
        part = write_fcstd(os.path.join(self.root, "a.FCStd"))
        self.assertEqual(refrepair.read_references(part), [])

    def test_a_non_archive_returns_empty_instead_of_raising(self):
        bogus = os.path.join(self.root, "bogus.FCStd")
        with open(bogus, "wb") as handle:
            handle.write(b"this is not a zip")
        self.assertEqual(refrepair.read_references(bogus), [])

    def test_a_missing_file_returns_empty(self):
        self.assertEqual(refrepair.read_references(os.path.join(self.root, "nope.FCStd")), [])


class RepairProjectTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        self.addCleanup(self._tmp.cleanup)

        # The project: an assembly pointing at a stale absolute path, and the
        # real part sitting in the project folder.
        self.part = write_fcstd(os.path.join(self.root, "Bracket.FCStd"), label="Bracket")
        stale = os.path.join(self.root, "old", "Bracket.FCStd")
        self.assembly = write_fcstd(os.path.join(self.root, "Asm.FCStd"), links=[stale])

    def test_stale_reference_is_repointed(self):
        changed, report = refrepair.repair_project(self.root)
        self.assertTrue(changed)
        self.assertIn(os.path.join(self.root, "Bracket.FCStd"), refrepair.read_references(self.assembly))

    def test_the_model_stays_a_valid_archive(self):
        refrepair.repair_project(self.root)
        with zipfile.ZipFile(self.assembly) as archive:
            names = archive.namelist()
            self.assertIn("Document.xml", names)
            self.assertIn("GuiDocument.xml", names)
        # The untouched part must not have been modified.
        self.assertEqual(refrepair.read_references(self.part), [])

    def test_already_correct_reference_is_left_alone(self):
        # Uses its own folder: setUp deliberately creates a *broken* assembly,
        # so the "nothing to do" case has to be tested in isolation.
        clean = os.path.join(self.root, "clean")
        part = write_fcstd(os.path.join(clean, "B.FCStd"), label="B")
        asm = write_fcstd(os.path.join(clean, "C.FCStd"), links=[part])
        before = os.path.getmtime(asm)

        changed, _report = refrepair.repair_project(clean)

        self.assertFalse(changed, "a correct reference table needs no rewrite")
        self.assertEqual(os.path.getmtime(asm), before, "the file must not be touched")
        self.assertEqual(refrepair.read_references(asm), [part])

    def test_unresolvable_reference_is_reported_not_deleted(self):
        asm = write_fcstd(
            os.path.join(self.root, "D.FCStd"), links=["/elsewhere/Missing.FCStd"]
        )
        _changed, report = refrepair.repair_project(self.root)
        self.assertIn("Missing.FCStd", report)
        # Crucially the link survives: deleting it would lose placement work.
        self.assertIn("/elsewhere/Missing.FCStd", refrepair.read_references(asm))

    def test_no_temp_files_are_left_behind(self):
        refrepair.repair_project(self.root)
        leftovers = [n for n in os.listdir(self.root) if n.endswith(".mrfree.tmp")]
        self.assertEqual(leftovers, [])

    def test_nfd_names_are_normalised_first(self):
        import unicodedata

        nfd = unicodedata.normalize("NFD", "Açılım")
        part = write_fcstd(os.path.join(self.root, nfd, "Parça.FCStd"), label="Parça")
        asm = write_fcstd(os.path.join(self.root, "Asm2.FCStd"), links=[part])
        _changed, report = refrepair.repair_project(self.root)
        self.assertIn("NFD->NFC", report)
        self.assertTrue(
            os.path.isfile(os.path.join(self.root, unicodedata.normalize("NFC", "Açılım"), "Parça.FCStd"))
        )
        # After normalisation the link path must resolve to the real file.
        rewritten = refrepair.read_references(asm)
        self.assertTrue(rewritten)
        self.assertTrue(os.path.isfile(rewritten[0]))

    def test_missing_folder_is_reported(self):
        changed, report = refrepair.repair_project(os.path.join(self.root, "nope"))
        self.assertFalse(changed)
        self.assertIn("Klasör bulunamadı", report)

    def test_folder_without_models(self):
        empty = os.path.join(self.root, "empty")
        os.makedirs(empty)
        changed, report = refrepair.repair_project(empty)
        self.assertFalse(changed)
        self.assertIn("bulunamadı", report)

    def test_report_names_the_project(self):
        _changed, report = refrepair.repair_project(self.root)
        self.assertIn(self.root, report)

    def test_repair_is_idempotent(self):
        first, _r1 = refrepair.repair_project(self.root)
        second, _r2 = refrepair.repair_project(self.root)
        self.assertTrue(first)
        self.assertFalse(second, "a second run must find nothing left to do")

    def test_diacritic_mismatch_still_matches(self):
        # The recorded path is ASCII-mangled, the file on disk is not.
        part = write_fcstd(os.path.join(self.root, "Açılım.FCStd"), label="A")
        asm = write_fcstd(os.path.join(self.root, "Asm3.FCStd"), links=["/wrong/Acilim.FCStd"])
        refrepair.repair_project(self.root)
        rewritten = refrepair.read_references(asm)
        self.assertEqual(len(rewritten), 1)
        self.assertTrue(os.path.isfile(rewritten[0]))


class BackupTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        self.addCleanup(self._tmp.cleanup)

    def test_backup_copies_the_tree(self):
        source = os.path.join(self.root, "proj")
        write_fcstd(os.path.join(source, "A.FCStd"))
        destination = refrepair.backup_project(source)
        self.assertTrue(os.path.isdir(destination))
        self.assertTrue(os.path.isfile(os.path.join(destination, "A.FCStd")))

    def test_backup_of_a_missing_folder_is_empty(self):
        self.assertEqual(refrepair.backup_project(os.path.join(self.root, "nope")), "")


class XLinkPatternTests(unittest.TestCase):
    def test_matches_plain_and_escaped_paths(self):
        self.assertEqual(
            refrepair.XLinkPattern.findall('x file="C:/a.FCStd" y file="D:\\b.FCStd"'),
            ["C:/a.FCStd", "D:\\b.FCStd"],
        )

    def test_tolerates_spacing(self):
        self.assertEqual(refrepair.XLinkPattern.findall('file = "a.FCStd"'), ["a.FCStd"])


if __name__ == "__main__":
    unittest.main()
