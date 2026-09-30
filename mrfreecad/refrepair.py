"""External document reference repair - the ``Reset Ref`` port.

The SolidWorks original had the largest single routine in the tool: it scanned
a project folder, read an assembly's dependency table without opening it,
normalised Unicode, fixed the on-disk reference paths, opened the assembly,
replaced misplaced components (with a ``_TEMP`` copy fallback for
same-model-different-path), unsuppressed subtrees, repaired drawing references
and finally cleaned up the search folders it had added - all without saving
anything without asking.

FreeCAD's model is different and much more tractable: a ``.FCStd`` file is a
zip whose ``Document.xml`` lists every external link by path.  That gives the
same three capabilities without opening anything:

1. **read** the reference table of a document, closed, in milliseconds;
2. **rewrite** a stale path in place, again without opening the document, which
   means no "where is this file?" prompt and no risk of a half-modified
   session;
3. **report** what could not be resolved and let the user decide, exactly like
   the original's confirmation step before deleting anything.

Deleting a component is deliberately *not* automated.  In FreeCAD a link with
an unresolvable target is a visible, fixable condition; silently deleting it
destroys placement work, so the tool reports and stops.
"""

from __future__ import annotations

import os
import re
import shutil
import zipfile
from typing import Any, Dict, List, Optional, Tuple

from mrfreecad import compat
from mrfreecad.naming import index_project, normalize_name, normalize_names_deep, resolve_nfc_path

__all__ = [
    "read_references",
    "repair_project",
    "backup_project",
    "resolve_reference",
    "MODEL_EXTENSIONS",
    "XLinkPattern",
]

#: Model file types FreeCAD links to.
MODEL_EXTENSIONS = (".fcstd",)

#: ``file="..."`` attributes in ``Document.xml``.  Matches both plain and
#: escaped backslash paths, which is how FreeCAD writes Windows paths.
XLinkPattern = re.compile(r'file\s*=\s*"([^"]+)"')


def _document_xml(path: str) -> Optional[str]:
    """Read ``Document.xml`` out of a ``.FCStd`` archive without opening it."""
    try:
        with zipfile.ZipFile(path) as archive:
            for name in archive.namelist():
                if name == "Document.xml":
                    return archive.read(name).decode("utf-8", errors="replace")
    except (OSError, zipfile.BadZipFile, KeyError) as exc:
        compat.console_log("read_document_xml failed for {0}: {1}".format(path, exc))
        return None
    return None


def read_references(path: str) -> List[str]:
    """Every external file path recorded in ``path``.

    Normalises away ``\\`` to ``/`` and drops empty and self references.
    """
    xml = _document_xml(path)
    if xml is None:
        return []

    found: List[str] = []
    seen = set()
    self_normalized = normalize_name(os.path.basename(path))
    for match in XLinkPattern.finditer(xml):
        raw = match.group(1).strip()
        if not raw:
            continue
        candidate = raw.replace("\\", "/")
        if normalize_name(os.path.basename(candidate)) == self_normalized:
            continue
        if candidate in seen:
            continue
        seen.add(candidate)
        found.append(candidate)
    return found


