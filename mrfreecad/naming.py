"""File name normalisation, project indexing and output file naming.

Ported from the SolidWorks original, where these routines were the root-cause
fix for three separate production problems:

1. ``NFD`` -> ``NFC`` file names.  Windows treats ``o`` + combining diaeresis
   and precomposed ``\u00f6`` as *different* names, so a file visible in
   Explorer could not be opened by the path stored in the document.
2. Turkish diacritic folding.  A suppressed component can come back from the
   kernel with its name ASCII-mangled, so matching has to be done on a folded
   form.
3. Search folders.  A file has to be findable by name, not only by the exact
   path somebody once recorded.

All of that is plain string and filesystem work, so it ports over directly and
is fully unit tested in ``tests/test_naming.py``.
"""

from __future__ import annotations

import os
import re
import unicodedata
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

__all__ = [
    "normalize_name",
    "to_nfc",
    "is_nfd",
    "normalize_names_deep",
    "resolve_nfc_path",
    "index_project",
    "search_file",
    "find_reference_in_roots",
    "strip_instance_suffix",
    "build_flat_dxf_name",
    "build_screen_cap_path",
    "next_screen_cap_path",
    "collect_screen_caps",
    "to_decimal",
    "MM",
]

#: FreeCAD works in millimetres internally.
MM = 1.0

#: Turkish letters and their ASCII folds.  Applied after NFD decomposition has
#: already stripped the combining marks, so ``\u00f6`` reaches the table as
#: ``o`` and simply passes through.
_TURKISH_FOLD = str.maketrans(
    {
        "\u0131": "i",  # ı
        "\u0130": "I",  # İ
        "\u015f": "s",  # ş
        "\u015e": "S",  # Ş
        "\u00e7": "c",  # ç
        "\u00c7": "C",  # Ç
        "\u011f": "g",  # ğ
        "\u011e": "G",  # Ğ
        "\u00fc": "u",  # ü
        "\u00dc": "U",  # Ü
        "\u00f6": "o",  # ö
        "\u00d6": "O",  # Ö
        "\u00e2": "a",  # â
        "\u00ee": "i",  # î
        "\u00fb": "u",  # û
    }
)

#: Instance suffix FreeCAD-less kernels append to repeated component links,
#: e.g. ``Yan Sac Ek-1``.
_INSTANCE_SUFFIX = re.compile(r"-\d+$")


def normalize_name(value: Optional[str]) -> str:
    """Fold ``value`` into a comparison-safe form.

    Decomposes to NFD, drops combining marks, folds Turkish letters and keeps
    ASCII letters (also lowercased) intact.  Two names that differ only in
    diacritics, in NFD/NFC form, or in ASCII mangling compare equal.
    """
    if not value:
        return ""
    decomposed = unicodedata.normalize("NFD", value)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    folded = stripped.translate(_TURKISH_FOLD)
    return "".join(ch for ch in folded if ch.isascii() or ch.isalnum()).lower()


def to_nfc(value: Optional[str]) -> str:
    """Return ``value`` in NFC (composed) form."""
    if not value:
        return ""
    return unicodedata.normalize("NFC", value)


def is_nfd(value: str) -> bool:
    """True when ``value`` is not in NFC form and would be renamed."""
    return bool(value) and value != to_nfc(value)


def normalize_names_deep(root: str, log: Optional[List[str]] = None) -> int:
    """Recursively rename every file and folder below ``root`` to NFC.

    Names stay visually identical; only the byte form changes, which is exactly
    what makes a recorded path resolvable again.  Returns the number of renames
    performed and appends one line per rename to ``log`` when given.
    """
    renamed = 0
    if not root or not os.path.isdir(root):
        return 0

    try:
        entries = list(os.scandir(root))
    except OSError:
        return 0

    # Files first, then directories: a directory rename invalidates the paths
    # we collected for its children, so recurse using the post-rename path.
    for entry in entries:
        if not entry.is_file(follow_symlinks=False):
            continue
        name = entry.name
        if not is_nfd(name):
            continue
        target = os.path.join(root, to_nfc(name))
        if os.path.exists(target):
            continue
        try:
            os.rename(entry.path, target)
            renamed += 1
            if log is not None:
                log.append("NFD->NFC file: " + name)
        except OSError:
            continue

    for entry in entries:
        if not entry.is_dir(follow_symlinks=False):
            continue
        name = entry.name
        child = entry.path
        if is_nfd(name):
            target = os.path.join(root, to_nfc(name))
            if not os.path.exists(target):
                try:
                    os.rename(child, target)
                    renamed += 1
                    if log is not None:
                        log.append("NFD->NFC folder: " + name)
                    child = target
                except OSError:
                    pass
        renamed += normalize_names_deep(child, log)

    return renamed


