"""Command registry and FreeCAD command objects.

Two audiences:

* the GUI panel and the FreeCAD command bar, which need a parameterless
  callable that reads its inputs from the panel or from the selection;
* macros and the Python console, which want the same operations with explicit
  arguments.

So every operation exists twice: a ``function`` that takes arguments and
returns a result, and a thin ``*_command`` wrapper that pulls its inputs from
the shared panel state.  Both land in a :class:`OperationResult`, which is
what the report window renders.
"""

from __future__ import annotations

import os
from typing import Any, Callable, Dict, List, Optional, Tuple

from mrfreecad import OperationResult
from mrfreecad import compat

__all__ = [
    "COMMANDS",
    "LABELS",
    "PanelState",
    "command_label",
    "panel_state",
    "set_panel_state",
    "show_result",
    "preset_commands",
    "resolve",
]


def _error_result(message: str, title: str) -> OperationResult:
    """Build a failed result.  Named here so commands do not import the class."""
    return OperationResult.failure(message, title=title)


# ---------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------
#: Menu/button label for each command.  Lives here rather than in the GUI layer
#: because the workbench menu, the panel buttons and the report window titles
#: all need it, and the report title is produced with no GUI present.
LABELS: Dict[str, str] = {
    "drawing.make_drawing": "Make Drw",
    "drawing.replace_template": "Replace Sheet",
    "drawing.apply_ayazsa": "Ayazsa",
    "drawing.apply_karadeniz": "Karadeniz",
    "drawing.add_zimba": "Zımba",
    "drawing.add_lazer": "Lazer",
    "drawing.add_simetri": "Simetriği var",
    "drawing.set_qty": "Qty uygula",
    "drawing.set_scale": "Ölçek uygula",
    "dxf.export_flat_dxf": "Export Dxf",
    "dxf.export_page_dxf": "Export Sayfa Dxf",
    "dxf.export_png": "Export Png",
    "normalize.norm_part": "Norm Part",
    "normalize.read_thickness": "t",
    "normalize.randomize_colors": "RandomizeC",
    "normalize.restore_colors": "RestoreC",
    "browse.reset_ref": "Reset Ref",
    "browse.screen_cap": "Screen Cap",
    "browse.make_pdf": "make pdf",
    "browse.stamp_logo": "Logo bas",
}


def command_label(name: str) -> str:
    """Human label for a dotted command name.

    Unknown names fall back to a title-cased tail, so a command added without a
    label still reads sensibly instead of showing its internal name.
    """
    if name in LABELS:
        return LABELS[name]
    tail = name.rsplit(".", 1)[-1]
    return tail.replace("_", " ").title()


# ---------------------------------------------------------------------------
# Shared panel state
# ---------------------------------------------------------------------------
class PanelState:
    """Input values the panel collects and the commands read.

    Mirrors the original's controls: Qty (drawing and DXF), Laser/Punch radio,
    "simetriği de var" and "%R" checkboxes, bend lines, and the scale slider
    position.
    """

    def __init__(self) -> None:
        self.qty: int = 1
        self.laser: bool = True
        self.simetri: bool = False
        self.rotation: bool = False
        self.bend_lines: bool = True
        self.scale_index: int = 3
        self.folder: str = ""
        self.firm: str = "Ayazsa"

    def sync_from_settings(self) -> None:
        """Seed the controls from the stored preferences, as the original did."""
        from mrfreecad.settings import get_settings

        settings = get_settings()
        self.qty = settings.qty()
        self.laser = settings.get_bool("Dxf/LaserDefault")
        self.rotation = settings.get_bool("Dxf/Rotation")
        self.simetri = settings.get_bool("Dxf/Simetri")
        self.bend_lines = settings.get_bool("Dxf/BendLinesDefault")

    def persist(self) -> None:
        """Write the control values back, matching the original's behaviour."""
        from mrfreecad.settings import get_settings

        settings = get_settings()
        settings.set_qty(self.qty)
        settings.set_bool("Dxf/LaserDefault", self.laser)
        settings.set_bool("Dxf/Rotation", self.rotation)
        settings.set_bool("Dxf/Simetri", self.simetri)
        settings.set_bool("Dxf/BendLinesDefault", self.bend_lines)


_STATE = PanelState()


def panel_state() -> PanelState:
    """The shared panel state."""
    return _STATE


def set_panel_state(state: PanelState) -> None:
    global _STATE
    _STATE = state


def show_result(result: OperationResult) -> OperationResult:
    """Hand a result to the report window when a GUI is up."""
    if not compat.HAS_GUI:
        compat.console_log(result.report())
        return result
    try:
        from mrfreecad.gui.dialogs import show_report

        show_report(result)
    except Exception as exc:
        compat.console_log("report window failed: " + str(exc))
        compat.console_log(result.report())
    return result


