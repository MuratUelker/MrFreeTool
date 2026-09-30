"""A self-contained DXF writer for planar shapes.

Written because FreeCAD has no working shape-to-DXF path:

* ``Import.export`` routes STEP, IGES and BREP but silently writes nothing for
  ``.dxf`` (verified on FreeCAD 1.1) - it returns ``None`` and creates no file,
  which is the worst possible failure mode because the caller sees success.
* ``TechDraw.writeDXFPage`` / ``writeDXFView`` work, but only for pages and views.
  There is no ``writeDXFShape``.
* ``importDXF.export`` needs the Draft DXF libraries and does not write from a
  plain ``Part::Feature`` either.

So this module writes the file itself.

Format: **ASCII DXF R12 (``AC1009``)**.  R12 is the most widely accepted
version - every laser controller, nesting package and CAM post reads it - and it
needs no handles or object sections, which keeps the writer small and the output
easy to inspect.

Entities emitted:

* ``LINE`` for straight edges,
* ``ARC`` for circular arc edges,
* ``CIRCLE`` for full circles,
* ``POLYLINE`` (with ``VERTEX`` entries) for curves that have no native DXF
  equivalent, discretised to a chord tolerance so the cut path stays within
  manufacturing tolerance.

Bend lines are the reason this is written from scratch rather than delegated:
they have to land on their own DXF *layer* so a laser can ignore them, which
means the caller chooses what is a bend line, not a post-filter on the text.
"""

from __future__ import annotations

import math
import os
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

__all__ = [
    "DXF_VERSION",
    "DEFAULT_LAYER",
    "BEND_LAYER",
    "CUT_LAYER",
    "write_shape",
    "write_edges",
    "shape_bbox",
]

#: DXF version string written into the header.
DXF_VERSION = "AC1009"  # R12

#: Layer names.
CUT_LAYER = "CUT"
BEND_LAYER = "BEND"

#: Layer used when nothing more specific is given.
DEFAULT_LAYER = CUT_LAYER

#: Maximum chord deviation when a curve is turned into a polyline, in
#: millimetres.  0.02 mm is well inside sheet-metal cutting tolerance and keeps
#: the file from exploding in vertex count.
DEFAULT_DEFLECTION = 0.02

#: A vertex count ceiling per discretised curve, as a guard against a spline
#: whose discretisation would otherwise run away.
MAX_POINTS_PER_CURVE = 512


def shape_bbox(shape: Any) -> Tuple[float, float, float, float]:
    """``(xmin, ymin, xmax, ymax)`` of ``shape`` projected onto XY."""
    box = shape.BoundBox
    return (box.XMin, box.YMin, box.XMax, box.YMax)


# ---------------------------------------------------------------------------
# Entity construction
# ---------------------------------------------------------------------------
def _group(code: int, value: Any) -> List[str]:
    return [str(int(code)), str(value)]


def _pair(code: int, value: float) -> List[str]:
    return [str(int(code)), _num(value)]


def _num(value: float) -> str:
    """Format a coordinate.

    DXF reals need a decimal point even when the value is whole, and three
    decimals is 1 micron - far finer than any sheet-metal process.
    """
    number = float(value)
    if number == 0.0:
        return "0.0"
    text = "%.3f" % number
    if text in ("-0.000",):
        return "0.0"
    return text


def _angle(radians: float) -> str:
    """Format an angle in DXF degrees, counter-clockwise from the +X axis."""
    return "%.6f" % (math.degrees(radians) % 360.0)


def line_entity(x1: float, y1: float, x2: float, y2: float, layer: str) -> List[str]:
    out: List[str] = []
    out += _group(0, "LINE")
    out += _group(8, layer)
    out += _pair(10, x1) + _pair(20, y1) + _pair(30, 0.0)
    out += _pair(11, x2) + _pair(21, y2) + _pair(31, 0.0)
    return out


def circle_entity(cx: float, cy: float, radius: float, layer: str) -> List[str]:
    out: List[str] = []
    out += _group(0, "CIRCLE")
    out += _group(8, layer)
    out += _pair(10, cx) + _pair(20, cy) + _pair(30, 0.0)
    out += _pair(40, radius)
    return out


def arc_entity(
    cx: float, cy: float, radius: float, start_rad: float, end_rad: float, layer: str
) -> List[str]:
    out: List[str] = []
    out += _group(0, "ARC")
    out += _group(8, layer)
    out += _pair(10, cx) + _pair(20, cy) + _pair(30, 0.0)
    out += _pair(40, radius)
    out += _group(50, _angle(start_rad))
    out += _group(51, _angle(end_rad))
    return out


