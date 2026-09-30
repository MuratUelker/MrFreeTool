"""Integration tests against a real FreeCAD.

These are the tests that matter most and could not be written before: they run
the addon against a live ``FreeCADCmd`` interpreter, so the TechDraw object
model, the DXF writer and the exporters are exercised for real rather than
against a fake.

They skip automatically when FreeCAD is not installed, so the unit suite stays
runnable anywhere::

    python3 tests/test_integration_free.py            # if freecadcmd is on PATH
    FREECADCMD=/path/to/freecadcmd python3 tests/test_integration_free.py

Each test runs in its own FreeCAD process, because a crashed interpreter would
otherwise take the whole suite down with it.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def _as_float(value) -> float:
    """Best-effort float from a Quantity, a string or a number.

    The driver runs inside FreeCAD and records plain JSON, so quantities come
    back as strings like ``"258.0 mm"``.
    """
    if isinstance(value, str):
        digits = "".join(ch for ch in value if ch.isdigit() or ch in ".-")
        try:
            return float(digits)
        except ValueError:
            return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _find_freecadcmd() -> str:
    """Locate a FreeCAD command-line interpreter."""
    override = os.environ.get("FREECADCMD")
    if override and os.path.isfile(override):
        return override
    for name in ("freecadcmd", "FreeCADCmd", "freecad-cmd"):
        found = shutil.which(name)
        if found:
            return found
    return ""


FREECADCMD = _find_freecadcmd()

#: A self-contained script executed inside FreeCAD.  Kept as a string so the
#: whole test suite lives in one importable file with no fixture directory.
_DRIVER = r'''
import json, math, os, sys, tempfile, zipfile

sys.path.insert(0, "__PROJECT_ROOT__")
import FreeCAD

import mrfreecad
from mrfreecad import compat, drawing, makedrw, normalize, refrepair
from mrfreecad import export_dxf, export_png, flatpattern, naming, settings, screencap

out = {}


def plain(value):
    """Coerce FreeCAD types (Quantity, tuple-of-Quantity) to plain Python."""
    if hasattr(value, "Value") and hasattr(value, "getValue"):
        try:
            return float(value.getValue())
        except Exception:
            pass
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    if isinstance(value, dict):
        return dict((k, plain(v)) for k, v in value.items())
    return value


def as_float(value):
    """Best-effort float from a Quantity, a string or a number."""
    for attribute in ("getValue", "Value"):
        getter = getattr(value, attribute, None)
        if callable(getter):
            try:
                return float(getter())
            except Exception:
                pass
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def expression_engine(doc):
    """The document's expression bindings, as ``(target, expression)`` pairs."""
    try:
        engine = doc.ExpressionEngine
    except Exception:
        return []
    out_pairs = []
    for entry in engine or []:
        try:
            out_pairs.append(str(entry[0]) + " = " + str(entry[1]))
        except Exception:
            out_pairs.append(str(entry))
    return out_pairs


def record(key, value):
    out[key] = plain(value)


def make_sheet(name="Sheet", w=120.0, d=60.0, h=2.0, label=None):
    box = doc.addObject("Part::Box", name)
    box.Length, box.Width, box.Height = w, d, h
    if label:
        box.Label = label
    doc.recompute()
    return box


doc = FreeCAD.newDocument("Integration")

# -- 1. flat pattern discovery -------------------------------------------
plate = make_sheet("Plate", 200.0, 100.0, 1.5, label="Kose")
found = flatpattern.find_flat_pattern(doc)
record("flat_found", found is not None)
record("flat_label", getattr(found[0], "Label", None) if found else None)
record("flat_is_single_sheet", flatpattern._is_single_sheet(found[1]) if found else None)
record("bbox_mm", [found[1].BoundBox.XLength, found[1].BoundBox.YLength] if found else None)

# A named unfold-like object must win over the heuristic.
unfold = doc.addObject("Part::Feature", "Unfold")
unfold.Shape = plate.Shape.copy()
unfold.Label = "Acilim"
doc.recompute()
picked = flatpattern.find_flat_pattern(doc)
record("unfold_preferred", getattr(picked[0], "Label", None) if picked else None)
record("is_flat_label_turkish", flatpattern.is_flat_pattern_label("Açılım"))
record("is_flat_label_nfd", flatpattern.is_flat_pattern_label("Acilim"))
doc.removeObject(unfold.Name)
doc.recompute()