def _fail(exc: Exception, title: str) -> OperationResult:
    import traceback

    detail = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    compat.console_log(detail)
    return show_result(OperationResult.failure(str(exc), detail, title))


def _guard(title: str, func: Callable[[], OperationResult]) -> OperationResult:
    """Run ``func``, turning any exception into a failed result."""
    try:
        return func()
    except Exception as exc:  # noqa: BLE001 - the boundary must not raise
        return _fail(exc, title)


# ---------------------------------------------------------------------------
# Drawing commands
# ---------------------------------------------------------------------------
def drawing_make_drawing() -> OperationResult:
    from mrfreecad import makedrw

    state = panel_state()
    state.persist()
    page = makedrw.make_drawing()
    if page is None:
        return show_result(OperationResult.failure("Drawing oluşturulamadı.", title="Make Drw"))
    from mrfreecad import drawing as drawing_mod

    scale = drawing_mod.page_scale(page)
    message = "Drawing oluşturuldu.\nSayfa: {0}\nFormat: {1}\nÖlçek: {2}".format(
        page.Label,
        drawing_mod.template_name(page) or "(varsayılan)",
        drawing_mod.format_scale(scale),
    )
    return show_result(OperationResult.success(message, title="Make Drw"))


def drawing_replace_template(which: str = "landscape") -> OperationResult:
    from mrfreecad import drawing as drawing_mod
    from mrfreecad.settings import get_settings

    path = get_settings().template(which)
    if not path:
        return show_result(
            OperationResult.failure(
                "Şablon ayarlanmamış: " + which + "\n\nMrFreeTool > Ayarlar'dan TechDraw "
                "şablonunu (.svg) seçin.",
                title="Replace Sheet",
            )
        )
    page = drawing_mod.active_page()
    if page is None:
        return show_result(OperationResult.failure("Açık bir çizim sayfası yok.", title="Replace Sheet"))
    template = drawing_mod.apply_template(page, path)
    if template is None:
        return show_result(OperationResult.failure("Şablon uygulanamadı:\n" + path, title="Replace Sheet"))
    return show_result(
        OperationResult.success("Şablon yenilendi:\n" + path + "\nÖlçek korundu.", title="Replace Sheet")
    )


def drawing_add_zimba() -> OperationResult:
    from mrfreecad import drawing as drawing_mod

    page = drawing_mod.active_page()
    if page is None:
        return show_result(OperationResult.failure("Açık bir çizim sayfası yok.", title="Zımba"))
    if drawing_mod.add_zimba(page) is None:
        return show_result(OperationResult.failure("Not eklenemedi.", title="Zımba"))
    return show_result(OperationResult.success("'Zımba' notu eklendi.", title="Zımba"))


def drawing_add_lazer() -> OperationResult:
    from mrfreecad import drawing as drawing_mod

    page = drawing_mod.active_page()
    if page is None:
        return show_result(OperationResult.failure("Açık bir çizim sayfası yok.", title="Lazer"))
    if drawing_mod.add_lazer(page) is None:
        return show_result(OperationResult.failure("Not eklenemedi.", title="Lazer"))
    return show_result(OperationResult.success("'Lazer' notu eklendi.", title="Lazer"))


def drawing_add_simetri() -> OperationResult:
    from mrfreecad import drawing as drawing_mod

    state = panel_state()
    state.persist()
    page = drawing_mod.active_page()
    if page is None:
        return show_result(OperationResult.failure("Açık bir çizim sayfası yok.", title="Simetriği var"))
    if drawing_mod.add_simetri(page, state.qty) is None:
        return show_result(OperationResult.failure("Not eklenemedi.", title="Simetriği var"))
    return show_result(
        OperationResult.success("{0} ad. simetriği de var yazıldı.".format(state.qty), title="Simetriği var")
    )


def drawing_set_qty() -> OperationResult:
    from mrfreecad import drawing as drawing_mod

    state = panel_state()
    state.persist()
    page = drawing_mod.active_page()
    if page is None:
        return show_result(OperationResult.failure("Açık bir çizim sayfası yok.", title="Adet"))
    changed = drawing_mod.set_qty(page, state.qty)
    if changed == 0:
        return show_result(
            OperationResult(
                True,
                "Adet",
                "Şablonda güncellenecek 'Qty' alanı bulunamadı.",
                "Sayfadaki 'Qty' başlığının altında sayısal not olması gerekir.",
            )
        )
    return show_result(OperationResult.success("Adet {0} olarak güncellendi.".format(state.qty), title="Adet"))