def polyline_entity(points: Sequence[Tuple[float, float]], layer: str, closed: bool = False) -> List[str]:
    """A classic R12 ``POLYLINE``/``VERTEX`` chain.

    ``LWPOLYLINE`` would be more compact, but it was introduced in R14 and some
    laser controllers still choke on it, so the R12 form is used deliberately.
    """
    if len(points) < 2:
        return []
    out: List[str] = []
    out += _group(0, "POLYLINE")
    out += _group(8, layer)
    out += _group(66, 1)  # vertices follow
    out += _group(70, 1 if closed else 0)
    for x, y in points:
        out += _group(0, "VERTEX")
        out += _group(8, layer)
        out += _pair(10, x) + _pair(20, y) + _pair(30, 0.0)
    out += _group(0, "SEQEND")
    return out


# ---------------------------------------------------------------------------
# Edge conversion
# ---------------------------------------------------------------------------
def _circle_of(edge: Any) -> Optional[Tuple[float, float, float]]:
    """``(cx, cy, r)`` for an edge that lies on a circle, else ``None``."""
    try:
        curve = edge.Curve
    except Exception:
        return None
    name = type(curve).__name__
    if name not in ("Circle", "ArcOfCircle"):
        return None
    try:
        centre = curve.Center
        axis = curve.Axis
        # A circle in a plane other than XY projects to an ellipse; refusing it
        # is better than emitting a circle of the wrong size.
        if abs(axis.x) > 1e-9 or abs(axis.y) > 1e-9:
            return None
        return (centre.x, centre.y, float(curve.Radius))
    except Exception:
        return None


def _arc_range(edge: Any) -> Optional[Tuple[float, float]]:
    """``(start, end)`` parameter range in radians for an arc edge."""
    try:
        first, last = edge.FirstParameter, edge.LastParameter
    except Exception:
        return None
    if last <= first:
        last += 2.0 * math.pi
    return (float(first), float(last))


def _discretize(edge: Any, deflection: float) -> List[Tuple[float, float]]:
    """Points along ``edge``, from the curve type when possible."""
    for kwargs in ({"Deflection": deflection}, {"Number": 64}, {}):
        try:
            points = edge.discretize(**kwargs) if kwargs else edge.discretize(16)
        except Exception:
            continue
        if points and len(points) >= 2:
            return [(float(p.x), float(p.y)) for p in points]
    try:
        start = edge.valueAt(edge.FirstParameter)
        end = edge.valueAt(edge.LastParameter)
        return [(float(start.x), float(start.y)), (float(end.x), float(end.y))]
    except Exception:
        return []


#: Edges shorter than this in the XY projection are dropped.  DXF is 2D, so an
#: edge perpendicular to the sheet - a vertical edge on a formed part, or a
#: construction line in Z - projects to a point.  Writing it as a zero-length
#: LINE produces geometry a cutting controller may reject or try to cut.
MIN_PROJECTED_LENGTH = 1e-6


def edge_entities(edge: Any, layer: str, deflection: float = DEFAULT_DEFLECTION) -> List[List[str]]:
    """Convert one ``Part.Edge`` into DXF entity groups."""
    circle = _circle_of(edge)
    if circle is not None:
        cx, cy, radius = circle
        if radius <= MIN_PROJECTED_LENGTH:
            return []
        arc_range = _arc_range(edge)
        if arc_range is not None:
            start, end = arc_range
            if end - start >= 2.0 * math.pi - 1e-9:
                return [circle_entity(cx, cy, radius, layer)]
            return [arc_entity(cx, cy, radius, start, end, layer)]
        return [circle_entity(cx, cy, radius, layer)]

    points = _discretize(edge, deflection)
    if len(points) < 2:
        return []

    # A straight edge that lands on a circle should still be a LINE: a chamfer or
    # a straight tangent is genuinely linear, not an arc.
    try:
        is_line = type(edge.Curve).__name__ == "Line"
    except Exception:
        is_line = False

    if is_line:
        x1, y1 = points[0]
        x2, y2 = points[-1]
        if math.hypot(x2 - x1, y2 - y1) <= MIN_PROJECTED_LENGTH:
            return []  # perpendicular to the sheet: nothing to cut
        return [line_entity(x1, y1, x2, y2, layer)]

    # A polyline whose XY footprint collapsed to nothing is equally uncuttable.
    if _polyline_length(points) <= MIN_PROJECTED_LENGTH:
        return []
    return [polyline_entity(points, layer)]


