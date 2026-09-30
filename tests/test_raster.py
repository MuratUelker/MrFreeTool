"""Tests for :mod:`mrfreecad.raster` - the PNG pipeline and compositing.

The PNG encoder/decoder is exercised as a round trip, and the background flood
fill is tested on a synthetic image with a known content box.  These are the
routines that decide what ends up on a printed sheet, so they are worth
covering even though Qt is unavailable here - the pure-Python decoder is the
one that gets used when Qt is missing.
"""

import os
import tempfile
import unittest

from tests import _bootstrap  # noqa: F401  (path setup)

from mrfreecad import raster


def make_raster(width, height, colour=(255, 255, 255, 255)):
    return raster.Raster(width, height, fill=colour[0]).paint(colour)


def draw_rect(image, x0, y0, x1, y1, colour=(0, 0, 0, 255)):
    for y in range(y0, y1):
        for x in range(x0, x1):
            image.set(x, y, colour)


class RasterBasicsTests(unittest.TestCase):
    def test_default_is_white_and_opaque(self):
        image = raster.Raster(4, 3)
        self.assertEqual(image.get(0, 0), (255, 255, 255, 255))
        self.assertEqual(image.nbytes, 4 * 3 * 4)

    def test_buffer_length_is_validated(self):
        with self.assertRaises(ValueError):
            raster.Raster(2, 2, bytearray(3))

    def test_set_is_clipped_to_the_bounds(self):
        image = make_raster(2, 2)
        image.set(9, 9, (1, 2, 3, 4))  # must not raise
        image.set(-1, 0, (1, 2, 3, 4))

    def test_copy_is_independent(self):
        image = make_raster(2, 2)
        clone = image.copy()
        clone.set(0, 0, (0, 0, 0, 255))
        self.assertEqual(image.get(0, 0), (255, 255, 255, 255))


class PngRoundTripTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self._tmp.name, "test.png")
        self.addCleanup(self._tmp.cleanup)

    def test_write_then_read_is_lossless(self):
        image = raster.Raster(7, 5)
        # A gradient plus an alpha ramp exercises every channel.
        for y in range(5):
            for x in range(7):
                image.set(x, y, (x * 30 % 256, y * 50 % 256, (x + y) * 20 % 256, (x * 36) % 256))

        self.assertTrue(raster.write_png(self.path, image, 300))

        loaded = raster.load_rgba(self.path)
        self.assertEqual((loaded.width, loaded.height), (7, 5))
        for y in range(5):
            for x in range(7):
                self.assertEqual(loaded.get(x, y), image.get(x, y), "pixel {0},{1}".format(x, y))

    def test_header_reports_the_size(self):
        image = make_raster(11, 13)
        raster.write_png(self.path, image, 300)
        self.assertEqual(raster.read_png_size(self.path), (11, 13))

    def test_write_is_atomic(self):
        # The temp file must not survive a successful write.
        image = make_raster(3, 3)
        raster.write_png(self.path, image, 300)
        self.assertFalse(os.path.exists(self.path + ".part"))
        self.assertTrue(os.path.isfile(self.path))

    def test_rejects_a_non_png(self):
        bogus = os.path.join(self._tmp.name, "bogus.png")
        with open(bogus, "wb") as handle:
            handle.write(b"not a png at all")
        with self.assertRaises(ValueError):
            raster.read_png_size(bogus)


class ContentBboxTests(unittest.TestCase):
    def test_finds_a_known_box(self):
        image = make_raster(50, 50)
        draw_rect(image, 10, 20, 30, 40)
        box = raster.content_bbox(image, tolerance=10)
        self.assertEqual(box, (10, 20, 20, 20))

    def test_background_is_flooded_to_white(self):
        image = make_raster(20, 20)
        draw_rect(image, 5, 5, 15, 15, (250, 250, 250, 255))
        # A near-white background must still be counted as background.
        raster.content_bbox(image, tolerance=20)
        self.assertEqual(image.get(0, 0), (255, 255, 255, 255))

    def test_interior_white_survives(self):
        # A white object inside dark content must not be erased: the flood is
        # seeded from the border, so it cannot reach an enclosed region.
        image = make_raster(30, 30, colour=(0, 0, 0, 255))
        draw_rect(image, 5, 5, 25, 25, (0, 0, 0, 255))
        draw_rect(image, 10, 10, 20, 20, (255, 255, 255, 255))
        box = raster.content_bbox(image, tolerance=10)
        self.assertIsNotNone(box)
        self.assertEqual(image.get(15, 15), (255, 255, 255, 255))

    def test_uniform_image_has_no_content(self):
        image = make_raster(10, 10)
        self.assertIsNone(raster.content_bbox(image, tolerance=5))

    def test_empty_raster(self):
        self.assertIsNone(raster.content_bbox(raster.Raster(0, 0)))


