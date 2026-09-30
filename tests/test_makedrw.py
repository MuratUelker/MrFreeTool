"""Tests for :mod:`mrfreecad.makedrw` - scale snapping and layout.

The scale-snapping rule is the part with real consequences: it decides whether
a drawing prints 1:1 or 1:20, and the original's rule (never scale *up*, snap
down to a standard value) is reproduced here exactly.
"""

import unittest

from tests import _bootstrap  # noqa: F401  (path setup)

from mrfreecad import makedrw


class SnapScaleTests(unittest.TestCase):
    def test_exact_standard_values_pass_through(self):
        for value in makedrw.STANDARD_SCALES:
            self.assertEqual(makedrw.snap_scale(value), value)

    def test_snaps_down_to_a_standard_value(self):
        # 0.31 fits between 0.25 and 0.5, so it snaps down to 0.25 - never up.
        self.assertEqual(makedrw.snap_scale(0.31), 0.25)
        self.assertEqual(makedrw.snap_scale(0.26), 0.25)
        self.assertEqual(makedrw.snap_scale(0.249), 0.2)

    def test_never_enlarges_beyond_the_raw_ratio(self):
        raw = 0.4
        self.assertLessEqual(makedrw.snap_scale(raw), raw)

    def test_enlarging_scales_are_supported(self):
        self.assertEqual(makedrw.snap_scale(2.4), 2.0)
        self.assertEqual(makedrw.snap_scale(1.2), 1.0)
        self.assertEqual(makedrw.snap_scale(3.5), 3.0)

    def test_below_the_smallest_standard_keeps_the_raw_ratio(self):
        # A part too large even for 1:100 still has to fit, so the raw ratio is
        # retained down to the MIN_SCALE floor rather than clamped to 1:100.
        self.assertAlmostEqual(makedrw.snap_scale(0.005), 0.01)
        self.assertEqual(makedrw.snap_scale(0.004), makedrw.MIN_SCALE)

    def test_nonsense_input_is_contained(self):
        self.assertEqual(makedrw.snap_scale(0), 0.01)
        self.assertEqual(makedrw.snap_scale(-1), 0.01)
        self.assertEqual(makedrw.snap_scale("abc"), 0.01)


class ScalePairTests(unittest.TestCase):
    def test_reductions_become_one_over_n(self):
        self.assertEqual(makedrw.scale_pair(0.5), (1, 2))
        self.assertEqual(makedrw.scale_pair(0.05), (1, 20))
        self.assertEqual(makedrw.scale_pair(0.01), (1, 100))

    def test_one_to_one(self):
        self.assertEqual(makedrw.scale_pair(1.0), (1, 1))

    def test_enlargements(self):
        self.assertEqual(makedrw.scale_pair(1.5), (3, 2))
        self.assertEqual(makedrw.scale_pair(2.0), (2, 1))
        self.assertEqual(makedrw.scale_pair(3.0), (3, 1))

    def test_every_standard_scale_yields_exact_integers(self):
        for value in makedrw.STANDARD_SCALES:
            numerator, denominator = makedrw.scale_pair(value)
            self.assertAlmostEqual(numerator / denominator, value, places=9)

    def test_guarded(self):
        self.assertEqual(makedrw.scale_pair(0), (1, 1))
        self.assertEqual(makedrw.scale_pair("x"), (1, 1))


class _FakeShape:
    """A shape exposing only the bounding box, which is all the code reads."""

    def __init__(self, x, y, z=0.0):
        self.BoundBox = type("Box", (), {"XLength": x, "YLength": y, "ZLength": z})()


class OutlineTests(unittest.TestCase):
    def test_landscape_shape_does_not_need_rotation(self):
        shape = _FakeShape(300.0, 100.0, 2.0)
        self.assertFalse(makedrw.needs_landscape_rotation(shape))

    def test_portrait_shape_is_rotated(self):
        shape = _FakeShape(100.0, 300.0, 2.0)
        self.assertTrue(makedrw.needs_landscape_rotation(shape))

    def test_missing_shape_does_not_rotate(self):
        self.assertFalse(makedrw.needs_landscape_rotation(None))
        self.assertEqual(makedrw.outline_mm(None), (0.0, 0.0))


class UsableFractionTests(unittest.TestCase):
    def test_matches_the_originals_85_percent_margin(self):
        self.assertEqual(makedrw.USABLE_FRACTION, 0.85)

    def test_standard_view_set_has_three_views(self):
        self.assertEqual(len(makedrw.STANDARD_VIEWS), 3)
        labels = [label for label, _d, _x in makedrw.STANDARD_VIEWS]
        self.assertEqual(labels, ["Front", "Top", "Right"])

    def test_view_directions_are_unit_vectors(self):
        for _label, direction, x_direction in makedrw.STANDARD_VIEWS:
            for vector in (direction, x_direction):
                length = sum(component * component for component in vector) ** 0.5
                self.assertAlmostEqual(length, 1.0, places=9)


if __name__ == "__main__":
    unittest.main()
