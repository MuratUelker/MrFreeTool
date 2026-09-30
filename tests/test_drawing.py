"""Tests for :mod:`mrfreecad.drawing` - scale, annotations, Qty, templates.

TechDraw objects are faked with plain Python classes.  That is deliberate: the
module only ever touches a small, stable slice of the TechDraw API
(``TypeId``, ``Text``, ``TextSize``, ``X``, ``Y``, ``Views``, ``addView``,
``removeView``, ``Scale``), so exercising it against a fake tests the actual
logic - the nearest-Qty rule, the landscape/portrait switch, the template swap -
without needing a running FreeCAD.
"""

import os
import tempfile
import unittest

from tests import _bootstrap  # noqa: F401  (path setup)

from mrfreecad import drawing


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------
class FakeDocument:
    def __init__(self):
        self.Objects = []
        self.Name = "TestDoc"
        self.recomputes = 0

    def addObject(self, type_id, name):
        obj = FakeObject(type_id, name, self)
        self.Objects.append(obj)
        return obj

    def removeObject(self, name):
        self.Objects = [o for o in self.Objects if o.Name != name]

    def getObject(self, name):
        for obj in self.Objects:
            if obj.Name == name:
                return obj
        return None

    def recompute(self, *args, **kwargs):
        self.recomputes += 1


class FakeObject:
    def __init__(self, type_id, name, document=None):
        self.TypeId = type_id
        self.Name = name
        self.Label = name
        self.Document = document
        self.Text = []
        self.TextSize = 0.0
        self.X = 0.0
        self.Y = 0.0
        self.Views = []
        self.Scale = 1.0
        self.ScaleType = "Page"
        self.Template = ""
        self.Height = 0.0
        self.Width = 0.0

    def addView(self, view):
        self.Views.append(view)

    def removeView(self, view):
        if view in self.Views:
            self.Views.remove(view)


def make_page(template="A3_Landscape", width=420.0, height=297.0, with_template=True):
    doc = FakeDocument()
    page = FakeObject("TechDraw::DrawPage", "Page", doc)
    doc.Objects.append(page)
    if with_template:
        template_obj = FakeObject("TechDraw::DrawSVGTemplate", "Template", doc)
        template_obj.Template = "/tmp/" + template
        template_obj.Width = width
        template_obj.Height = height
        page.addView(template_obj)
    return doc, page


def add_anno(page, text, x, y, size=13.0):
    anno = FakeObject("TechDraw::DrawViewAnnotation", "Anno", page.Document)
    anno.Text = ["<b>" + text + "</b>"]
    anno.TextSize = size
    anno.X = x
    anno.Y = y
    page.addView(anno)
    return anno


# ---------------------------------------------------------------------------
class ScaleLadderTests(unittest.TestCase):
    def test_first_three_steps_enlarge(self):
        self.assertEqual(drawing.scale_for_index(1), (3, 1))
        self.assertEqual(drawing.scale_for_index(2), (2, 1))
        self.assertEqual(drawing.scale_for_index(3), (1, 1))

    def test_then_reduces_by_one(self):
        self.assertEqual(drawing.scale_for_index(4), (1, 2))
        self.assertEqual(drawing.scale_for_index(21), (1, 19))
        self.assertEqual(drawing.scale_for_index(22), (1, 20))

    def test_below_range_clamps_to_the_first_step(self):
        self.assertEqual(drawing.scale_for_index(0), (3, 1))
        self.assertEqual(drawing.scale_for_index(-5), (3, 1))

    def test_ladder_length_follows_max_denominator(self):
        self.assertEqual(len(drawing.scale_ladder(20)), 22)  # 3 enlarging + 1:1..1:20
        self.assertEqual(len(drawing.scale_ladder(10)), 12)

    def test_ladder_is_ordered_and_ends_at_the_maximum(self):
        ladder = drawing.scale_ladder(20)
        self.assertEqual(ladder[0], (3, 1))
        self.assertEqual(ladder[-1], (1, 20))

    def test_format_scale(self):
        self.assertEqual(drawing.format_scale((1, 20)), "1:20")
        self.assertEqual(drawing.format_scale((3, 1)), "3:1")


