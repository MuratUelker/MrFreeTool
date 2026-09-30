"""Tests for :mod:`mrfreecad.dxf` - the DXF writer.

The writer exists because FreeCAD cannot export a shape to DXF, so these tests
check the output as *text*: the structure a DXF R12 reader requires, and the
geometry that must not appear.
"""

import math
import os
import tempfile
import unittest

from tests import _bootstrap  # noqa: F401  (path setup)

from mrfreecad import dxf


class Circle:
    """Named exactly as ``Part.Circle``.

    The writer detects geometry by ``type(curve).__name__``, which is how
    FreeCAD's Part bindings actually expose it, so the fake has to match.
    """

    def __init__(self, cx, cy, radius):
        self.Center = FakeVector(cx, cy, 0.0)
        self.Axis = FakeVector(0.0, 0.0, 1.0)
        self.Radius = radius


class ArcOfCircle(Circle):
    """Named exactly as ``Part.ArcOfCircle``."""


class Line:
    """Named exactly as ``Part.Line``."""


class UnknownCurve:
    """A curve type the writer has no native DXF mapping for."""


class FakeVector:
    def __init__(self, x, y, z):
        self.x, self.y, self.z = x, y, z


class FakeVertex:
    def __init__(self, x, y):
        self.x, self.y = x, y


class FakeEdge:
    """Enough of ``Part.Edge`` for the writer."""

    def __init__(self, points, curve=None):
        self._points = [FakeVertex(x, y) for x, y in points]
        self.Curve = curve if curve is not None else Line()
        self.FirstParameter = 0.0
        self.LastParameter = 1.0

    def discretize(self, *args, **kwargs):
        return self._points

    def valueAt(self, parameter):  # noqa: N802 - FreeCAD API name
        if parameter <= self.FirstParameter:
            return self._points[0]
        return self._points[-1]


class FakeShape:
    def __init__(self, edges):
        self.Edges = list(edges)


def codes_of(entities):
    """Flatten entity groups into a single list of tokens."""
    out = []
    for entity in entities:
        out.extend(entity)
    return out


class GeometryTests(unittest.TestCase):
    def test_straight_edge_becomes_a_line(self):
        edge = FakeEdge([(0.0, 0.0), (10.0, 5.0)])
        tokens = codes_of(dxf.edge_entities(edge, "CUT"))
        self.assertIn("LINE", tokens)
        self.assertIn("CUT", tokens)
        # Coordinates present, three decimals, as DXF reals require.
        self.assertIn("10.000", tokens)
        self.assertIn("5.000", tokens)

    def test_vertical_edge_is_dropped(self):
        # A vertical edge projects to a point: nothing for a laser to cut, and a
        # zero-length LINE can make a controller reject the file.
        edge = FakeEdge([(3.0, 4.0), (3.0, 4.0)])
        self.assertEqual(dxf.edge_entities(edge, "CUT"), [])

    def test_nearly_zero_edge_is_dropped(self):
        edge = FakeEdge([(0.0, 0.0), (1e-9, 0.0)])
        self.assertEqual(dxf.edge_entities(edge, "CUT"), [])

    def test_full_circle_edge_becomes_a_circle(self):
        edge = FakeEdge([(0.0, 0.0), (0.0, 0.0)], curve=Circle(5.0, 7.0, 3.0))
        edge.LastParameter = 2.0 * math.pi
        tokens = codes_of(dxf.edge_entities(edge, "CUT"))
        self.assertIn("CIRCLE", tokens)
        self.assertIn("3.000", tokens)  # radius

    def test_partial_arc_becomes_an_arc(self):
        edge = FakeEdge([(0.0, 0.0), (0.0, 0.0)], curve=Circle(5.0, 7.0, 3.0))
        edge.FirstParameter = 0.0
        edge.LastParameter = math.pi / 2.0
        tokens = codes_of(dxf.edge_entities(edge, "CUT"))
        self.assertIn("ARC", tokens)
        self.assertIn("50", tokens)  # start angle code
        self.assertIn("51", tokens)  # end angle code

    def test_curve_in_another_plane_is_not_written_as_a_circle(self):
        # A circle whose axis is not Z projects to an ellipse.  Emitting a CIRCLE
        # would put the wrong geometry on the sheet, so it must be discretised
        # into a polyline of its actual projection instead.
        class Tilted(Circle):
            def __init__(self):
                super().__init__(0.0, 0.0, 5.0)
                self.Axis = FakeVector(1.0, 0.0, 0.0)

        edge = FakeEdge([(0.0, 0.0), (1.0, 1.0), (2.0, 0.0)], curve=Tilted())
        tokens = codes_of(dxf.edge_entities(edge, "CUT"))
        self.assertNotIn("CIRCLE", tokens)
        self.assertIn("POLYLINE", tokens)

    def test_curved_edge_becomes_a_polyline(self):
        edge = FakeEdge([(0.0, 0.0), (5.0, 1.0), (10.0, 0.0)], curve=UnknownCurve())
        tokens = codes_of(dxf.edge_entities(edge, "CUT"))
        self.assertIn("POLYLINE", tokens)
        self.assertIn("VERTEX", tokens)
        self.assertIn("SEQEND", tokens)

    def test_empty_edge_is_ignored(self):
        self.assertEqual(dxf.edge_entities(FakeEdge([(1.0, 1.0)]), "CUT"), [])


class DocumentTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.folder = self._tmp.name
        self.addCleanup(self._tmp.cleanup)

    def _write(self, edges, name="t.dxf", **kwargs):
        shape = FakeShape(edges)
        path = os.path.join(self.folder, name)
        ok, message = dxf.write_shape(shape, path, **kwargs)
        return (ok, message, path)

    def test_round_rectangle_produces_a_complete_document(self):
        rect = [
            FakeEdge([(0.0, 0.0), (10.0, 0.0)]),
            FakeEdge([(10.0, 0.0), (10.0, 5.0)]),
            FakeEdge([(10.0, 5.0), (0.0, 5.0)]),
            FakeEdge([(0.0, 5.0), (0.0, 0.0)]),
        ]
        ok, _msg, path = self._write(rect)
        self.assertTrue(ok)

        with open(path, encoding="utf-8") as handle:
            text = handle.read()

        # The structure a DXF R12 reader walks top to bottom.
        self.assertTrue(text.startswith("0\nSECTION"))
        for token in ("HEADER", "$ACADVER", dxf.DXF_VERSION, "TABLES", "LAYER", "ENTITIES", "ENDSEC", "EOF"):
            self.assertIn(token, text, token)
        self.assertIn("$INSUNITS", text)
        self.assertTrue(text.rstrip().endswith("EOF"))

    def test_units_are_millimetres(self):
        # $INSUNITS group 70 = 4 means millimetres; a wrong unit setting scales
        # every cut path by 1000.
        _ok, _m, path = self._write([FakeEdge([(0.0, 0.0), (1.0, 0.0)])], "u.dxf")
        with open(path, encoding="utf-8") as handle:
            lines = handle.read().splitlines()
        index = lines.index("$INSUNITS")
        self.assertEqual(lines[index + 1], "70")
        self.assertEqual(lines[index + 2], "4")

    def test_layer_table_lists_every_layer_used(self):
        rect = [FakeEdge([(0.0, 0.0), (10.0, 0.0)])]
        _ok, _m, path = self._write(rect, "lay.dxf", bend_edges=[FakeEdge([(0.0, 0.0), (1.0, 1.0)])])
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn("CUT", text)
        self.assertIn("BEND", text)

    def test_bend_edges_land_on_their_own_layer(self):
        _ok, _m, path = self._write(
            [FakeEdge([(0.0, 0.0), (10.0, 0.0)])],
            "bend.dxf",
            bend_edges=[FakeEdge([(2.0, 2.0), (8.0, 2.0)])],
        )
        with open(path, encoding="utf-8") as handle:
            lines = handle.read().splitlines()
        # Find the second LINE's layer code; a bend edge is not on CUT.
        layers = [lines[i + 1] for i, line in enumerate(lines) if line == "8"]
        self.assertIn("CUT", layers)
        self.assertIn("BEND", layers)

    def test_extents_are_written(self):
        _ok, _m, path = self._write([FakeEdge([(5.0, 7.0), (25.0, 7.0)])], "ext.dxf")
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn("$EXTMIN", text)
        self.assertIn("$EXTMAX", text)

    def test_a_shape_with_no_edges_is_refused(self):
        ok, message, path = self._write([])
        self.assertFalse(ok)
        self.assertIn("no edges", message)
        self.assertFalse(os.path.exists(path))

    def test_missing_shape_is_refused(self):
        ok, message = dxf.write_shape(None, os.path.join(self.folder, "x.dxf"))
        self.assertFalse(ok)
        self.assertIn("no shape", message)

    def test_output_folder_is_created(self):
        nested = os.path.join(self.folder, "a", "b", "c.dxf")
        ok, _ = dxf.write_shape(FakeShape([FakeEdge([(0.0, 0.0), (1.0, 1.0)])]), nested)
        self.assertTrue(ok)
        self.assertTrue(os.path.isfile(nested))

    def test_no_part_file_survives(self):
        _ok, _m, path = self._write([FakeEdge([(0.0, 0.0), (1.0, 0.0)])], "part.dxf")
        self.assertFalse(os.path.exists(path + ".part"))

    def test_every_coordinate_is_a_dxf_real(self):
        # A bare integer where a real is required is a common malformed-DXF bug.
        _ok, _m, path = self._write([FakeEdge([(0.0, 0.0), (10.0, 0.0)])], "real.dxf")
        with open(path, encoding="utf-8") as handle:
            lines = handle.read().splitlines()
        for index, line in enumerate(lines):
            if line in ("10", "11", "20", "21", "30", "31", "40"):
                value = lines[index + 1]
                self.assertIn(".", value, "coordinate {0} is not a real: {1}".format(line, value))