def _rewrite_references(path: str, mapping: Dict[str, str]) -> Tuple[int, List[str]]:
    """Rewrite every reference in ``path`` per ``mapping``.

    Returns ``(replaced, errors)``.  The archive is rebuilt into a temporary
    file and moved into place, so an interrupted write cannot destroy the
    model - the one non-negotiable rule when editing someone else's project.
    """
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            if "Document.xml" not in names:
                return (0, ["Document.xml yok: " + path])
            payloads = {name: archive.read(name) for name in names}
    except (OSError, zipfile.BadZipFile) as exc:
        return (0, [str(exc)])

    xml = payloads["Document.xml"].decode("utf-8", errors="replace")
    replaced = 0
    seen: set = set()

    def substitute(match: "re.Match[str]") -> str:
        nonlocal replaced
        raw = match.group(1)
        candidate = raw.replace("\\", "/")
        target = mapping.get(candidate) or mapping.get(raw)
        if not target:
            return match.group(0)
        if candidate in seen:
            return match.group(0)
        seen.add(candidate)
        replaced += 1
        # Preserve the quoting style the document used.
        if "\\" in raw and "/" in target:
            return match.group(0).replace(raw, target.replace("/", "\\"))
        return match.group(0).replace(raw, target)

    new_xml = XLinkPattern.sub(substitute, xml)
    if replaced == 0:
        return (0, [])

    payloads["Document.xml"] = new_xml.encode("utf-8")
    temp = path + ".mrfree.tmp"
    try:
        with zipfile.ZipFile(temp, "w", zipfile.ZIP_DEFLATED) as out:
            for name in names:
                out.writestr(name, payloads[name])
        os.replace(temp, path)
    except OSError as exc:
        try:
            if os.path.exists(temp):
                os.remove(temp)
        except OSError:
            pass
        return (0, ["yazılamadı: " + str(exc)])
    return (replaced, [])


def _classify(
    references: List[str],
    index: Dict[str, str],
    project_root: str,
) -> Tuple[List[Tuple[str, str]], List[str], List[str]]:
    """Sort references into repairable, already-correct and unresolvable."""
    repairable: List[Tuple[str, str]] = []
    correct: List[str] = []
    missing: List[str] = []
    project_norm = normalize_name(os.path.basename(project_root)) if project_root else ""

    for reference in references:
        if os.path.exists(reference):
            directory = os.path.dirname(reference)
            if project_root and normalize_name(os.path.basename(directory)) == project_norm:
                correct.append(reference)
                continue
        key = normalize_name(os.path.basename(reference))
        found = index.get(key)
        if found and found != reference:
            repairable.append((reference, found))
        elif found and found == reference:
            correct.append(reference)
        else:
            missing.append(os.path.basename(reference))
    return (repairable, correct, missing)