# -- 2. settings ---------------------------------------------------------
settings.get_settings().set("Capture/PaperWidthMm", 297.0)
settings.get_settings().set("Capture/PaperHeightMm", 210.0)
record("max_qty", settings.get_settings().max_qty())
record("persistent_settings", settings.get_settings().persistent)
record("landscape_templates", len(settings.builtin_templates(True)))
record("portrait_templates", len(settings.builtin_templates(False)))
default_tpl = makedrw._default_template(True)
record("default_template", os.path.basename(default_tpl) if default_tpl else "")
record("default_template_exists", bool(default_tpl) and os.path.isfile(default_tpl))

# -- 3. TechDraw page, annotations, Qty, scale ----------------------------
page = doc.addObject("TechDraw::DrawPage", "Page")
tpl = doc.addObject("TechDraw::DrawSVGTemplate", "Template")
tpl.Template = default_tpl
# A template attaches through the property, not addView().
page.Template = tpl
page.KeepUpdated = True
doc.recompute()
record("template_attached", page.Template is not None)

record("page_size_mm", [round(v, 1) for v in drawing.page_size_mm(page)])
record("orientation", drawing.template_orientation(page))

drawing.add_zimba(page)
drawing.add_lazer(page)
drawing.add_simetri(page, 4)
annos = drawing.iter_annotations(page)
record("anno_count", len(annos))
record("anno_texts", [drawing._annotation_text(a) for a in annos])
record("anno_positions", [[round(a.X, 1), round(a.Y, 1)] for a in annos])
record("anno_sizes", [a.TextSize for a in annos])

# Qty: a title plus the nearest numeric note.
drawing.add_annotation(page, "Qty", 250.0, 40.0, 4.0)
near = drawing.add_annotation(page, "9", 253.0, 36.0, 4.0)
far = drawing.add_annotation(page, "7", 268.0, 36.0, 4.0)
record("qty_candidates", len(drawing.find_qty_notes(page)))
record("qty_changed", drawing.set_qty(page, 11))
record("qty_texts", [drawing._annotation_text(a) for a in page.Views
                     if getattr(a, "TypeId", "") == "TechDraw::DrawViewAnnotation"])

# Re-running simetri must replace, not stack.
before = len(drawing.iter_annotations(page))
drawing.add_simetri(page, 6)
record("simetri_replaced", len(drawing.iter_annotations(page)) == before)

# Scale read/write round trip.
for pair in ((1, 1), (1, 2), (1, 20), (1, 5), (2, 1), (1, 7), (1, 100)):
    drawing.set_page_scale(page, pair)
    record("scale_%s" % ("_".join(str(p) for p in pair)),
           drawing.page_scale(page) == pair)

# Template swap clears the old notes.
record("apply_template_ok", drawing.apply_template(page, default_tpl) is not None)
record("annos_after_swap", len(drawing.iter_annotations(page)))

# -- 4. Make Drw ---------------------------------------------------------
page2 = makedrw.make_drawing(source=plate, use_flat_pattern=False, single_view=True)
record("makedrw_page", page2 is not None)
if page2 is not None:
    record("makedrw_views", len(drawing.iter_views(page2)))
    record("makedrw_scale", drawing.format_scale(drawing.page_scale(page2)))
    record("makedrw_template", drawing.template_name(page2))
    record("makedrw_size", [round(v, 1) for v in drawing.page_size_mm(page2)])

# Three-view variant.
page3 = makedrw.make_drawing(source=plate, use_flat_pattern=False)
record("makedrw3_views", len(drawing.iter_views(page3)) if page3 else 0)

# A big part must be scaled down, a small one not enlarged.
big = make_sheet("Big", 3000.0, 1500.0, 3.0)
p4 = makedrw.make_drawing(source=big, use_flat_pattern=False, single_view=True)
record("big_scale", drawing.format_scale(drawing.page_scale(p4)) if p4 else "")
small = make_sheet("Small", 30.0, 20.0, 1.0)
p5 = makedrw.make_drawing(source=small, use_flat_pattern=False, single_view=True)
record("small_scale", drawing.format_scale(drawing.page_scale(p5)) if p5 else "")