class PlanarityTests(unittest.TestCase):
    class FakeBox:
        def __init__(self, x, y, z):
            self.BoundBox = type(
                "Box", (), {"XLength": x, "YLength": y, "ZLength": z}
            )()

    def test_a_thin_sheet_is_planar(self):
        self.assertTrue(dxf.is_planar(self.FakeBox(300.0, 200.0, 1.0)))
        self.assertTrue(dxf.is_planar(self.FakeBox(50.0, 40.0, 0.5)))

    def test_a_formed_part_is_not_planar(self):
        self.assertFalse(dxf.is_planar(self.FakeBox(300.0, 200.0, 120.0)))

    def test_thick_plate_is_not_planar_by_default(self):
        self.assertFalse(dxf.is_planar(self.FakeBox(300.0, 200.0, 10.0)))
        # ...but the threshold is the caller's to set.
        self.assertTrue(dxf.is_planar(self.FakeBox(300.0, 200.0, 10.0), tolerance=12.0))

    def test_missing_shape_is_not_planar(self):
        self.assertFalse(dxf.is_planar(object()))


class NumberFormatTests(unittest.TestCase):
    def test_always_prints_a_decimal_point(self):
        self.assertIn(".", dxf._num(5.0))
        self.assertIn(".", dxf._num(0.0))

    def test_zero_is_normalised(self):
        self.assertEqual(dxf._num(0.0), "0.0")
        self.assertEqual(dxf._num(-0.0), "0.0")

    def test_negative_zero_is_cleaned(self):
        self.assertEqual(dxf._num(-1e-9), "0.0")

    def test_three_decimals_is_micron_resolution(self):
        self.assertEqual(dxf._num(1.23456), "1.235")

    def test_angle_is_wrapped_into_degrees(self):
        self.assertEqual(dxf._angle(math.pi), "180.000000")
        self.assertEqual(dxf._angle(-math.pi / 2), "270.000000")


if __name__ == "__main__":
    unittest.main()