def resolve_nfc_path(path: str) -> str:
    """Map an NFC path onto the real on-disk path, segment by segment.

    Starts at the closest existing ancestor and walks down, matching each
    segment in NFC form.  This is what lets a path recorded by another program
    be found even when the disk holds decomposed names.
    """
    if not path:
        return ""
    current = os.path.abspath(path)
    missing: List[str] = []
    while not os.path.exists(current):
        parent = os.path.dirname(current)
        if parent == current:
            return ""
        missing.insert(0, os.path.basename(current))
        current = parent
    for segment in missing:
        wanted = to_nfc(segment).casefold()
        matched = ""
        try:
            for child in os.listdir(current):
                if to_nfc(child).casefold() == wanted:
                    matched = child
                    break
        except OSError:
            return ""
        if not matched:
            return ""
        current = os.path.join(current, matched)
    return current


def index_project(root: str, extensions: Sequence[str] = (".fcstd",)) -> Dict[str, str]:
    """Build ``{normalised_name: path}`` for every model below ``root``.

    Nested folders are included, matching the original's recursive scan.  On a
    name clash the shallowest path wins, and among equals the first found in
    sorted order wins, so indexing is deterministic.
    """
    index: Dict[str, str] = {}
    if not root or not os.path.isdir(root):
        return index
    wanted = {ext.lower() for ext in extensions}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for filename in sorted(filenames):
            if os.path.splitext(filename)[1].lower() not in wanted:
                continue
            key = normalize_name(filename)
            if key and key not in index:
                index[key] = os.path.join(dirpath, filename)
    return index


def search_file(root: str, filename: str, preferred_ext: str = "", max_depth: int = 12) -> str:
    """Find ``filename`` below ``root`` by *normalised* name.

    ``preferred_ext`` wins when several files share a name.  Without it, the
    search prefers CAD-ish extensions in a fixed order, then falls back to the
    first match found.
    """
    if not root or not os.path.isdir(root):
        return ""
    wanted = normalize_name(os.path.splitext(filename)[0])
    if not wanted:
        return ""
    wanted_ext = normalize_name(preferred_ext.lstrip(".")) if preferred_ext else ""

    matches: List[str] = []
    root_depth = root.rstrip(os.sep).count(os.sep)
    for dirpath, dirnames, filenames in os.walk(root):
        if dirpath.rstrip(os.sep).count(os.sep) - root_depth >= max_depth:
            dirnames[:] = []
        dirnames.sort()
        for candidate in sorted(filenames):
            if normalize_name(os.path.splitext(candidate)[0]) != wanted:
                continue
            full = os.path.join(dirpath, candidate)
            if wanted_ext and normalize_name(os.path.splitext(candidate)[1].lstrip(".")) == wanted_ext:
                return full
            matches.append(full)
    if not matches:
        return ""
    for candidate in matches:
        if normalize_name(os.path.splitext(candidate)[1].lstrip(".")) == "fcstd":
            return candidate
    return matches[0]


def find_reference_in_roots(filename: str, roots: Iterable[str], preferred_ext: str = "") -> str:
    """Search several roots in order and return the first hit."""
    for root in roots:
        if not root:
            continue
        found = search_file(root, filename, preferred_ext)
        if found:
            return found
    return ""