class ClearAndPasteTests(unittest.TestCase):
    def test_clear_rect_fills_and_clips(self):
        image = make_raster(10, 10, colour=(0, 0, 0, 255))
        raster.clear_rect(image, 2, 2, 3, 3)
        self.assertEqual(image.get(3, 3), (255, 255, 255, 255))
        # Out-of-bounds clears must be clipped, not raise.
        raster.clear_rect(image, -5, -5, 100, 100)
        self.assertEqual(image.get(0, 0), (255, 255, 255, 255))

    def test_paste_opaque_replaces(self):
        dst = make_raster(5, 5, colour=(0, 0, 0, 255))
        src = make_raster(2, 2, colour=(255, 0, 0, 255))
        raster.paste_rgba(dst, src, 1, 1)
        self.assertEqual(dst.get(1, 1), (255, 0, 0, 255))
        self.assertEqual(dst.get(0, 0), (0, 0, 0, 255))

    def test_paste_transparent_is_a_no_op(self):
        dst = make_raster(5, 5, colour=(10, 20, 30, 255))
        src = make_raster(2, 2, colour=(255, 0, 0, 0))
        raster.paste_rgba(dst, src, 1, 1)
        self.assertEqual(dst.get(1, 1), (10, 20, 30, 255))

    def test_paste_clips_at_the_edges(self):
        dst = make_raster(4, 4)
        src = make_raster(3, 3, colour=(0, 0, 0, 255))
        raster.paste_rgba(dst, src, 2, 2)  # overhangs by 1px
        self.assertEqual(dst.get(3, 3), (0, 0, 0, 255))


class FitIntoCanvasTests(unittest.TestCase):
    def test_produces_the_requested_canvas(self):
        source = make_raster(100, 50, colour=(0, 0, 0, 255))
        canvas = raster.fit_into_canvas(source, 300, 200)
        self.assertEqual((canvas.width, canvas.height), (300, 200))

    def test_canvas_is_centred(self):
        # A 20x20 dark block on a 100x100 canvas with a 20% margin: the block
        # scales to 80x80 and must sit dead centre, surrounded by white.
        source = raster.Raster(20, 20)
        draw_rect(source, 0, 0, 20, 20, (0, 0, 0, 255))
        canvas = raster.fit_into_canvas(source, 100, 100, margin=0.2)

        self.assertEqual(canvas.get(50, 50), (0, 0, 0, 255))
        self.assertEqual(canvas.get(0, 0), (255, 255, 255, 255))
        self.assertEqual(canvas.get(99, 99), (255, 255, 255, 255))
        # The content edge lands at the 10% inset on each side.
        self.assertEqual(canvas.get(10, 50), (0, 0, 0, 255))
        self.assertEqual(canvas.get(9, 50), (255, 255, 255, 255))

    def test_landscape_source_in_landscape_canvas_keeps_aspect(self):
        source = make_raster(200, 100, colour=(0, 0, 0, 255))
        canvas = raster.fit_into_canvas(source, 200, 100, margin=0.0)
        # 1:1 box, so the content covers the canvas exactly.
        self.assertEqual(canvas.get(100, 50), (0, 0, 0, 255))

    def test_margin_shrinks_the_content(self):
        source = make_raster(100, 100, colour=(0, 0, 0, 255))
        canvas = raster.fit_into_canvas(source, 200, 200, margin=0.5)
        # With a 50% margin the content occupies the middle quarter.
        self.assertEqual(canvas.get(100, 100), (0, 0, 0, 255))
        self.assertEqual(canvas.get(2, 2), (255, 255, 255, 255))

    def test_degenerate_box_falls_back_to_the_whole_image(self):
        source = make_raster(10, 10, colour=(0, 0, 0, 255))
        canvas = raster.fit_into_canvas(source, 40, 40, box=(5, 5, 0, 0), margin=0.0)
        self.assertEqual(canvas.get(20, 20), (0, 0, 0, 255))


class CanvasPxTests(unittest.TestCase):
    def test_a4_at_300_dpi(self):
        # 297 mm / 25.4 * 300 = 3507.87 -> 3508 px
        width, height = raster.canvas_px(297.0, 210.0, 300)
        self.assertEqual((width, height), (3508, 2480))

    def test_scales_with_dpi(self):
        low = raster.canvas_px(297.0, 210.0, 150)
        high = raster.canvas_px(297.0, 210.0, 300)
        self.assertAlmostEqual(high[0], low[0] * 2, delta=2)

    def test_mm_to_px(self):
        self.assertEqual(raster.mm_to_px(10.0, 2.0), 20)


if __name__ == "__main__":
    unittest.main()
