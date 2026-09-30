"""Tests for :mod:`mrfreecad.naming`.

These cover the file-name handling that caused the most production trouble in
the original tool: Unicode normalisation and diacritic folding, plus the DXF
file-name layout the shop reads by eye.
"""

import os
import tempfile
import unittest
import unicodedata

from tests import _bootstrap  # noqa: F401  (path setup)

from mrfreecad import naming


class NormalizeNameTests(unittest.TestCase):
    def test_turkish_letters_fold_to_ascii(self):
        for text, expected in (
            ("Zımba", "zimba"),
            ("Lazer", "lazer"),
            ("Yan Sac", "yan sac"),
            ("AÇILIM", "aciliм".replace("м", "m")),
            ("Şasi", "sasi"),
            ("Çatı", "cati"),
        ):
            with self.subTest(text=text):
                self.assertEqual(naming.normalize_name(text), expected)

    def test_nfd_and_nfc_forms_compare_equal(self):
        composed = unicodedata.normalize("NFC", "Açılım")
        decomposed = unicodedata.normalize("NFD", "Açılım")
        self.assertNotEqual(composed, decomposed)
        self.assertEqual(naming.normalize_name(composed), naming.normalize_name(decomposed))

    def test_ascii_preserved_and_lowercased(self):
        self.assertEqual(naming.normalize_name("Bracket-01"), "bracket-01")

    def test_empty_input(self):
        self.assertEqual(naming.normalize_name(""), "")
        self.assertEqual(naming.normalize_name(None), "")


class NfcTests(unittest.TestCase):
    def test_is_nfd_detects_decomposed(self):
        self.assertFalse(naming.is_nfd(unicodedata.normalize("NFC", "Açılım")))
        self.assertTrue(naming.is_nfd(unicodedata.normalize("NFD", "Açılım")))

    def test_to_nfc_is_idempotent(self):
        once = naming.to_nfc(unicodedata.normalize("NFD", "Şasi Çatı"))
        self.assertEqual(once, naming.to_nfc(once))


class NormalizeNamesDeepTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        self.addCleanup(self._tmp.cleanup)

    def _write(self, relative, content=b"x"):
        path = os.path.join(self.root, relative)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(content)
        return path

    def test_renames_decomposed_files_and_folders(self):
        nfd_dir = unicodedata.normalize("NFD", "Açılım")
        nfc_dir = unicodedata.normalize("NFC", "Açılım")
        nfd_file = unicodedata.normalize("NFD", "Parça.FCStd")
        nfc_file = unicodedata.normalize("NFC", "Parça.FCStd")

        self._write(os.path.join(nfd_dir, nfd_file))

        log = []
        renamed = naming.normalize_names_deep(self.root, log)

        self.assertEqual(renamed, 2)
        self.assertTrue(os.path.isfile(os.path.join(self.root, nfc_dir, nfc_file)))
        self.assertEqual(len(log), 2)

    def test_already_nfc_tree_is_untouched(self):
        self._write("Parça.FCStd")
        self.assertEqual(naming.normalize_names_deep(self.root), 0)
        self.assertTrue(os.path.isfile(os.path.join(self.root, "Parça.FCStd")))

    def test_missing_root_returns_zero(self):
        self.assertEqual(naming.normalize_names_deep(os.path.join(self.root, "nope")), 0)

    def test_resolve_nfc_path_finds_decomposed_tree(self):
        nfd_dir = unicodedata.normalize("NFD", "Açılım")
        target = self._write(os.path.join(nfd_dir, "Parça.FCStd"))
        nfc_query = os.path.join(self.root, unicodedata.normalize("NFC", "Açılım"), "Parça.FCStd")

        # The NFC path does not exist verbatim; the resolver must still find it.
        self.assertFalse(os.path.exists(nfc_query))
        self.assertEqual(os.path.realpath(naming.resolve_nfc_path(nfc_query)), os.path.realpath(target))


class IndexProjectTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        self.addCleanup(self._tmp.cleanup)

    def _touch(self, relative):
        path = os.path.join(self.root, relative)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "wb").close()
        return path

    def test_index_is_recursive_and_normalized(self):
        self._touch(os.path.join("a", "Yan Sac.FCStd"))
        self._touch(os.path.join("b", "c", "Köşe.FCStd"))
        self._touch(os.path.join("b", "c", "ignored.DXF"))

        index = naming.index_project(self.root, (".fcstd",))

        self.assertIn(naming.normalize_name("Yan Sac.FCStd"), index)
        self.assertIn(naming.normalize_name("Köşe.FCStd"), index)
        # Only the requested extension is indexed.
        self.assertNotIn(naming.normalize_name("ignored.FCStd"), index)
        self.assertEqual(len(index), 2)

    def test_missing_root_yields_empty_index(self):
        self.assertEqual(naming.index_project(os.path.join(self.root, "nope")), {})

    def test_search_file_prefers_requested_extension(self):
        self._touch("Bracket.step")
        self._touch("Bracket.FCStd")
        found = naming.search_file(self.root, "Bracket.FCStd")
        self.assertTrue(found.endswith("Bracket.FCStd"))

    def test_search_file_matches_across_diacritics(self):
        self._touch(unicodedata.normalize("NFC", "Açılım.FCStd"))
        found = naming.search_file(self.root, unicodedata.normalize("NFD", "Acilim.FCStd"))
        self.assertTrue(found.endswith("Açılım.FCStd"))