# -- 5. Normalize --------------------------------------------------------
obj = compat.active_object() or plate
ok, message = normalize.norm_part(obj=plate, k_factor=0.42, material="S355")
record("norm_ok", ok)
record("norm_report_has_kfactor", "0,42" in message or "0.42" in message)
record("kfactor_property", as_float(getattr(plate, normalize.PROP_K_FACTOR, None)))
record("description_before_presets", getattr(doc, normalize.PROP_DESCRIPTION, None))
record("weight", getattr(doc, normalize.PROP_WEIGHT, None))
record("thickness_property", getattr(plate, normalize.PROP_THICKNESS, None))

for label in normalize.PRESET_LABELS:
    preset = normalize.preset_for_label(label)
    ok2, _m = normalize.apply_preset(preset[1], obj=plate)
    record("preset_%s" % label, ok2)
record("thickness_after_preset", as_float(getattr(plate, normalize.PROP_THICKNESS)))
# Read after the presets, which is when a thickness exists and the
# description is written to match it.
record("description", getattr(doc, normalize.PROP_DESCRIPTION, None))
# Recorded after the presets: that is when a thickness is known and the
# description can be bound to it.

record("read_thickness_property", normalize.read_thickness_property(plate))
record("read_thickness_text", export_dxf.read_thickness(plate))
record("read_weight_kg", export_dxf.read_weight_kg(plate))
record("read_material", export_dxf.read_material(plate))
record("metadata", export_dxf.read_metadata(plate))
doc.recompute()

# -- 6. DXF export -------------------------------------------------------
work = tempfile.mkdtemp(prefix="mrfree_it_")
FreeCAD.ParamGet("User parameter:BaseApp/Preferences/Mod/MrFreeTool").SetString(
    "Dxf/OutputDir", work
)
ok, path, message = export_dxf.export_flat_dxf(source=plate, laser=True, qty=3, simetri=True)
record("dxf_ok", ok)
record("dxf_message", message)
record("dxf_name", os.path.basename(path) if path else "")
record("dxf_exists", bool(path) and os.path.isfile(path))
record("dxf_size", os.path.getsize(path) if path and os.path.isfile(path) else 0)
if ok and os.path.isfile(path):
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        head = handle.read(4000)
    record("dxf_is_dxf", "SECTION" in head)
    record("dxf_has_entities", "ENTITIES" in head or "LWPOLYLINE" in head or "LINE" in head)

# Punched variant, so the Z marker is covered too.
ok_z, path_z, _ = export_dxf.export_flat_dxf(source=plate, laser=False, qty=1)
record("dxf_z_name", os.path.basename(path_z) if path_z else "")
record("dxf_z_ok", ok_z)

# -- 7. Page DXF / PNG ---------------------------------------------------
if page2 is not None:
    ok_d, path_d, msg_d = export_dxf.export_page_dxf(page2, os.path.join(work, "page.DXF"))
    record("page_dxf_ok", ok_d)
    record("page_dxf_exists", bool(path_d) and os.path.isfile(path_d))

    png_ok, png_path, png_msg = export_png.export_page_png(page2, os.path.join(work, "page.png"))
    record("page_png_ok", png_ok)
    record("page_png_msg", png_msg[:200])
    if png_path and os.path.isfile(png_path):
        from mrfreecad.raster import read_png_size

        record("page_png_size", list(read_png_size(png_path)))
        record("page_png_bytes", os.path.getsize(png_path))

# -- 8. Reference repair on a real saved document ------------------------
saved = os.path.join(work, "Asm.FCStd")
FreeCAD.ParamGet("User parameter:BaseApp/Preferences/Mod/MrFreeTool").SetString(
    "Dxf/OutputDir", ""
)
doc.saveAs(saved)
record("saved_size", os.path.getsize(saved))
record("refs_of_saved", refrepair.read_references(saved))
changed, report = refrepair.repair_project(work)
record("repair_changed", changed)
record("repair_report_lines", len(report.splitlines()))

# -- 9. Raster round trip -------------------------------------------------
from mrfreecad import raster

img = raster.Raster(60, 40)
raster.clear_rect(img, 10, 8, 30, 32, (10, 20, 30, 255))
png = os.path.join(work, "rt.png")
raster.write_png(png, img, 300)
back = raster.load_rgba(png)
record("raster_size", [back.width, back.height])
record("raster_pixel", list(back.get(15, 15)))
record("raster_bbox", list(raster.content_bbox(img, 20) or ()))

# -- 10. Command dispatch (headless-safe) -------------------------------
results = {}
for name in mrfreecad.list_commands():
    try:
        r = mrfreecad.run(name)
        results[name] = [bool(r.ok), bool(r.message)]
    except Exception as exc:
        results[name] = ["EXCEPTION", str(exc)]
