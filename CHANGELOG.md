# Changelog

All notable changes to MrFreeTool are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[semantic versioning](https://semver.org/).

## [Unreleased]

### Fixed

Defects found by running the addon against a real FreeCAD 1.1.3, plus a new
integration test suite that would have caught them:

- Stock TechDraw templates are discovered again. They live in the `ISO/` and
  `ASME/` subdirectories, so the previous flat scan found none and *Make Drw*
  failed out of the box.
- A template attaches through `page.Template`; `page.addView()` rejects it.
- Page scale is set through the page's `Scale` float. `DrawPage` has no
  `ScaleType` — that lives on the views.
- Annotation and view positions survive. TechDraw centres a view when it joins a
  page, discarding any position set beforehand.
- Font sizes are converted from points to millimetres, because TechDraw's
  `TextSize` is a `Length`.
- `Norm Part` no longer segfaults FreeCAD. FreeCAD 1.1's `Document.Material` is
  an `App::PropertyMap`; assigning a string to it crashes the interpreter. The
  material goes to `MrFreeMaterial`, and any write whose type does not match an
  existing property is refused rather than attempted.
- Page scale no longer overwrites a per-view `Custom` scale, which was a
  deliberate choice by the user.

### Added

- `mrfreecad/dxf.py`: an ASCII DXF R12 writer for shapes, with profile and bend
  lines on separate layers. FreeCAD cannot export a shape to DXF — `Import.export`
  writes no file for a `.dxf` target and there is no `TechDraw.writeDXFShape`.
- 42 integration tests that run against a real `FreeCADCmd`, skipping themselves
  when none is installed.
- `Description` is written alongside the thickness rather than expression-bound,
  with the reason recorded: a document property cannot be expression-bound, and
  an object binding yields a quantity that will not render as a comma decimal.

## [1.0.0] — 2026-10-01

First release. A port of the SolidWorks tool `MrSWTool` to FreeCAD, covering the
same production jobs on FreeCAD geometry.

### Added

**Drawing**
- `Make Drw`: creates a TechDraw page from the selected part — template
  applied, three views, flat pattern in place of the base view, longest edge
  turned horizontal, largest standard scale that still fits.
- Template swapping (`Replace Sheet`, `Ayazsa`, `Karadeniz`) with the previous
  format's notes cleared first, so two formats cannot overlap.
- `Zımba` and `Lazer` notes at the original's millimetre positions, 26 pt bold.
- `Simetriği var` note, replacing any previous one instead of stacking.
- `Qty` field updates via the nearest-number rule, so templates with several
  numeric fields are handled correctly.
- Page scale ladder 3:1 … 1:N, matching the original slider.

**Dxf**
- Flat pattern DXF export with the shop's file-naming scheme, byte-compatible
  with the SolidWorks tool, so a mixed shop produces one naming series.
- Own ASCII DXF R12 writer (`mrfreecad/dxf.py`). FreeCAD cannot export a shape
  to DXF at all: `Import.export` creates no file for a `.dxf` target and there
  is no `TechDraw.writeDXFShape`, so the writer is written from scratch. Emits
  `LINE`, `ARC`, `CIRCLE` and R12 `POLYLINE`, in millimetres, with the profile on
  a `CUT` layer and bend lines on `BEND`. Edges perpendicular to the sheet are
  dropped rather than written as zero-length lines.
- Whole-page DXF export including annotations.
- Sheet PNG export at paper size and 300 dpi.

**Normalize**
- `Norm Part`: thickness, K-factor, bend radius, relief type and the
  `Description` / `Weight` / `Material` document properties.
- Thickness presets 0,5 / 0,7 / 0,8 / 1 / 1,2 / 1,5 / 2 mm carrying the
  original's K-factor and bend-radius pairings.
- Per-face colour randomisation with exact restore.
- Property writes are guarded by a type check: FreeCAD 1.1 gave `Document` a
  built-in `Material` property of type `App::PropertyMap`, and assigning a
  string to it segfaults the interpreter inside `PropertyMap::setPyObject`. The
  material is written to `MrFreeMaterial` and any incompatible assignment is
  refused rather than attempted.

**Browse**
- `Reset Ref`: external link repair across a project, read and rewritten from
  the `Document.xml` XLink table without opening any model. Unicode
  normalisation, name-based matching and an atomic archive rewrite.
- `Screen Cap`: A4 capture at 300 dpi, auto-numbered, background flooded to
  white and content trimmed to its bounding box.
- `make pdf`: combines captures into one `montaj talimatı.pdf` via `QPdfWriter`.
- Company logo stamping, cleaning both firms' rectangles before drawing the
  selected logo at its own position.

**Infrastructure**
- Four-tab Qt panel generated from a single command table, so the panel and the
  command bar cannot drift apart.
- Settings dialog, with the logo placement the SolidWorks version read out of
  the sheet format file.
- Scrollable report window, replacing the original's `MessageBox` for reports
  that exceed the screen height.
- Settings persist in FreeCAD's own preference tree
  (`BaseApp/Preferences/Mod/MrFreeTool`).
- Works on PySide2 and PySide6, so FreeCAD 0.21 and 1.x are both supported.
- Usable from the Python console and from macros; every operation returns a
  result object instead of raising, so a command can never propagate an
  exception into FreeCAD's menu handling.
- 294 unit tests plus 42 integration tests that run against a real FreeCAD,
  and an install script.

### Verified against FreeCAD 1.1.3

Several defects were only found by running the addon in a real interpreter and
are fixed here:

- **Stock templates were not found.** FreeCAD keeps them under
  `Templates/ISO/` and `Templates/ASME/`, so the non-recursive scan that
  shipped found nothing and left *Make Drw* with no fallback at all.
- **Templates cannot be added with `page.addView()`.** The page rejects a
  template; it attaches through `page.Template`.
- **`DrawPage` has no `ScaleType`.** That property is on the views; the page is
  driven by its `Scale` float.
- **Annotation and view positions were being discarded.** TechDraw centres a
  view when it joins a page, so `X`/`Y` assigned beforehand are lost; both are
  now set after `addView`.
- **Font sizes were nearly three times too large.** TechDraw's `TextSize` is a
  `Length` in millimetres, not points, so the original's 26 pt is now converted
  to 9.17 mm and 13 pt to 4.59 mm.
- **Writing `Material` segfaulted FreeCAD**, as described above.

### Known limitations

- **No built-in unfold.** FreeCAD has no sheet-metal unfold, so the DXF export
  needs a flat pattern from the SheetMetal add-on or an already-flat part. The
  tool refuses rather than writing a wrong DXF.
- **No flange insertion.** FreeCAD has no sheet-metal feature tree, so the
  thickness buttons write the metadata rather than inserting a flange. The
  values the DXF name, drawing and ERP read are preserved exactly.
- **Logo placement is configured, not extracted.** A `.slddrt` sheet format has
  no FreeCAD equivalent, so logo images and positions are entered in settings
  instead of scraped from the template.
- **`Description` is not expression-bound to the thickness.** A document
  property cannot be expression-bound in FreeCAD at all, and binding on the
  object yields a quantity that will not render as the comma-decimal string the
  DXF file name needs. The two are written together instead.
- **Page-to-PNG needs the GUI.** Rendering a page uses `TechDrawGui`; from
  `freecadcmd` it reports why rather than writing a blank image.

[1.0.0]: https://github.com/MuratUelker/MrFreeTool/releases/tag/v1.0.0
[Unreleased]: https://github.com/MuratUelker/MrFreeTool/compare/v1.0.0...HEAD