def strip_instance_suffix(name: str) -> str:
    """Drop a trailing ``-N`` instance counter: ``Yan Sac Ek-1`` -> ``Yan Sac Ek``.

    Matching is exact after this.  Prefix matching is deliberately *not*
    offered: a reference to ``Yan Sac`` must not be applied to a component
    called ``Yan Sac Ek``.
    """
    return _INSTANCE_SUFFIX.sub("", name or "")


def to_decimal(value: float, places: int = 3) -> str:
    """Format a millimetre number the way Turkish CAD practice writes it.

    Comma decimal separator, no trailing zeros, so ``1.5`` becomes ``1,5`` and
    ``0.8`` becomes ``0,8``.  Used for DXF file names, which the laser and the
    punch both read by eye.
    """
    text = "{0:.{1}f}".format(float(value), places).rstrip("0").rstrip(".")
    if text in ("", "-", "-0"):
        return "0"
    return text.replace(".", ",")


def _sanitize(component: str) -> str:
    """Strip characters that are illegal in a file name on any platform."""
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", component or "")
    return cleaned.strip().rstrip(".")


def build_flat_dxf_name(
    document_name: str,
    model_name: str,
    configuration: str,
    thickness: str,
    material: str,
    qty: int,
    laser: bool = True,
    simetri: bool = False,
    rotation: bool = False,
    extension: str = ".DXF",
) -> str:
    """Compose the flat-pattern DXF file name.

    The layout is byte-compatible with the SolidWorks tool so a mixed
    SolidWorks / FreeCAD shop produces a single naming series::

        L <model><config> - <thickness>mm <material> <qty> ad simetriği de var %R.DXF

    ``L`` is the laser marker and ``Z`` the punch marker.
    """
    marker = "L" if laser else "Z"
    thickness_text = _sanitize(str(thickness).strip())
    material_text = _sanitize(str(material).strip())
    config_text = _sanitize(str(configuration).strip())
    model_text = _sanitize(str(model_name or document_name).strip())

    stem = "{0} {1}{2}".format(marker, model_text, config_text)
    # The original's layout is "<marker> <model><config> - <thickness>mm <material> ...".
    # The " - " separator is only present when a thickness was found, so the dash
    # is emitted together with the field it introduces rather than on its own.
    thickness_field = "{0}mm".format(thickness_text) if thickness_text else ""
    if thickness_field:
        thickness_field = "- " + thickness_field
    parts = [stem, thickness_field]
    if material_text:
        parts.append(material_text)
    parts.append("{0} ad".format(int(qty)))
    if simetri:
        parts.append("simetriği de var")
    if rotation:
        parts.append("%R")
    return " ".join(p for p in parts if p) + extension


def build_screen_cap_path(folder: str, index: int, prefix: str = "screencap", extension: str = ".png") -> str:
    """``<folder>/screencap01.png`` — zero padded to two digits, as the original."""
    return os.path.join(folder, "{0}{1:02d}{2}".format(prefix, int(index), extension))


def next_screen_cap_path(folder: str, prefix: str = "screencap", extension: str = ".png") -> str:
    """First unused ``screencapNN.png`` in ``folder`` (1..999, then wraps)."""
    for index in range(1, 1000):
        candidate = build_screen_cap_path(folder, index, prefix, extension)
        if not os.path.exists(candidate):
            return candidate
    return build_screen_cap_path(folder, 999, prefix, extension)


def collect_screen_caps(folder: str, prefix: str = "screencap", extension: str = ".png") -> List[str]:
    """Every ``<prefix>NN.<ext>`` in ``folder``, ordered by the numeric suffix.

    Non-numeric names are ignored, which keeps unrelated PNGs out of the
    assembly PDF.
    """
    found: List[Tuple[int, str]] = []
    if not folder or not os.path.isdir(folder):
        return []
    for name in os.listdir(folder):
        stem, ext = os.path.splitext(name)
        if not stem.startswith(prefix) or ext.lower() != extension.lower():
            continue
        suffix = stem[len(prefix) :]
        if not suffix.isdigit():
            continue
        found.append((int(suffix), os.path.join(folder, name)))
    found.sort()
    return [path for _, path in found]