def _polyline_length(points: Sequence[Tuple[float, float]]) -> float:
    total = 0.0
    for index in range(1, len(points)):
        total += math.hypot(points[index][0] - points[index - 1][0], points[index][1] - points[index - 1][1])
    return total


# ---------------------------------------------------------------------------
# Document assembly
# ---------------------------------------------------------------------------
def _header(bbox: Optional[Tuple[float, float, float, float]]) -> List[str]:
    out: List[str] = []
    out += _group(0, "SECTION") + _group(2, "HEADER")
    out += _group(9, "$ACADVER") + _group(1, DXF_VERSION)
    out += _group(9, "$INSUNITS") + _group(70, 4)  # 4 = millimetres
    if bbox is not None:
        xmin, ymin, xmax, ymax = bbox
        out += _group(9, "$EXTMIN") + _pair(10, xmin) + _pair(20, ymin) + _pair(30, 0.0)
        out += _group(9, "$EXTMAX") + _pair(10, xmax) + _pair(20, ymax) + _pair(30, 0.0)
    out += _group(0, "ENDSEC")
    return out


def _layer_table(layers: Sequence[str], colors: Optional[Dict[str, int]] = None) -> List[str]:
    """A LAYER table, so the layers a laser filters on actually exist."""
    colors = colors or {}
    unique = []
    for name in layers:
        if name and name not in unique:
            unique.append(name)
    if not unique:
        unique = [DEFAULT_LAYER]

    out: List[str] = []
    out += _group(0, "SECTION") + _group(2, "TABLES")
    out += _group(0, "TABLE") + _group(2, "LAYER") + _group(70, len(unique))
    for name in unique:
        out += _group(0, "LAYER")
        out += _group(2, name)
        out += _group(70, 0)
        out += _group(62, int(colors.get(name, 7)))
        out += _group(6, "CONTINUOUS")
    out += _group(0, "ENDTAB")
    out += _group(0, "ENDSEC")
    return out


def _entities(entities: Iterable[List[str]]) -> List[str]:
    out: List[str] = []
    out += _group(0, "SECTION") + _group(2, "ENTITIES")
    for entity in entities:
        out += entity
    out += _group(0, "ENDSEC")
    return out


def _eof() -> List[str]:
    return _group(0, "EOF")


def build_document(
    entities: Sequence[List[str]],
    layers: Sequence[str],
    bbox: Optional[Tuple[float, float, float, float]] = None,
    layer_colors: Optional[Dict[str, int]] = None,
) -> str:
    """Assemble a complete R12 DXF as text."""
    lines: List[str] = []
    lines += _header(bbox)
    lines += _layer_table(layers, layer_colors)
    lines += _entities(entities)
    lines += _eof()
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def write_edges(
    edges: Sequence[Any],
    path: str,
    bend_edges: Optional[Sequence[Any]] = None,
    deflection: float = DEFAULT_DEFLECTION,
    cut_layer: str = CUT_LAYER,
    bend_layer: str = BEND_LAYER,
) -> Tuple[bool, str]:
    """Write ``edges`` to ``path`` as DXF.  Returns ``(ok, message)``.

    ``bend_edges``, when given, go on their own layer so a laser configured to
    cut only ``CUT`` ignores them.
    """
    if not path:
        return (False, "no output path")
    entities: List[List[str]] = []
    layers: List[str] = []

    for edge in edges or []:
        groups = edge_entities(edge, cut_layer, deflection)
        if groups:
            entities.extend(groups)
            layers.append(cut_layer)

    for edge in bend_edges or []:
        groups = edge_entities(edge, bend_layer, deflection)
        if groups:
            entities.extend(groups)
            layers.append(bend_layer)

    if not entities:
        return (False, "the shape produced no drawable edges")

    bbox = _bbox_of_points(entities)
    text = build_document(entities, layers, bbox)
    return _write_text(path, text)