class PageScaleTests(unittest.TestCase):
    def test_reads_reduction(self):
        _doc, page = make_page()
        page.Scale = 0.05
        self.assertEqual(drawing.page_scale(page), (1, 20))

    def test_reads_enlargement(self):
        _doc, page = make_page()
        page.Scale = 2.0
        self.assertEqual(drawing.page_scale(page), (2, 1))

    def test_one_to_one(self):
        _doc, page = make_page()
        page.Scale = 1.0
        self.assertEqual(drawing.page_scale(page), (1, 1))

    def test_guarded_against_nonsense(self):
        _doc, page = make_page()
        page.Scale = 0.0
        self.assertEqual(drawing.page_scale(page), (1, 1))
        self.assertEqual(drawing.page_scale(None), (1, 1))

    def test_round_trip(self):
        _doc, page = make_page()
        self.assertTrue(drawing.set_page_scale(page, (1, 25)))
        self.assertEqual(drawing.page_scale(page), (1, 25))

    def test_set_page_scale_switches_to_custom(self):
        _doc, page = make_page()
        drawing.set_page_scale(page, (1, 7))
        self.assertEqual(page.ScaleType, "Custom")

    def test_apply_scale_index(self):
        _doc, page = make_page()
        self.assertEqual(drawing.apply_scale_index(page, 5), (1, 3))
        self.assertEqual(page.Scale, 1 / 3)


class TemplateTests(unittest.TestCase):
    def setUp(self):
        # apply_template refuses a path that does not exist, on purpose: a
        # missing template must not clear the current one.  The tests therefore
        # need real files on disk.
        self._tmp = tempfile.TemporaryDirectory()
        self.template_path = os.path.join(self._tmp.name, "Anket Yeni.svg")
        with open(self.template_path, "w", encoding="utf-8") as handle:
            handle.write("<svg/>")
        self.addCleanup(self._tmp.cleanup)

    def test_size_comes_from_the_template(self):
        _doc, page = make_page(width=594.0, height=420.0)
        self.assertEqual(drawing.page_size_mm(page), (594.0, 420.0))

    def test_orientation_from_file_name(self):
        _doc, landscape = make_page(template="Antet Yatay.svg")
        _doc, portrait = make_page(template="Antet Dikey.svg")
        self.assertEqual(drawing.template_orientation(landscape), "landscape")
        self.assertEqual(drawing.template_orientation(portrait), "portrait")

    def test_orientation_falls_back_to_aspect_ratio(self):
        _doc, page = make_page(template="A3_ISO7200_Pep.svg", width=297.0, height=420.0)
        self.assertEqual(drawing.template_orientation(page), "portrait")

    def test_annotation_positions_differ_by_orientation(self):
        _doc, landscape = make_page(template="Antet Yatay.svg")
        _doc, portrait = make_page(template="Antet Dikey.svg")
        self.assertEqual(drawing.view_position(landscape, "zimba"), drawing.ANNO_ZIMBA_LANDSCAPE)
        self.assertEqual(drawing.view_position(portrait, "zimba"), drawing.ANNO_ZIMBA_PORTRAIT)
        self.assertEqual(
            drawing.view_position(landscape, "simetri"), drawing.ANNO_SIMETRI_LANDSCAPE
        )
        self.assertEqual(drawing.view_position(portrait, "simetri"), drawing.ANNO_SIMETRI_PORTRAIT)

    def test_apply_template_replaces_and_clears_notes(self):
        _doc, page = make_page()
        add_anno(page, "Qty", 100.0, 100.0)
        add_anno(page, "3", 100.0, 90.0)

        template = drawing.apply_template(page, self.template_path)

        self.assertIsNotNone(template)
        self.assertEqual(template.Template, self.template_path)
        # The old format's notes must not survive: they would overlap the new one.
        self.assertEqual(drawing.iter_annotations(page), [])

    def test_apply_template_rejects_a_missing_file(self):
        _doc, page = make_page()
        self.assertIsNone(drawing.apply_template(page, "/does/not/exist.svg"))
        self.assertIsNone(drawing.apply_template(page, ""))

    def test_apply_template_preserves_scale(self):
        _doc, page = make_page()
        drawing.set_page_scale(page, (1, 10))
        drawing.apply_template(page, self.template_path)
        self.assertEqual(drawing.page_scale(page), (1, 10))

    def test_apply_template_adds_a_template_when_absent(self):
        doc, page = make_page(with_template=False)
        template = drawing.apply_template(page, self.template_path)
        self.assertIsNotNone(template)
        self.assertTrue(any(v.TypeId == "TechDraw::DrawSVGTemplate" for v in page.Views))