def drawing_set_scale() -> OperationResult:
    from mrfreecad import drawing as drawing_mod

    state = panel_state()
    ratio = drawing_mod.apply_scale_index(drawing_mod.active_page(), state.scale_index)
    return show_result(
        OperationResult.success("Ölçek {0} uygulandı.".format(drawing_mod.format_scale(ratio)), title="Ölçek")
    )


# ---------------------------------------------------------------------------
# Dxf / Png commands
# ---------------------------------------------------------------------------
def dxf_export_flat() -> OperationResult:
    from mrfreecad import export_dxf

    state = panel_state()
    state.persist()
    ok, path, message = export_dxf.export_flat_dxf(
        laser=state.laser,
        qty=state.qty,
        simetri=state.simetri,
        rotation=state.rotation,
        bend_lines=state.bend_lines,
    )
    if not ok:
        return show_result(OperationResult.failure(message, title="Export Dxf"))
    return show_result(OperationResult.success(message, title="Export Dxf"))


def dxf_export_page() -> OperationResult:
    from mrfreecad import export_dxf

    ok, path, message = export_dxf.export_page_dxf()
    if not ok:
        return show_result(OperationResult.failure(message, title="Export Page Dxf"))
    return show_result(OperationResult.success(message, title="Export Page Dxf"))


def png_export_page() -> OperationResult:
    from mrfreecad import export_png

    ok, path, message = export_png.export_page_png()
    if not ok:
        return show_result(OperationResult.failure(message, title="Export Png"))
    return show_result(OperationResult.success(message, title="Export Png"))


# ---------------------------------------------------------------------------
# Normalize commands
# ---------------------------------------------------------------------------
def normalize_norm() -> OperationResult:
    from mrfreecad import normalize

    ok, message = normalize.norm_part()
    if not ok:
        return show_result(OperationResult.failure(message, title="Norm Part"))
    return show_result(OperationResult.success(message, title="Norm Part"))


def normalize_thickness(label: str) -> OperationResult:
    from mrfreecad import normalize

    preset = normalize.preset_for_label(label)
    if preset is None:
        available = ", ".join(normalize.PRESET_LABELS)
        return show_result(
            OperationResult.failure(
                "Bilinmeyen kalınlık: {0}\n\nSeçenekler: {1}".format(label, available),
                title="Kalınlık " + label,
            )
        )
    ok, message = normalize.apply_preset(preset[1])
    title = "Kalınlık " + label
    if not ok:
        return show_result(OperationResult.failure(message, title=title))
    return show_result(OperationResult.success(message, title=title))


def normalize_read_thickness() -> OperationResult:
    from mrfreecad import export_dxf, normalize

    obj = compat.active_object()
    if obj is None:
        return show_result(OperationResult.failure("Açık nesne yok.", title="Kalınlık oku"))
    thickness = normalize.read_thickness_property(obj)
    text = export_dxf.read_thickness(obj)
    if thickness is None and not text:
        return show_result(
            OperationResult.failure("Parçada kalınlık bulunamadı.", title="Kalınlık oku")
        )
    message = "Thickness = {0} mm\nAçıklama   = {1}\nMalzeme   = {2}".format(
        ("{0} mm".format(thickness) if thickness is not None else "(yok)"),
        text or "(boş)",
        export_dxf.read_material(obj) or "(boş)",
    )
    return show_result(OperationResult.success(message, title="Kalınlık oku"))


def normalize_randomize() -> OperationResult:
    from mrfreecad import colors

    ok, message = colors.randomize_colors()
    if not ok:
        return show_result(OperationResult.failure(message, title="RandomizeC"))
    return show_result(OperationResult.success(message, title="RandomizeC"))


def normalize_restore() -> OperationResult:
    from mrfreecad import colors

    ok, message = colors.restore_colors()
    if not ok:
        return show_result(OperationResult.failure(message, title="RestoreC"))
    return show_result(OperationResult.success(message, title="RestoreC"))


# ---------------------------------------------------------------------------
# Browse commands
# ---------------------------------------------------------------------------
def browse_reset_ref() -> OperationResult:
    from mrfreecad import refrepair

    state = panel_state()
    folder = state.folder
    if not folder:
        # No folder given and no dialog possible (headless / macro): fall back
        # to the active document's folder rather than blocking on a dialog.
        if compat.HAS_GUI and compat.qt_widgets("Folder chooser").QApplication.instance() is not None:
            from mrfreecad.gui.dialogs import pick_folder

            folder = pick_folder("Referansları onarılacak proje klasörünü seçin")
            if not folder:
                return show_result(OperationResult.failure("İşlem iptal edildi.", title="Reset Ref"))
        else:
            folder = _document_folder()
            if not folder:
                return show_result(
                    _error_result(
                        "Proje klasörü belirtilmedi ve açık bir doküman yok.\n\n"
                        "Klasörü komut satırından geçirin ya da panelde ayarlayın.",
                        "Reset Ref",
                    )
                )
        state.folder = folder

    changed, report = refrepair.repair_project(folder)
    return show_result(OperationResult(changed, "Reset Ref", "Onarım tamamlandı." if changed else "Değişiklik yok.", report))


