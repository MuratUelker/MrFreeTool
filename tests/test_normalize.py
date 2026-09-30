"""Tests for the thickness presets and the settings store.

The preset table encodes the shop's process values, carried over from the
SolidWorks original, so the table itself is asserted rather than assumed.
"""

import unittest
from typing import Tuple, cast

from tests import _bootstrap  # noqa: F401  (path setup)

from mrfreecad import normalize
from mrfreecad import settings as settings_mod


class ThicknessPresetTests(unittest.TestCase):
    def test_table_has_the_seven_shop_thicknesses(self):
        self.assertEqual(
            [preset[0] for preset in normalize.THICKNESS_PRESETS],
            ["0,5", "0,7", "0,8", "1", "1,2", "1,5", "2"],
        )

    def test_thicknesses_are_ascending(self):
        thicknesses = [preset[1] for preset in normalize.THICKNESS_PRESETS]
        self.assertEqual(thicknesses, sorted(thicknesses))

    def test_known_pairings_match_the_original(self):
        # (thickness, k-factor, bend radius) as used by the SolidWorks buttons.
        expected = {
            0.5: (0.05, 1.5),
            0.7: (0.05, 1.0),
            0.8: (0.15, 1.0),
            1.0: (0.24, 1.0),
            1.2: (0.31, 1.0),
            1.5: (0.17, 1.0),
            2.0: (0.105, 1.0),
        }
        for thickness, (k_factor, radius) in expected.items():
            preset = cast(
                Tuple[str, float, float, float], normalize.preset_for_thickness(thickness)
            )
            self.assertIsNotNone(preset, thickness)
            self.assertAlmostEqual(preset[2], k_factor, places=4, msg=str(thickness))
            self.assertAlmostEqual(preset[3], radius, places=4, msg=str(thickness))

    def test_lookup_is_tolerant_of_float_noise(self):
        self.assertIsNotNone(normalize.preset_for_thickness(1.5 + 1e-9))

    def test_unknown_thickness_returns_none(self):
        self.assertIsNone(normalize.preset_for_thickness(3.0))
        self.assertIsNone(normalize.preset_for_thickness("x"))
        self.assertIsNone(normalize.preset_for_thickness(None))

    def test_button_order(self):
        self.assertEqual(
            normalize.PRESET_LABELS, ("0,5", "0,8", "1", "1,2", "1,5", "2", "0,7")
        )

    def test_every_button_label_has_a_preset(self):
        for label in normalize.PRESET_LABELS:
            self.assertIsNotNone(normalize.preset_for_label(label), label)

    def test_label_lookup_accepts_a_dot_separator(self):
        self.assertIsNotNone(normalize.preset_for_label("0.5"))
        self.assertIsNone(normalize.preset_for_label("9,9"))

    def test_labels_are_unique(self):
        self.assertEqual(len(set(normalize.PRESET_LABELS)), len(normalize.PRESET_LABELS))

    def test_k_factors_are_in_a_physical_range(self):
        for _label, _thickness, k_factor, _radius in normalize.THICKNESS_PRESETS:
            self.assertGreater(k_factor, 0.0)
            self.assertLess(k_factor, 1.0)

    def test_bend_radius_is_positive_and_capped(self):
        # The shop uses a 1 mm bend radius from 0,8 up and a deeper 1,5 mm bend
        # for 0,5 mm sheet.  Note the radius is deliberately *not* always larger
        # than the sheet - for 1,2 mm and thicker it is tighter - so the
        # invariant asserted here is only that the value is usable.  These are
        # the original's numbers, reproduced unchanged.
        for label, _thickness, _k, radius in normalize.THICKNESS_PRESETS:
            self.assertGreater(radius, 0.0, label)
            self.assertLessEqual(radius, 1.5, label)

    def test_thin_sheets_get_at_least_a_full_thickness_bend(self):
        # Below 1 mm the bend must clear the sheet, which is the manufacturable
        # range this preset table covers.
        for label, thickness, _k, radius in normalize.THICKNESS_PRESETS:
            if thickness < 1.0:
                self.assertGreaterEqual(radius, thickness, label)

    def test_thinnest_sheet_gets_the_deepest_bend(self):
        thin = cast(Tuple[str, float, float, float], normalize.preset_for_thickness(0.5))
        thick = cast(Tuple[str, float, float, float], normalize.preset_for_thickness(2.0))
        self.assertGreater(thin[3], thick[3])


class PropertyNameTests(unittest.TestCase):
    def test_property_names_are_distinct(self):
        names = [
            normalize.PROP_K_FACTOR,
            normalize.PROP_BEND_RADIUS,
            normalize.PROP_THICKNESS,
            normalize.PROP_DESCRIPTION,
            normalize.PROP_WEIGHT,
            normalize.PROP_MATERIAL,
            normalize.PROP_RELIEF,
        ]
        self.assertEqual(len(set(names)), len(names))

    def test_description_is_the_property_the_dxf_name_reads(self):
        # export_dxf.read_thickness looks at PROP_DESCRIPTION first, so the two
        # modules have to agree on the name.
        from mrfreecad import export_dxf

        self.assertEqual(export_dxf.PROP_DESCRIPTION, normalize.PROP_DESCRIPTION)
        self.assertEqual(export_dxf.PROP_MATERIAL, normalize.PROP_MATERIAL)
        self.assertEqual(export_dxf.PROP_WEIGHT, normalize.PROP_WEIGHT)