def repair_project(
    project_folder: str,
    extensions: Tuple[str, ...] = MODEL_EXTENSIONS,
    normalize_unicode: bool = True,
    include_subfolders: bool = True,
) -> Tuple[bool, str]:
    """Repair every model's references within ``project_folder``.

    Steps, mirroring the original's order:

    1. normalise file and folder names to NFC (so paths resolve at all);
    2. index the project by normalised name;
    3. for each model, read its reference table and rewrite stale paths.

    Nothing is opened, nothing is deleted, and no file is saved beyond the
    path rewrite itself.  Returns ``(changed_anything, report)``.
    """
    if not project_folder or not os.path.isdir(project_folder):
        return (False, "Klasör bulunamadı:\n" + str(project_folder))

    lines: List[str] = ["=" * 59, "  REFERANS ONARIM RAPORU", "=" * 59, ""]
    lines.append("Proje Klasörü : " + str(project_folder))
    lines.append("")

    renames = 0
    if normalize_unicode:
        name_log: List[str] = []
        renames = normalize_names_deep(project_folder, name_log)
        lines.append("--- Unicode Normalizasyon ---")
        lines.append("NFD->NFC yeniden adlandırma : " + str(renames))
        for entry in name_log[:40]:
            lines.append("  • " + entry)
        if len(name_log) > 40:
            lines.append("  ... (" + str(len(name_log) - 40) + " kayıt daha)")
        lines.append("")

    index = index_project(project_folder, extensions)
    if not index:
        lines.append("Projede model dosyası bulunamadı (" + ", ".join(extensions) + ").")
        return (False, "\n".join(lines))

    total_refs = 0
    total_fixed = 0
    missing_total: List[str] = []
    repaired_files: List[str] = []
    errors: List[str] = []

    targets: List[str] = []
    if include_subfolders:
        for dirpath, dirnames, filenames in os.walk(project_folder):
            dirnames.sort()
            for name in sorted(filenames):
                if os.path.splitext(name)[1].lower() in {ext.lower() for ext in extensions}:
                    targets.append(os.path.join(dirpath, name))
    else:
        for name in sorted(os.listdir(project_folder)):
            full = os.path.join(project_folder, name)
            if os.path.isfile(full) and os.path.splitext(name)[1].lower() in {e.lower() for e in extensions}:
                targets.append(full)

    for model in targets:
        references = read_references(model)
        if not references:
            continue
        total_refs += len(references)
        repairable, correct, missing = _classify(references, index, project_folder)
        if missing:
            missing_total.extend(sorted(set(missing)))
        if not repairable:
            continue
        mapping = {old: new for old, new in repairable}
        replaced, problems = _rewrite_references(model, mapping)
        errors.extend(problems)
        total_fixed += replaced
        if replaced:
            repaired_files.append(os.path.relpath(model, project_folder))
            for old, new in repairable:
                lines.append("  • " + os.path.basename(old) + " -> " + os.path.relpath(new, project_folder))

    lines.append("--- Model Referansları ---")
    lines.append("Taranan model     : " + str(len(targets)))
    lines.append("Toplam referans   : " + str(total_refs))
    lines.append("Düzeltilen yol    : " + str(total_fixed))
    lines.append("Eksik (bulunamadı): " + str(len(set(missing_total))))
    if repaired_files:
        lines.append("")
        lines.append("Düzeltilen dosyalar:")
        for name in repaired_files:
            lines.append("  • " + name)
    if missing_total:
        lines.append("")
        lines.append("Projede karşılığı olmayan referanslar:")
        for name in sorted(set(missing_total)):
            lines.append("  • " + name)
        lines.append("")
        lines.append("Bu referanslar FreeCAD'de 'kırık bağ' olarak görünür.")
        lines.append("MrFreeTool onları silmez; silmek yerine doğru dosyayı")
        lines.append("göstermenizi ister. Taşıma yapıldıysa dosyayı projeye kopyalayıp")
        lines.append("tekrar çalıştırın.")
    if errors:
        lines.append("")
        lines.append("Hatalar:")
        for error in sorted(set(errors)):
            lines.append("  • " + error)

    lines.append("")
    if total_fixed:
        lines.append("✓ Referanslar onarıldı. Hiçbir model açılmadı, taşıma yapılmadı.")
    elif missing_total:
        lines.append("⚠ Düzeltilebilir referans yok; eksik dosyalar listede.")
    else:
        lines.append("✓ Tüm referanslar doğru. Proje sağlıklı.")
    lines.append("")
    lines.append("NOT: Hiçbir dosya otomatik kaydedilmedi (yol yeniden yazımı hariç).")
    lines.append("Kaydetme kararı size aittir.")

    return (total_fixed > 0, "\n".join(lines))


def backup_project(project_folder: str, destination: str = "") -> str:
    """Copy the project folder aside before a repair run.  Returns the path."""
    if not project_folder or not os.path.isdir(project_folder):
        return ""
    if not destination:
        parent = os.path.dirname(os.path.abspath(project_folder))
        name = os.path.basename(os.path.abspath(project_folder))
        destination = os.path.join(parent, name + "_mrfree_backup")
    if os.path.exists(destination):
        return destination
    try:
        shutil.copytree(project_folder, destination)
    except OSError as exc:
        compat.console_log("backup failed: " + str(exc))
        return ""
    return destination


def resolve_reference(reference: str, roots: List[str]) -> str:
    """Locate a single reference under any of ``roots``, NFC-aware."""
    direct = resolve_nfc_path(reference)
    if direct and os.path.exists(direct):
        return direct
    for root in roots:
        found = index_project(root)
        candidate = found.get(normalize_name(os.path.basename(reference)))
        if candidate:
            return candidate
    return ""