def _document_folder() -> str:
    """Folder of the active document, or ``""``."""
    doc = compat.active_document()
    if doc is None:
        return ""
    path = str(getattr(doc, "FileName", "") or "")
    return os.path.dirname(path) if path else ""


def browse_screen_cap() -> OperationResult:
    from mrfreecad import screencap

    state = panel_state()
    ok, path, message = screencap.screen_cap(folder=state.folder or "")
    if not ok:
        return show_result(OperationResult.failure(message, title="Screen Cap"))
    return show_result(OperationResult.success(message, title="Screen Cap"))


def browse_make_pdf() -> OperationResult:
    from mrfreecad import screencap

    state = panel_state()
    ok, path, message = screencap.make_pdf(folder=state.folder or "")
    if not ok:
        return show_result(OperationResult.failure(message, title="Montaj PDF"))
    return show_result(OperationResult.success(message, title="Montaj PDF"))


def browse_stamp_logo(firm: str = "") -> OperationResult:
    from mrfreecad import logo

    state = panel_state()
    target = firm or state.firm
    state.firm = target
    ok, report, message = logo.stamp_folder(target, state.folder or "")
    if not ok:
        return show_result(OperationResult.failure(report or message, title=target + " logo"))
    return show_result(OperationResult.success(message, report, target + " logo"))


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
COMMANDS: Dict[str, Callable[[], OperationResult]] = {
    "drawing.make_drawing": drawing_make_drawing,
    "drawing.replace_template": drawing_replace_template,
    "drawing.apply_ayazsa": lambda: drawing_replace_template("ayazsa"),
    "drawing.apply_karadeniz": lambda: drawing_replace_template("karadeniz"),
    "drawing.add_zimba": drawing_add_zimba,
    "drawing.add_lazer": drawing_add_lazer,
    "drawing.add_simetri": drawing_add_simetri,
    "drawing.set_qty": drawing_set_qty,
    "drawing.set_scale": drawing_set_scale,
    "dxf.export_flat_dxf": dxf_export_flat,
    "dxf.export_page_dxf": dxf_export_page,
    "dxf.export_png": png_export_page,
    "normalize.norm_part": normalize_norm,
    "normalize.read_thickness": normalize_read_thickness,
    "normalize.randomize_colors": normalize_randomize,
    "normalize.restore_colors": normalize_restore,
    "browse.reset_ref": browse_reset_ref,
    "browse.screen_cap": browse_screen_cap,
    "browse.make_pdf": browse_make_pdf,
    "browse.stamp_logo": browse_stamp_logo,
}


def preset_commands() -> List[Tuple[str, Callable[[], OperationResult]]]:
    """One command per thickness preset, labelled the way the buttons were.

    Generated from the preset table rather than listed by hand, so adding a
    thickness to :data:`mrfreecad.normalize.THICKNESS_PRESETS` is enough to get
    a working button in the panel and a command in the command bar.
    """
    from mrfreecad import normalize

    def make_handler(label: str) -> Callable[[], OperationResult]:
        return lambda: normalize_thickness(label)

    return [
        ("normalize.apply_thickness:" + label, make_handler(label))
        for label in normalize.PRESET_LABELS
    ]


def resolve(name: str) -> Callable[[], OperationResult]:
    """Look a command up, including the generated thickness-preset ones.

    The returned wrapper is always safe to call: any exception becomes a failed
    :class:`OperationResult` with a full traceback in its details, because a
    command invoked from a menu or toolbar has no caller to catch for it and
    would otherwise surface as a silent no-op.
    """
    if name in COMMANDS:
        handler = COMMANDS[name]
    else:
        for candidate, candidate_handler in preset_commands():
            if candidate == name:
                handler = candidate_handler
                break
        else:
            raise KeyError("unknown command: " + name)

    def guarded() -> OperationResult:
        return _guard(_short_name(name), handler)

    return guarded


def _short_name(dotted: str) -> str:
    """A readable title for a dotted command name."""
    if ":" in dotted:
        base, argument = dotted.split(":", 1)
        return "{0} {1}".format(command_label(base), argument)
    return command_label(dotted)