class AnnotationTests(unittest.TestCase):
    def test_zimba_and_lazer_use_the_same_slot_but_differ_in_text(self):
        _doc, page = make_page()
        zimba = drawing.add_zimba(page)
        lazer = drawing.add_lazer(page)
        self.assertEqual(zimba.X, lazer.X)
        self.assertEqual(zimba.Y, lazer.Y)
        self.assertIn("Zımba", zimba.Text[0])
        self.assertIn("Lazer", lazer.Text[0])
        self.assertEqual(zimba.TextSize, drawing.STAMP_FONT_SIZE)

    def test_annotations_are_bold(self):
        _doc, page = make_page()
        anno = drawing.add_zimba(page)
        self.assertTrue(anno.Text[0].startswith("<b>"))

    def test_simetri_includes_the_quantity(self):
        _doc, page = make_page()
        anno = drawing.add_simetri(page, 7)
        self.assertIn("7 ad.", anno.Text[0])
        self.assertIn("simetriği de var", anno.Text[0])
        self.assertEqual(anno.TextSize, drawing.SIMETRI_FONT_SIZE)

    def test_simetri_replaces_rather_than_stacks(self):
        _doc, page = make_page()
        drawing.add_simetri(page, 2)
        drawing.add_simetri(page, 5)
        notes = [a for a in drawing.iter_annotations(page) if "simetri" in a.Text[0]]
        self.assertEqual(len(notes), 1)
        self.assertIn("5 ad.", notes[0].Text[0])

    def test_simetri_matches_a_differently_spelled_previous_note(self):
        _doc, page = make_page()
        add_anno(page, "2 ad. simetriği de var", 200.0, 37.0)
        drawing.add_simetri(page, 9)
        notes = [a for a in drawing.iter_annotations(page) if "simetri" in a.Text[0]]
        self.assertEqual(len(notes), 1)
        self.assertIn("9 ad.", notes[0].Text[0])

    def test_remove_annotations_containing_filters(self):
        _doc, page = make_page()
        add_anno(page, "Qty", 10.0, 10.0)
        add_anno(page, "2 ad. simetriği de var", 20.0, 20.0)
        self.assertEqual(drawing.remove_annotations_containing(page, "simetri"), 1)
        self.assertEqual(len(drawing.iter_annotations(page)), 1)

    def test_remove_with_empty_needle_clears_everything(self):
        _doc, page = make_page()
        add_anno(page, "A", 1.0, 1.0)
        add_anno(page, "B", 2.0, 2.0)
        self.assertEqual(drawing.remove_annotations_containing(page, ""), 2)
        self.assertEqual(drawing.iter_annotations(page), [])

    def test_removed_annotations_leave_the_page_and_the_document(self):
        doc, page = make_page()
        anno = add_anno(page, "Zımba", 1.0, 1.0)
        drawing.remove_annotations_containing(page, "Zımba")
        self.assertNotIn(anno, page.Views)
        self.assertIsNone(doc.getObject(anno.Name))