def write_shape(
    shape: Any,
    path: str,
    bend_edges: Optional[Sequence[Any]] = None,
    deflection: float = DEFAULT_DEFLECTION,
    cut_layer: str = CUT_LAYER,
    bend_layer: str = BEND_LAYER,
    skip_interior: bool = False,
    planarity_tolerance: float = 3.0,
) -> Tuple[bool, str]:
    """Write ``shape``'s edges to ``path`` as DXF.

    ``skip_interior`` drops edges whose midpoint projects strictly inside
    another closed wire - the interior seam lines of a blank that a laser would
    otherwise cut as part of the profile.

    It is **off by default**.  A correct unfold already contains only the outer
    contour, so the filter normally has nothing to do, and its test is a 2D
    containment check: on anything with real depth it would delete genuine
    geometry (a box's vertical edges project inside the projection of its top
    face).  Deleting edges from a file that goes to a laser is not a trade worth
    making for a cleanup a good unfold does not need, so it is opt-in and
    additionally gated on the shape actually looking like a flat blank.
    """
    if shape is None:
        return (False, "no shape to write")

    try:
        edges = list(shape.Edges)
    except Exception as exc:
        return (False, "shape edges unreadable: {0}".format(exc))
    if not edges:
        return (False, "the shape has no edges")

    if skip_interior and is_planar(shape, planarity_tolerance):
        edges = _drop_interior_edges(edges)

    bend = list(bend_edges) if bend_edges else None
    return write_edges(
        edges,
        path,
        bend_edges=bend,
        deflection=deflection,
        cut_layer=cut_layer,
        bend_layer=bend_layer,
    )


def is_planar(shape: Any, tolerance: float = 3.0) -> bool:
    """True when ``shape`` is essentially a flat blank lying parallel to XY.

    Judged purely on depth: sheet metal is a fraction of a millimetre up to a
    few millimetres thick, while a formed or machined part is far deeper.  A
    3 mm default keeps ordinary sheet and rejects anything with structure.
    """
    try:
        box = shape.BoundBox
    except Exception:
        return False
    return box.ZLength <= max(0.0, float(tolerance))


def _drop_interior_edges(edges: Sequence[Any]) -> List[Any]:
    """Remove edges lying strictly inside a wire that encloses them."""
    try:
        import Part  # type: ignore
    except Exception:
        return list(edges)

    try:
        from FreeCAD import Vector  # type: ignore
    except Exception:  # pragma: no cover - inside FreeCAD only
        return list(edges)

    # Collect the closed wires and test whether an edge's midpoint is inside any.
    wires = []
    try:
        wires = [Part.Wire(e) for e in Part.sortEdges(list(edges))]
    except Exception:
        wires = []

    closed = []
    for wire in wires:
        try:
            if wire.isClosed():
                closed.append(wire)
        except Exception:
            continue
    if not closed:
        return list(edges)

    keep = []
    for edge in edges:
        try:
            middle = edge.valueAt((edge.FirstParameter + edge.LastParameter) / 2.0)
        except Exception:
            keep.append(edge)
            continue
        point = Vector(middle.x, middle.y, middle.z)
        inside = False
        for wire in closed:
            try:
                if not wire.isClosed():
                    continue
                # An edge of the wire itself is on the boundary, not inside it.
                if wire.distToShape(Part.Vertex(point))[0] < 1e-6:
                    inside = False
                    break
                if wire.isInside(point, 1e-6, True):
                    inside = True
                    break
            except Exception:
                continue
        if not inside:
            keep.append(edge)
    return keep


def _bbox_of_points(entities: Sequence[Sequence[str]]) -> Optional[Tuple[float, float, float, float]]:
    """Bounding box implied by the entity coordinates, for the header."""
    xs: List[float] = []
    ys: List[float] = []
    for entity in entities:
        for index in range(0, len(entity) - 1, 2):
            code = entity[index]
            if code in ("10", "11"):
                xs.append(float(entity[index + 1]))
            elif code in ("20", "21"):
                ys.append(float(entity[index + 1]))
    if not xs or not ys:
        return None
    return (min(xs), min(ys), max(xs), max(ys))


def _write_text(path: str, text: str) -> Tuple[bool, str]:
    """Write ``text`` to ``path`` atomically."""
    directory = os.path.dirname(os.path.abspath(path))
    if directory and not os.path.isdir(directory):
        try:
            os.makedirs(directory)
        except OSError as exc:
            return (False, "output folder could not be created: {0}".format(exc))
    temp = path + ".part"
    try:
        with open(temp, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        os.replace(temp, path)
    except OSError as exc:
        try:
            if os.path.exists(temp):
                os.remove(temp)
        except OSError:
            pass
        return (False, "DXF could not be written: {0}".format(exc))
    return (True, path)