class SettingsStoreTests(unittest.TestCase):
    """The store falls back to memory outside FreeCAD, so these run anywhere."""

    def setUp(self):
        self.store = settings_mod.SettingsStore("User parameter:Test/MrFreeTool")

    def test_defaults_are_returned_before_anything_is_written(self):
        self.assertEqual(self.store.get_int("Drawing/MaxQty", 10), 10)
        self.assertEqual(self.store.get_str("Template/Ayazsa"), "")
        self.assertTrue(self.store.get_bool("Dxf/LaserDefault"))

    def test_typed_round_trip(self):
        self.store.set_int("Drawing/MaxQty", 42)
        self.store.set_str("Template/Ayazsa", "/tmp/a.svg")
        self.store.set_bool("Dxf/LaserDefault", False)
        self.store.set_float("Capture/Dpi", 600)
        self.assertEqual(self.store.get_int("Drawing/MaxQty", 10), 42)
        self.assertEqual(self.store.get_str("Template/Ayazsa"), "/tmp/a.svg")
        self.assertFalse(self.store.get_bool("Dxf/LaserDefault"))
        self.assertEqual(self.store.get_float("Capture/Dpi", 300), 600.0)

    def test_out_of_range_values_are_contained(self):
        # set_max_scale_denominator clamps to the floor of 3 rather than
        # producing a scale ladder with no reducing steps.
        self.store.set_max_scale_denominator(1)
        self.assertEqual(self.store.max_scale_denominator(), 3)
        self.store.set_max_scale_denominator(50)
        self.assertEqual(self.store.max_scale_denominator(), 50)

    def test_a_stored_value_below_the_floor_falls_back_to_the_default(self):
        # A hand-edited parameter file can hold anything; the getter refuses it.
        self.store.set_int("Scale/MaxDenominator", 1)
        self.assertEqual(self.store.max_scale_denominator(), 20)

    def test_max_qty_is_at_least_one(self):
        self.store.set_max_qty(0)
        self.assertEqual(self.store.max_qty(), 1)

    def test_template_shortcuts(self):
        self.store.set_template("landscape", "/tmp/yatay.svg")
        self.store.set_template("portrait", "/tmp/dikey.svg")
        self.store.set_template("ayazsa", "/tmp/ayazsa.svg")
        self.store.set_template("karadeniz", "/tmp/karadeniz.svg")
        self.assertEqual(self.store.template("landscape"), "/tmp/yatay.svg")
        self.assertEqual(self.store.template("AYAZSA"), "/tmp/ayazsa.svg")
        self.assertEqual(self.store.template("nonsense"), "")

    def test_logo_round_trip(self):
        slot = settings_mod.LogoSlot(
            firm="Ayazsa", image="/tmp/logo.png", x=10.0, y=20.0, w=30.0, h=12.0
        )
        self.store.set_logo(slot)
        loaded = self.store.logo("Ayazsa")
        self.assertEqual(loaded.image, "/tmp/logo.png")
        self.assertEqual((loaded.x, loaded.y, loaded.w, loaded.h), (10.0, 20.0, 30.0, 12.0))

    def test_unknown_firm_gets_a_usable_default(self):
        slot = self.store.logo("YeniFirma")
        self.assertEqual(slot.firm, "YeniFirma")
        self.assertGreater(slot.w, 0.0)

    def test_as_dict_covers_every_default(self):
        data = self.store.as_dict()
        for key in settings_mod.DEFAULTS:
            self.assertIn(key, data)

    def test_apply_round_trips_the_snapshot(self):
        data = self.store.as_dict()
        data["Drawing/MaxQty"] = 7
        data["Dxf/LaserDefault"] = False
        data["Template/Karadeniz"] = "/tmp/k.svg"
        self.store.apply(data)
        self.assertEqual(self.store.get_int("Drawing/MaxQty", 10), 7)
        self.assertFalse(self.store.get_bool("Dxf/LaserDefault"))
        self.assertEqual(self.store.template("karadeniz"), "/tmp/k.svg")

    def test_known_firms(self):
        self.assertEqual(set(settings_mod.FIRMS), {"Ayazsa", "Karadeniz"})

    def test_default_pdf_name_is_the_originals(self):
        self.assertEqual(settings_mod.DEFAULTS["Pdf/FileName"], "montaj talimatı.pdf")

    def test_default_capture_prefix_is_the_originals(self):
        self.assertEqual(settings_mod.DEFAULTS["Capture/Prefix"], "screencap")


if __name__ == "__main__":
    unittest.main()