class InstanceSuffixTests(unittest.TestCase):
    def test_strips_trailing_instance_number(self):
        self.assertEqual(naming.strip_instance_suffix("Yan Sac Ek-1"), "Yan Sac Ek")
        self.assertEqual(naming.strip_instance_suffix("Yan Sac-12"), "Yan Sac")

    def test_leaves_names_without_suffix_untouched(self):
        self.assertEqual(naming.strip_instance_suffix("Yan Sac"), "Yan Sac")

    def test_only_strips_a_trailing_suffix(self):
        # A hyphen in the middle must survive, otherwise prefixes would collide.
        self.assertEqual(naming.strip_instance_suffix("A-B"), "A-B")


class ToDecimalTests(unittest.TestCase):
    def test_uses_comma_separator(self):
        self.assertEqual(naming.to_decimal(1.5), "1,5")
        self.assertEqual(naming.to_decimal(0.8), "0,8")

    def test_strips_trailing_zeros(self):
        self.assertEqual(naming.to_decimal(2.0), "2")
        self.assertEqual(naming.to_decimal(1.0, 3), "1")

    def test_zero_and_negative_edge_cases(self):
        self.assertEqual(naming.to_decimal(0.0), "0")
        self.assertEqual(naming.to_decimal(-0.0), "0")


class BuildDxfNameTests(unittest.TestCase):
    def test_laser_layout(self):
        name = naming.build_flat_dxf_name(
            document_name="Bracket",
            model_name="Bracket",
            configuration="Default",
            thickness="1,5",
            material="S235JR",
            qty=4,
            laser=True,
        )
        self.assertEqual(name, "L BracketDefault - 1,5mm S235JR 4 ad.DXF")

    def test_punch_marker(self):
        name = naming.build_flat_dxf_name(
            document_name="Bracket",
            model_name="Bracket",
            configuration="Default",
            thickness="1",
            material="S235JR",
            qty=1,
            laser=False,
        )
        self.assertTrue(name.startswith("Z "))

    def test_simetri_and_rotation_suffixes(self):
        name = naming.build_flat_dxf_name(
            document_name="B",
            model_name="B",
            configuration="C",
            thickness="1",
            material="M",
            qty=2,
            simetri=True,
            rotation=True,
        )
        self.assertIn("2 ad simetriği de var %R", name)

    def test_illegal_characters_are_removed(self):
        name = naming.build_flat_dxf_name(
            document_name="D",
            model_name="A/B:C",
            configuration="*",
            thickness="1",
            material="M",
            qty=1,
        )
        self.assertNotIn("/", name)
        self.assertNotIn(":", name)
        self.assertNotIn("*", name)

    def test_missing_thickness_omits_the_mm_field(self):
        name = naming.build_flat_dxf_name(
            document_name="B",
            model_name="B",
            configuration="C",
            thickness="",
            material="M",
            qty=1,
        )
        self.assertNotIn("mm", name)


class ScreenCapNameTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        self.addCleanup(self._tmp.cleanup)

    def test_two_digit_padding(self):
        self.assertEqual(
            os.path.basename(naming.build_screen_cap_path(self.root, 1)), "screencap01.png"
        )
        self.assertEqual(
            os.path.basename(naming.build_screen_cap_path(self.root, 42)), "screencap42.png"
        )

    def test_next_path_skips_existing(self):
        first = naming.next_screen_cap_path(self.root)
        self.assertEqual(os.path.basename(first), "screencap01.png")
        open(first, "wb").close()
        self.assertEqual(os.path.basename(naming.next_screen_cap_path(self.root)), "screencap02.png")

    def test_collect_is_numeric_ordered_and_filtered(self):
        for index in (10, 2, 1):
            open(naming.build_screen_cap_path(self.root, index), "wb").close()
        open(os.path.join(self.root, "screencapXX.png"), "wb").close()
        open(os.path.join(self.root, "other.png"), "wb").close()

        found = naming.collect_screen_caps(self.root)

        self.assertEqual(
            [os.path.basename(p) for p in found],
            ["screencap01.png", "screencap02.png", "screencap10.png"],
        )

    def test_collect_on_missing_folder_is_empty(self):
        self.assertEqual(naming.collect_screen_caps(os.path.join(self.root, "nope")), [])


if __name__ == "__main__":
    unittest.main()
