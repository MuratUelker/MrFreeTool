"""MrFreeTool - FreeCAD sheet-metal production helpers.

The package is intentionally split into two halves:

``mrfreecad.<module>``
    Pure-Python command implementations.  Every exported feature can be called
    from the Python console (``import mrfreecad``) or from a macro without the
    GUI being involved.  Nothing in this half imports ``FreeCADGui`` at module
    scope, so the whole package stays usable from ``freecadcmd``.

``mrfreecad.gui``
    The Qt workbench panel.  Imported only from :mod:`InitGui`, i.e. when
    FreeCAD runs with a GUI.

Every command follows the same convention: it returns a human readable
:class:`OperationResult` instead of raising, and it never auto-saves a
document the user did not ask to save.
"""

from mrfreecad.version import VERSION, VERSION_STRING

__all__ = [
    "VERSION",
    "VERSION_STRING",
    "OperationResult",
    "DEFAULT_COMMAND_GROUPS",
    "run",
    "get_command",
    "list_commands",
]


class OperationResult:
    """Result of a MrFreeTool operation.

    Mirrors the detailed report windows of the original tool: every command
    reports success/failure plus a block of text the user can read and copy.
    """

    __slots__ = ("ok", "title", "message", "details")

    def __init__(self, ok: bool = True, title: str = "", message: str = "", details: str = ""):
        self.ok = bool(ok)
        self.title = title or "MrFreeTool"
        self.message = message or ""
        self.details = details or ""

    # -- constructors -----------------------------------------------------
    @classmethod
    def success(cls, message: str = "", details: str = "", title: str = "") -> "OperationResult":
        return cls(True, title, message, details)

    @classmethod
    def failure(cls, message: str, details: str = "", title: str = "") -> "OperationResult":
        return cls(False, title, message, details)

    # -- behaviour --------------------------------------------------------
    def __bool__(self) -> bool:
        return self.ok

    def __str__(self) -> str:
        parts = [self.message]
        if self.details:
            parts.append(self.details)
        return "\n".join(p for p in parts if p)

    def report(self) -> str:
        """Full report text, identical in shape to the SolidWorks tool's."""
        head = "=" * 59
        lines = [head, "  " + self.title.upper(), head, ""]
        if self.message:
            lines.append(self.message)
            lines.append("")
        if self.details:
            lines.append(self.details)
            lines.append("")
        return "\n".join(lines)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        state = "ok" if self.ok else "failed"
        return "OperationResult({0}, {1!r})".format(state, self.message)


#: Lazily built command registry, populated by :func:`_registry`.
_REGISTRY = None

#: Ordered command groups.  Each entry is ``(group_id, group_label, commands)``
#: and mirrors the four tabs of the original Windows tool:
#: Drawing / Dxf / Normalize / Browse.  ``workbench.py`` consumes this to build
#: the command bar, ``panel.py`` to build the tabbed dialog, so the two can
#: never drift apart.
#:
#: Note that the per-thickness preset commands are *not* listed here: they are
#: generated from :data:`mrfreecad.normalize.THICKNESS_PRESETS` by
#: :func:`mrfreecad.commands.preset_commands`, because one exists per thickness
#: in the table.  Add new fixed commands here; add new thicknesses to the table.
DEFAULT_COMMAND_GROUPS = (
    (
        "drawing",
        "Drawing",
        (
            "drawing.make_drawing",
            "drawing.replace_template",
            "drawing.apply_ayazsa",
            "drawing.apply_karadeniz",
            "drawing.add_zimba",
            "drawing.add_lazer",
            "drawing.add_simetri",
            "drawing.set_qty",
            "drawing.set_scale",
        ),
    ),
    (
        "dxf",
        "Dxf",
        (
            "dxf.export_flat_dxf",
            "dxf.export_page_dxf",
            "dxf.export_png",
        ),
    ),
    (
        "normalize",
        "Normalize",
        (
            "normalize.norm_part",
            "normalize.read_thickness",
            "normalize.randomize_colors",
            "normalize.restore_colors",
        ),
    ),
    (
        "browse",
        "Browse",
        (
            "browse.reset_ref",
            "browse.screen_cap",
            "browse.make_pdf",
            "browse.stamp_logo",
        ),
    ),
)


def _registry():
    """Return the lazily built ``{name: callable}`` command registry."""
    global _REGISTRY
    if _REGISTRY is None:
        from mrfreecad import commands

        _REGISTRY = dict(commands.COMMANDS)
        for label, handler in commands.preset_commands():
            _REGISTRY[label] = handler
    return _REGISTRY


def get_command(name: str):
    """Look a dotted command name up in the registry.

    Returns a *guarded* callable, so calling it can never raise: failures come
    back as an :class:`OperationResult`.  Returns ``None`` for an unknown name.

    >>> callable(get_command("drawing.add_zimba"))
    True
    """
    if name not in _registry():
        return None
    from mrfreecad import commands

    return commands.resolve(name)


def list_commands() -> "tuple[str, ...]":
    """All available dotted command names, grouped and de-duplicated.

    Includes the generated per-thickness preset commands.
    """
    seen = []
    for _gid, _label, names in DEFAULT_COMMAND_GROUPS:
        for name in names:
            if name not in seen:
                seen.append(name)
    from mrfreecad import commands

    for name, _handler in commands.preset_commands():
        if name not in seen:
            seen.append(name)
    return tuple(seen)


def run(name: str, *args, **kwargs) -> OperationResult:
    """Run a command by dotted name.

    Raises :class:`KeyError` for unknown names (a programming error, not a
    user error); user-facing failures come back as a failed
    :class:`OperationResult`.
    """
    handler = get_command(name)
    if handler is None:
        raise KeyError("unknown MrFreeTool command: {0!r}".format(name))
    return handler(*args, **kwargs)
