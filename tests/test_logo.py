"""Tests for :mod:`mrfreecad.logo` - the sheet-to-pixel coordinate mapping.

The millimetre-to-pixel conversion is the part that has to be right: it is what
decides where a company logo lands on a printed sheet, and getting the y axis
the wrong way round puts the logo at the top of the page instead of the bottom.
"""

import unittest
from typing import Tuple, cast

from tests import _bootstrap  # noqa: F401  (path setup)

from mrfreecad import logo
from mrfreecad import settings as settings_mod
from mrfreecad.settings import LogoSlot


def slot(x=258.0, y=40.0, w=40.0, h=15.0):
    return LogoSlot(firm="Test", image="/tmp/logo.png", x=x, y=y, w=w, h=h)


def rect_of(testcase, *args, **kwargs):
    """Call ``slot_to_rect`` and return the rectangle, asserting it is valid.

    Tests unpack the result directly, which keeps them readable; asserting
    here means an unexpected ``None`` is reported at the call site rather than
    as a confusing subscript error.
    """
    rect = logo.slot_to_rect(*args, **kwargs)
    testcase.assertIsNotNone(rect)
    # assertIsNotNone does not narrow for a type checker, hence the cast.
    return cast(Tuple[int, int, int, int], rect)


class MmToRectTests(unittest.TestCase):
    def test_y_is_flipped_from_sheet_to_pixel_space(self):
        # Sheet space has its origin bottom-left, y up.  A logo whose bottom
        # edge sits 40 mm above the sheet's bottom edge must appear 40 mm up
        # from the *bottom*, which in pixel space is far from the top.
        canvas_w, canvas_h = 3508, 2480          # A4 landscape at 300 dpi
        paper_w_mm, paper_h_mm = 297.0, 210.0
        scale = canvas_w / paper_w_mm             # px per mm, from the width

        # Placed so the whole logo fits: 200 + 40 = 240 mm < 297 mm.
        rect = rect_of(self, slot(x=200.0), scale, canvas_w, canvas_h, paper_h_mm)
        x, y, w, h = rect
        self.assertAlmostEqual(w, 40.0 * scale, delta=1)
        self.assertAlmostEqual(h, 15.0 * scale, delta=1)
        # px_y = (paper_h - (y + h)) * scale = (210 - 55) * scale
        self.assertAlmostEqual(y, (paper_h_mm - (40.0 + 15.0)) * scale, delta=1)
        # Which is the lower half of the page, not the top.
        self.assertGreater(y, canvas_h / 2)
        # And the logo's bottom edge must land 40 mm up from the sheet bottom.
        bottom_px_from_edge = canvas_h - (y + h)
        self.assertAlmostEqual(bottom_px_from_edge, 40.0 * scale, delta=2)

    def test_a_logo_overhanging_the_sheet_is_clipped(self):
        # The default slot sits at x=258 mm with a 40 mm width, which runs past
        # a 297 mm sheet.  It must be clipped to the edge, not rejected.
        scale = 3508 / 297.0
        rect = rect_of(self, slot(x=258.0), scale, 3508, 2480, 210.0)
        self.assertEqual(rect[0] + rect[2], 3508)

    def test_a_logo_at_the_sheet_bottom_lands_at_the_bottom(self):
        # 1 px/mm with a 100 mm tall sheet, so the canvas is 100 px tall too.
        rect = rect_of(self, slot(x=0.0, y=0.0, w=10.0, h=10.0), 1.0, 100, 100, 100.0)
        # 100 - (0 + 10) = 90, so the top edge is 90 px down and the bottom is
        # flush with the sheet's bottom edge.
        self.assertEqual(rect[1] + rect[3], 100)

    def test_a_logo_at_the_sheet_top_lands_at_the_top(self):
        rect = rect_of(self, slot(x=0.0, y=90.0, w=10.0, h=10.0), 1.0, 100, 100, 100.0)
        self.assertEqual(rect[1], 0)

    def test_padding_grows_the_rectangle_symmetrically(self):
        scale = 1.0
        tight = rect_of(self, slot(x=100.0, y=40.0, w=10.0, h=10.0), scale, 1000, 1000, 200.0)
        padded = rect_of(
            self, slot(x=100.0, y=40.0, w=10.0, h=10.0), scale, 1000, 1000, 200.0, pad_mm_x=2.0
        )
        # 2 mm of padding adds 2 px of width, split evenly at the edges.
        self.assertEqual(padded[2] - tight[2], 2)
        self.assertEqual(tight[0] - padded[0], 1)

    def test_zero_sized_slot_is_rejected(self):
        self.assertIsNone(logo.slot_to_rect(slot(w=0.0), 1.0, 1000, 1000, 100.0))
        self.assertIsNone(logo.slot_to_rect(slot(h=0.0), 1.0, 1000, 1000, 100.0))

    def test_tiny_slot_is_rejected(self):
        self.assertIsNone(logo.slot_to_rect(slot(w=0.001, h=0.001), 1.0, 1000, 1000, 100.0))

    def test_slot_is_clipped_to_the_canvas(self):
        # A logo hanging off the right edge must be clipped, not dropped.
        rect = rect_of(self, slot(x=95.0, y=0.0, w=20.0, h=10.0), 1.0, 100, 100, 100.0)
        self.assertLessEqual(rect[0] + rect[2], 100)

    def test_fully_off_canvas_is_rejected(self):
        self.assertIsNone(logo.slot_to_rect(slot(x=500.0, y=0.0), 1.0, 100, 100, 100.0))