class QtyTests(unittest.TestCase):
    def _page_with_qty(self, value="3", dx=10.0, dy=0.0):
        doc, page = make_page()
        add_anno(page, "Qty", 200.0, 40.0)
        add_anno(page, value, 200.0 + dx, 40.0 + dy)
        return doc, page

    def test_finds_the_value_under_the_title(self):
        _doc, page = self._page_with_qty()
        found = drawing.find_qty_notes(page)
        self.assertEqual(len(found), 1)
        self.assertIn("3", found[0][0].Text[0])

    def test_nearest_number_wins(self):
        doc, page = make_page()
        add_anno(page, "Qty", 200.0, 40.0)
        add_anno(page, "9", 260.0, 40.0)   # far
        add_anno(page, "4", 203.0, 41.0)   # near
        found = drawing.find_qty_notes(page)
        self.assertEqual(len(found), 2)
        self.assertEqual(sorted(n[0].Text[0] for n in found), ["<b>4</b>", "<b>9</b>"])

    def test_non_numeric_notes_are_ignored(self):
        _doc, page = make_page()
        add_anno(page, "Qty", 200.0, 40.0)
        add_anno(page, "Rev A", 201.0, 41.0)
        self.assertEqual(drawing.find_qty_notes(page), [])

    def test_set_qty_updates_the_value(self):
        _doc, page = self._page_with_qty(value="3")
        self.assertEqual(drawing.set_qty(page, 6), 1)
        self.assertEqual(drawing.iter_annotations(page)[1].Text[0], "<b>6</b>")

    def test_set_qty_is_idempotent(self):
        _doc, page = self._page_with_qty(value="3")
        self.assertEqual(drawing.set_qty(page, 3), 0)

    def test_set_qty_reports_zero_without_a_qty_field(self):
        _doc, page = make_page()
        add_anno(page, "Malzeme", 10.0, 10.0)
        self.assertEqual(drawing.set_qty(page, 4), 0)

    def test_turkish_and_plain_titles_both_recognised(self):
        for title in ("Qty", "QTY", "qty", "Adet"):
            doc, page = make_page()
            add_anno(page, title, 100.0, 100.0)
            add_anno(page, "2", 100.0, 95.0)
            self.assertEqual(len(drawing.find_qty_notes(page)), 1, title)

    def test_decorated_value_is_parsed(self):
        doc, page = make_page()
        add_anno(page, "Qty", 100.0, 100.0)
        add_anno(page, "5 ad", 100.0, 95.0)
        self.assertEqual(len(drawing.find_qty_notes(page)), 1)


class PageDiscoveryTests(unittest.TestCase):
    def test_get_pages_finds_pages_only(self):
        doc, page = make_page()
        doc.addObject("Part::Feature", "Body")
        self.assertEqual(drawing.get_pages(doc), [page])

    def test_named_lookup_wins(self):
        doc, page = make_page()
        other = FakeObject("TechDraw::DrawPage", "Sheet2", doc)
        doc.Objects.append(other)
        self.assertIs(drawing.get_page(doc, "Sheet2"), other)

    def test_get_page_on_empty_document(self):
        doc = FakeDocument()
        self.assertIsNone(drawing.get_page(doc))

    def test_get_page_without_freecad_raises_a_clear_error(self):
        # Passing no document means "ask FreeCAD for the active one", which is
        # impossible outside FreeCAD.  The error must say so rather than
        # failing obscurely.
        from mrfreecad import compat

        if compat.HAS_FREECAD:  # pragma: no cover - only inside FreeCAD
            self.skipTest("running inside FreeCAD")
        with self.assertRaises(RuntimeError) as caught:
            drawing.get_page(None)
        self.assertIn("FreeCAD", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
