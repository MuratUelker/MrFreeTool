#!/usr/bin/env bash
# Install MrFreeTool into the FreeCAD Mod directory.
#
#   ./scripts/install.sh            # user install (recommended)
#   ./scripts/install.sh --link     # symlink instead of copy, for development
#   ./scripts/install.sh --system   # system-wide, needs root
#
# The target directory is taken from FreeCAD itself when it is on PATH, so the
# install lands exactly where FreeCAD will look.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$HERE")"
NAME="MrFreeTool"

MODE="user"
LINK=0
for arg in "$@"; do
    case "$arg" in
        --link)   LINK=1 ;;
        --system) MODE="system" ;;
        -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
        *) echo "unknown option: $arg" >&2; exit 2 ;;
    esac
done

# Ask FreeCAD where its Mod directory is; fall back to the documented defaults.
detect_mod_dir() {
    if command -v freecadcmd >/dev/null 2>&1; then
        freecadcmd -c "print(App.getUserAppDataDir())" 2>/dev/null | tail -1
        return
    fi
    if command -v FreeCADCmd >/dev/null 2>&1; then
        FreeCADCmd -c "print(App.getUserAppDataDir())" 2>/dev/null | tail -1
        return
    fi
    echo ""
}

if [ "$MODE" = "system" ]; then
    TARGET="/usr/share/freecad/Mod/$NAME"
else
    USER_APP="$(detect_mod_dir)"
    if [ -n "$USER_APP" ] && [ -d "$USER_APP" ]; then
        TARGET="$USER_APP/Mod/$NAME"
    else
        TARGET="${XDG_DATA_HOME:-$HOME/.local/share}/FreeCAD/Mod/$NAME"
    fi
fi

echo "Source : $ROOT"
echo "Target : $TARGET"

if [ -e "$TARGET" ] || [ -L "$TARGET" ]; then
    echo "Target already exists; replacing it."
    rm -rf "$TARGET"
fi
mkdir -p "$(dirname "$TARGET")"

if [ "$LINK" -eq 1 ]; then
    ln -s "$ROOT" "$TARGET"
    echo "Linked. Restart FreeCAD to load the workbench."
else
    mkdir -p "$TARGET"
    # Copy the code, not the working files.
    for item in mrfreecad icons InitGui.py package.xml README.md LICENSE; do
        [ -e "$ROOT/$item" ] && cp -r "$ROOT/$item" "$TARGET/"
    done
    find "$TARGET" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
    echo "Installed. Restart FreeCAD to load the workbench."
fi

cat <<'EOF'

Next steps
  1. Start FreeCAD and pick the "MrFreeTool" workbench.
  2. Open the panel from the toolbar.
  3. Set your TechDraw templates and logo images in the panel's gear button.
EOF