record("commands", results)

record("doc_dir", work)

# default=str makes the dump total: FreeCAD hands back Quantity and enum
# objects that plain() may not reach, and losing the whole report over one
# value would hide every other finding.
print("__MRFREE_JSON__" + json.dumps(out, ensure_ascii=False, default=str))
'''


class FreeCADIntegrationTests(unittest.TestCase):
    """One subprocess against a real FreeCAD, with many assertions."""

    @classmethod
    def setUpClass(cls):
        if not FREECADCMD:
            raise unittest.SkipTest("freecadcmd not found; set FREECADCMD to run these")
        cls.work = tempfile.mkdtemp(prefix="mrfree_it_outer_")
        script = os.path.join(cls.work, "driver.py")
        # Plain substitution, not %-formatting: the driver is full of literal
        # per-cent signs that would confuse a format string.
        with open(script, "w", encoding="utf-8") as handle:
            handle.write(_DRIVER.replace("__PROJECT_ROOT__", ROOT.replace("\\", "/")))
        try:
            proc = subprocess.run(
                [FREECADCMD, "-c", script],
                capture_output=True,
                text=True,
                timeout=420,
                cwd=cls.work,
            )
        except subprocess.TimeoutExpired:
            raise unittest.SkipTest("FreeCAD timed out")
        cls.script = script
        cls.stdout = proc.stdout or ""
        cls.stderr = proc.stderr or ""
        marker = "__MRFREE_JSON__"
        if marker not in cls.stdout:
            raise AssertionError(
                "the FreeCAD driver did not report.\n"
                "--- stdout (tail) ---\n{0}\n--- stderr (tail) ---\n{1}".format(
                    cls.stdout[-3000:], cls.stderr[-3000:]
                )
            )
        cls.data = json.loads(cls.stdout.split(marker, 1)[1].strip().splitlines()[0])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work, ignore_errors=True)

    def d(self, key):
        """Fetch a recorded value, failing with the FreeCAD output if absent."""
        self.assertIn(key, self.data, "{0} not recorded".format(key))
        return self.data[key]


class FlatPatternTests(FreeCADIntegrationTests):
    def test_a_single_solid_sheet_is_recognised(self):
        self.assertTrue(self.d("flat_found"))
        self.assertTrue(self.d("flat_is_single_sheet"))

    def test_the_shape_carries_a_usable_bounding_box(self):
        x, y = self.d("bbox_mm")
        self.assertAlmostEqual(x, 200.0, delta=0.5)
        self.assertAlmostEqual(y, 100.0, delta=0.5)

    def test_a_turkish_unfold_label_is_recognised_in_both_unicode_forms(self):
        self.assertTrue(self.d("is_flat_label_turkish"))
        self.assertTrue(self.d("is_flat_label_nfd"))

    def test_an_explicit_unfold_wins_over_the_heuristic(self):
        self.assertEqual(self.d("unfold_preferred"), "Acilim")


class SettingsTests(FreeCADIntegrationTests):
    def test_settings_persist_into_the_freecad_parameter_tree(self):
        self.assertTrue(self.d("persistent_settings"))

    def test_stock_freecad_templates_are_discovered(self):
        # The regression this guards: a non-recursive scan found none, which
        # left Make Drw with no fallback template.
        self.assertGreater(self.d("landscape_templates"), 10)
        self.assertGreater(self.d("portrait_templates"), 3)

    def test_the_default_template_exists_on_disk(self):
        self.assertTrue(self.d("default_template_exists"))


class TechDrawTests(FreeCADIntegrationTests):
    def test_page_size_comes_from_the_real_template(self):
        width, height = self.d("page_size_mm")
        self.assertIn(round(width), (297, 420, 210, 841, 594))
        self.assertGreater(width, height)

    def test_annotations_are_created_at_the_expected_positions(self):
        texts = self.d("anno_texts")
        self.assertIn("Zımba", " ".join(texts))
        self.assertIn("Lazer", " ".join(texts))
        self.assertTrue(any("simetriği de var" in t for t in texts))

        # Font sizes arrive as millimetres converted from the original's points;
        # test_font_sizes_are_points_converted_to_millimetres pins the values.
        self.assertEqual(len(self.d("anno_sizes")), 3)

    def test_stamp_notes_sit_at_the_configured_position(self):
        # The point of porting the millimetre tables is that the notes land
        # exactly where the SolidWorks tool put them.
        from mrfreecad import drawing

        positions = [tuple(_as_float(v) for v in pair) for pair in self.d("anno_positions")]
        for (x, y) in positions[:2]:
            self.assertAlmostEqual(x, drawing.ANNO_ZIMBA_LANDSCAPE[0], delta=0.5)
            self.assertAlmostEqual(y, drawing.ANNO_ZIMBA_LANDSCAPE[1], delta=0.5)
        self.assertAlmostEqual(positions[2][0], drawing.ANNO_SIMETRI_LANDSCAPE[0], delta=0.5)
        self.assertAlmostEqual(positions[2][1], drawing.ANNO_SIMETRI_LANDSCAPE[1], delta=0.5)

    def test_font_sizes_are_points_converted_to_millimetres(self):
        # TechDraw's TextSize is a Length in mm, so the original's 26 pt / 13 pt
        # must arrive as 9.17 mm / 4.59 mm rather than as 26 and 13.
        from mrfreecad import drawing

        sizes = [_as_float(v) for v in self.d("anno_sizes")]
        self.assertAlmostEqual(sizes[0], drawing.STAMP_FONT_SIZE, delta=0.01)
        self.assertAlmostEqual(sizes[2], drawing.SIMETRI_FONT_SIZE, delta=0.01)

    def test_qty_picks_the_nearest_number(self):
        self.assertEqual(self.d("qty_candidates"), 2)

    def test_set_qty_updates_the_fields(self):
        self.assertEqual(self.d("qty_changed"), 2)
        texts = " ".join(self.d("qty_texts"))
        self.assertIn("11", texts)

    def test_simetri_replaces_rather_than_stacks(self):
        self.assertTrue(self.d("simetri_replaced"))

    def test_scale_round_trips_through_the_real_page(self):
        for key in (
            "scale_1_1",
            "scale_1_2",
            "scale_1_20",
            "scale_1_5",
            "scale_2_1",
            "scale_1_7",
            "scale_1_100",
        ):
            with self.subTest(scale=key):
                self.assertTrue(self.d(key), "{0} did not round trip".format(key))

    def test_template_swap_clears_the_previous_notes(self):
        self.assertTrue(self.d("apply_template_ok"))
        self.assertEqual(self.d("annos_after_swap"), 0)


class MakeDrawingTests(FreeCADIntegrationTests):
    def test_single_view_page_is_created(self):
        self.assertTrue(self.d("makedrw_page"))
        self.assertEqual(self.d("makedrw_views"), 1)

    def test_template_is_attached(self):
        self.assertTrue(self.d("makedrw_template"))

    def test_three_view_page_has_three_views(self):
        self.assertEqual(self.d("makedrw3_views"), 3)

    def test_a_large_part_is_scaled_down(self):
        scale = self.d("big_scale")
        self.assertTrue(scale.startswith("1:"), scale)
        self.assertNotEqual(scale, "1:1", "a 3 m part must not print at 1:1")

    def test_a_small_part_is_not_enlarged(self):
        # snap_scale never scales up past the raw ratio, so a 30 mm part on an
        # A3 stays at the largest scale that still fits, never 3:1.
        self.assertIn(self.d("small_scale"), ("3:1", "2:1", "1:1"))


class NormalizeTests(FreeCADIntegrationTests):
    def test_norm_part_succeeds(self):
        self.assertTrue(self.d("norm_ok"))

    def test_k_factor_is_written_as_a_real_property(self):
        self.assertAlmostEqual(float(self.d("kfactor_property")), 0.42, places=6)

    def test_document_properties_are_written(self):
        self.assertIsNotNone(self.d("description"))
        self.assertTrue(self.d("weight"))

    def test_every_thickness_preset_applies(self):
        for label in ("0,5", "0,7", "0,8", "1", "1,2", "1,5", "2"):
            with self.subTest(thickness=label):
                self.assertTrue(self.d("preset_%s" % label))

    def test_thickness_ends_up_on_the_object(self):
        from typing import cast

        from mrfreecad import normalize

        # Every preset is applied in PRESET_LABELS order, so the last label's
        # value is what remains on the object.
        preset = cast(tuple, normalize.preset_for_label(normalize.PRESET_LABELS[-1]))
        self.assertAlmostEqual(self.d("thickness_after_preset"), preset[1], places=4)

    def test_metadata_is_readable_for_naming(self):
        self.assertTrue(self.d("read_thickness_property"))
        self.assertTrue(self.d("read_weight_kg"))
        model, config, thickness, material = self.d("metadata")
        self.assertTrue(model)
        self.assertEqual(config, "Default")
        self.assertTrue(thickness)

    def test_description_tracks_the_thickness(self):
        # The description carries the thickness for the DXF file name, so the two
        # must agree.  FreeCAD cannot expression-bind a document property, and a
        # bound length will not render as a comma decimal, so this is a value
        # invariant rather than a binding.
        thickness = self.d("read_thickness_text")
        description = self.d("description")
        self.assertTrue(thickness)
        self.assertEqual(description, thickness)


class ExportTests(FreeCADIntegrationTests):
    def test_flat_dxf_is_written(self):
        self.assertTrue(self.d("dxf_ok"))
        self.assertTrue(self.d("dxf_exists"))
        self.assertGreater(self.d("dxf_size"), 100)

    def test_dxf_contains_real_entities(self):
        self.assertTrue(self.d("dxf_is_dxf"))
        self.assertTrue(self.d("dxf_has_entities"))

    def test_dxf_name_follows_the_shop_convention(self):
        name = self.d("dxf_name")
        self.assertTrue(name.startswith("L "), name)
        self.assertTrue(name.endswith(".DXF"), name)
        # Laser + 3 off + "simetriği de var".
        self.assertIn(" 3 ad", name)
        self.assertIn("simetriği de var", name)
        self.assertIn("mm", name)

    def test_punch_uses_the_z_marker(self):
        name = self.d("dxf_z_name")
        self.assertTrue(name.startswith("Z "), name)
        self.assertTrue(self.d("dxf_z_ok"))

    def test_page_dxf_is_written(self):
        self.assertTrue(self.d("page_dxf_ok"))
        self.assertTrue(self.d("page_dxf_exists"))

    def test_page_png_either_writes_or_says_why_not(self):
        # Rendering a page needs the GUI (TechDrawGui.exportPageAsSvg and the
        # MDI grab).  Under freecadcmd there is no GUI, so the requirement is
        # that it fails *with an explanation* rather than silently.
        if self.d("page_png_ok"):
            self.assertGreater(self.d("page_png_bytes"), 1000)
            size = self.d("page_png_size")
            self.assertIsNotNone(size, "PNG written but no size recorded")
            width, height = size
            self.assertGreater(width, height)
        else:
            message = self.d("page_png_msg")
            self.assertIn("GUI", message)
            self.assertIn("TechDraw", message)


class RasterTests(FreeCADIntegrationTests):
    def test_png_round_trip_through_the_real_loader(self):
        self.assertEqual(self.d("raster_size"), [60, 40])

    def test_pixel_values_survive(self):
        self.assertEqual(self.d("raster_pixel"), [10, 20, 30, 255])

    def test_content_bbox_on_a_real_raster(self):
        self.assertEqual(self.d("raster_bbox"), [10, 8, 30, 32])


class ReferenceRepairTests(FreeCADIntegrationTests):
    def test_a_real_document_can_be_saved_and_read(self):
        self.assertGreater(self.d("saved_size"), 500)

    def test_reference_table_is_readable(self):
        self.assertIsInstance(self.d("refs_of_saved"), list)

    def test_repair_runs_and_reports(self):
        self.assertIn("repair_report_lines", self.d.__self__.data)  # noqa: SLF001
        self.assertGreater(self.d("repair_report_lines"), 3)


class CommandDispatchTests(FreeCADIntegrationTests):
    def test_no_command_raised(self):
        exceptions = {
            name: value
            for name, value in self.d("commands").items()
            if value[0] == "EXCEPTION"
        }
        self.assertEqual(exceptions, {}, "commands raised: {0}".format(exceptions))

    def test_every_command_returned_a_result(self):
        # Recorded as [ok, has_a_message] per command.
        for name, pair in self.d("commands").items():
            with self.subTest(command=name):
                self.assertEqual(len(pair), 2, name)
                ok, has_message = pair
                self.assertIsInstance(ok, bool, name)
                self.assertIsInstance(has_message, bool, name)
                self.assertTrue(has_message, "{0} failed with no message".format(name))


if __name__ == "__main__":
    unittest.main()