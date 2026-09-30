# MrFreeTool

FreeCAD workbench for sheet-metal production, ported from the SolidWorks tool
[`MrSWTool`](https://github.com/MuratUelker/MrSWTool).

It does the same jobs on FreeCAD geometry: stamps the antet notes on a drawing,
creates a drawing from a flat pattern with an automatic scale, exports the flat
pattern to DXF and the sheet to PNG, normalises a part's thickness / K-factor /
material metadata, produces A4 screen captures and a one-PDF assembly sheet, and
repairs broken external document links across a project.

Open source, MIT licensed.

---

## Install

**FreeCAD Addon Manager** — search for *MrFreeTool*, install, restart FreeCAD.

**Manually**

```bash
git clone https://github.com/MuratUelker/MrFreeTool.git
./MrFreeTool/scripts/install.sh          # copy into the FreeCAD Mod directory
./MrFreeTool/scripts/install.sh --link   # symlink, for development
```

Restart FreeCAD, then select the **MrFreeTool** workbench from the workbench
selector and press its toolbar button.

Requires FreeCAD 0.20 or newer. Works with both PySide2 (Qt5) and PySide6 (Qt6),
so 0.21 and 1.x are both fine.

## First-time setup

Everything is configured from the panel's **⚙** button (or *Ayarlar*). Two things
are worth setting before the first job:

1. **Drawing → Yatay / Dikey şablon** — point these at your TechDraw templates
   (`.svg`). These replace the SolidWorks `.slddrt` sheet formats.
2. **Logo → Ayazsa / Karadeniz** — choose the logo PNG for each firm and its
   position in millimetres on the sheet.

Without a template, *Make Drw* falls back to FreeCAD's bundled A3 landscape
blank, so it works out of the box but will not carry your own title block.

## The four tabs

### Drawing

| Action | What it does |
|---|---|
| **Make Drw** | New TechDraw page from the selected part: sheet format applied, three views, flat pattern replacing the base view, longest edge turned horizontal, and the largest standard scale that still fits. |
| **Replace Sheet / Ayazsa / Karadeniz** | Swap the page's template. Old-format notes are cleared first so the two do not overlap. |
| **Zımba / Lazer** | Stamp the punch or laser note at its fixed position, bold, 26 pt. Position is the same millimetre offset as the SolidWorks tool. |
| **Simetriği var** | Write *"N ad. simetriği de var"*, replacing any previous one. |
| **Adet / Ölçek** | Update the sheet's `Qty` field, or set the page scale from the slider ladder (3:1 … 1:N). |

### Dxf

- **Export Dxf** — writes the flat pattern with the shop's file-naming scheme:
  `L BracketDefault - 1,5mm S235JR 4 ad simetriği de var %R.DXF`
  (`L` laser / `Z` punch). Options: quantity, *simetriği de var*, `%R`
  rotation, and bend lines.
- **Export Sayfa Dxf** — the whole page, annotations included.
- **Export Png** — the sheet as a PNG at its own paper size and 300 dpi.

### Normalize

- **Norm Part** — writes the metadata the rest of the toolchain reads:
  thickness, K-factor, bend radius, relief type, and the `Description` /
  `Weight` / `Material` document properties. `Description` is bound by
  expression to the thickness, so it cannot drift.
- **Thickness presets** — 0,5 / 0,7 / 0,8 / 1 / 1,2 / 1,5 / 2 mm, each with the
  shop's K-factor and bend radius. **t** reads the current thickness back.
- **RandomizeC / RestoreC** — per-face random colours, restorable exactly.

### Browse

- **Reset Ref** — repair every model's external links across a project folder.
- **Screen Cap** — capture the 3D view as an A4 page at 300 dpi, auto-numbered
  `screencap01.png`, `screencap02.png`, …
- **make pdf** — combine those captures into one `montaj talimatı.pdf`.
- **Logo bas** — replace the company logo on every PNG in a folder: both firms'
  rectangles are cleaned, then the selected logo is drawn at its own position.

## What maps to what

| SolidWorks | FreeCAD |
|---|---|
| `DrawingDoc` | `TechDraw::DrawPage` |
| `.slddrt` sheet format | `TechDraw::DrawSVGTemplate` (`.svg`) |
| `Annotation` / `Note` | `TechDraw::DrawViewAnnotation` |
| `SetupSheet5` | template swap + `Page.Scale` |
| `Create3rdAngleViews` | three `TechDraw::DrawViewPart` objects |
| `ExportToDWG2` | `Import.export()` |
| `InsertSheetMetalBaseFlange2` | thickness/K-factor metadata (see below) |
| `MaterialPropertyValues` | `ViewObject.DiffuseColor` |
| `HKEY_CURRENT_USER\Software\MrSWTool` | `BaseApp/Preferences/Mod/MrFreeTool` |
| `GetDocumentDependencies2` / `ReplaceReferencedDocument` | `Document.xml` XLink table in the `.FCStd` zip |

Annotation positions are unchanged, because both systems put the page origin at
the bottom-left in millimetres.

## Two things that could not be ported literally

**Sheet-metal unfold.** SolidWorks has a built-in unfold; FreeCAD does not. The
DXF export needs a flat pattern, so install the
[SheetMetal](https://github.com/shaise/FreeCAD_SheetMetal) add-on and create an
*Unfold* feature, or select an already-flat part. If neither is present the tool
says so and refuses — writing a wrong DXF to the laser is much worse than
writing none.

**Base-flange insertion.** FreeCAD has no sheet-metal feature tree, so the
"insert a flange at this thickness" buttons became the metadata write described
above. The thickness, K-factor, bend radius and material are what the DXF file
name, the drawing and the ERP actually read, and those are preserved exactly,
including the original's thickness/K-factor pairings.

## Python / macro use

Every operation is importable and argument-taking, and returns an
`OperationResult` rather than raising:

```python
import mrfreecad

mrfreecad.run("dxf.export_flat_dxf", laser=True, qty=4, simetri=True)

# or call the module directly
from mrfreecad import export_dxf
ok, path, message = export_dxf.export_flat_dxf(laser=False, qty=2)

# lower-level pieces are useful on their own too
from mrfreecad.naming import build_flat_dxf_name, normalize_name
from mrfreecad.raster import load_rgba, content_bbox
from mrfreecad.refrepair import read_references
```

Commands are listed in `mrfreecad.DEFAULT_COMMAND_GROUPS`; the panel and the
command bar are both generated from it, so they cannot drift apart.

The naming, raster, settings and reference-repair modules import without
FreeCAD, which is why they are unit-testable.

## Development

```bash
python3 scripts/run_tests.py            # 202 tests, no FreeCAD needed
python3 scripts/run_tests.py -v naming  # one file, verbose
QT_QPA_PLATFORM=offscreen python3 scripts/run_tests.py   # include the Qt tests
```

Static analysis:

```bash
pyright                                # configured by pyrightconfig.json
```

`stubs/` holds minimal type stubs for `FreeCAD` and `FreeCADGui`, which ship
inside FreeCAD's own interpreter and cannot be pip-installed. They are never
imported at runtime.

Layout:

```
InitGui.py             workbench registration
mrfreecad/
  compat.py            FreeCAD / PySide version shims
  settings.py          persistent preferences
  naming.py            Unicode normalisation, indexing, DXF file names
  drawing.py           annotations, Qty, scale, templates
  makedrw.py           automatic drawing creation, scale snapping
  flatpattern.py       flat pattern discovery
  export_dxf.py        flat pattern and page DXF
  export_png.py        page and viewport PNG
  screencap.py         A4 capture and assembly PDF
  logo.py              company logo stamping
  normalize.py         thickness, K-factor, document properties
  colors.py            colour randomise / restore
  refrepair.py         external link repair
  raster.py            dependency-free PNG codec and compositing
  commands.py          command registry
  gui/                 workbench, panel, dialogs
tests/                 unit tests
```

## Licence

MIT — see [LICENSE](LICENSE).