class StampGuardTests(unittest.TestCase):
    """The functions must fail cleanly, not raise, on unusable input."""

    def setUp(self):
        from mrfreecad.settings import get_settings

        self.settings = get_settings()
        self._saved = self.settings.as_dict()

    def tearDown(self):
        self.settings.apply(self._saved)

    def test_missing_logo_image_is_reported(self):
        slot_value = LogoSlot(firm="Ayazsa", image="/does/not/exist.png")
        self.settings.set_logo(slot_value)
        ok, report, message = logo.stamp_folder("Ayazsa", folder="/tmp")
        self.assertFalse(ok)
        self.assertIn("ayarlanmamış", report + message)

    def test_missing_folder_is_reported(self):
        slot_value = LogoSlot(firm="Ayazsa", image="/does/not/exist.png")
        self.settings.set_logo(slot_value)
        # Point at a folder that exists so the image check is not what fails.
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "l.png"), "wb") as handle:
                handle.write(b"x")
            slot_value.image = os.path.join(tmp, "l.png")
            self.settings.set_logo(slot_value)
            ok, _report, message = logo.stamp_folder("Ayazsa", folder=os.path.join(tmp, "nope"))
            self.assertFalse(ok)
            self.assertIn("bulunamadı", message)

    def test_folder_without_pngs_is_reported(self):
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            logo_path = os.path.join(tmp, "l.png")
            with open(logo_path, "wb") as handle:
                handle.write(b"x")
            slot_value = LogoSlot(firm="Ayazsa", image=logo_path)
            self.settings.set_logo(slot_value)
            ok, _report, message = logo.stamp_folder("Ayazsa", folder=tmp)
            self.assertFalse(ok)
            self.assertIn("PNG", message)


class LogoSlotFitTests(unittest.TestCase):
    """A slot placed for a bigger sheet than the capture is silently clipped."""

    def test_fits_inside_the_sheet(self):
        self.assertTrue(settings_mod.LogoSlot("A", x=10.0, y=10.0, w=50.0, h=20.0).fits(297.0, 210.0))

    def test_overhanging_the_right_edge_does_not_fit(self):
        self.assertFalse(settings_mod.LogoSlot("A", x=280.0, y=10.0, w=50.0, h=20.0).fits(297.0, 210.0))

    def test_overhanging_the_top_does_not_fit(self):
        self.assertFalse(settings_mod.LogoSlot("A", x=10.0, y=200.0, w=50.0, h=20.0).fits(297.0, 210.0))

    def test_negative_origin_does_not_fit(self):
        self.assertFalse(settings_mod.LogoSlot("A", x=-5.0, y=10.0, w=50.0, h=20.0).fits(297.0, 210.0))

    def test_exact_edge_counts_as_fitting(self):
        self.assertTrue(settings_mod.LogoSlot("A", x=247.0, y=10.0, w=50.0, h=20.0).fits(297.0, 210.0))

    def test_default_slots_fit_an_a3_sheet(self):
        # The defaults are sized for A3, the sheet the shop's templates use.
        for firm in settings_mod.FIRMS:
            slot = settings_mod.logo_slot(firm)
            self.assertTrue(slot.fits(420.0, 297.0), firm)

    def test_unknown_firm_gets_a_usable_default_slot(self):
        # An unconfigured firm still needs a sane starting position, not zeros.
        slot = settings_mod.logo_slot("YeniFirma")
        self.assertEqual(slot.firm, "YeniFirma")
        self.assertTrue(slot.fits(420.0, 297.0))


class CleanOrderTests(unittest.TestCase):
    def test_other_firms_exclude_the_selected_one(self):
        from mrfreecad.settings import FIRMS

        others = [name for name in FIRMS if name != "Ayazsa"]
        self.assertIn("Karadeniz", others)
        self.assertNotIn("Ayazsa", others)


if __name__ == "__main__":
    unittest.main()
