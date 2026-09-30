# Changelog

All notable changes to MrFreeTool are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[semantic versioning](https://semver.org/).

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
- Bend-line filtering, quantity, *simetriği de var* and `%R` options.
- Whole-page DXF export including annotations.
- Sheet PNG export at paper size and 300 dpi.

**Normalize**
- `Norm Part`: thickness, K-factor, bend radius, relief type and the
  `Description` / `Weight` / `Material` document properties, with `Description`
  expression-bound to the thickness so it cannot drift.
- Thickness presets 0,5 / 0,7 / 0,8 / 1 / 1,2 / 1,5 / 2 mm carrying the
  original's K-factor and bend-radius pairings.
- Per-face colour randomisation with exact restore.

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
  result object instead of raising.
- 202 unit tests, no FreeCAD required, plus an install script.

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

[1.0.0]: https://github.com/MuratUelker/MrFreeTool/releases/tag/v1.0.0
