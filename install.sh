#!/bin/sh
# ORBIT / TERMINAL UNIVERSE — installer.
#
# Puts the `orbit` command into ~/.local/bin, so the Solar System starts from anywhere:
#
#     curl -fsSL https://raw.githubusercontent.com/dszhlt/orbit-terminal-universe/main/install.sh | sh
#
# Uninstall:
#
#     curl -fsSL https://raw.githubusercontent.com/dszhlt/orbit-terminal-universe/main/install.sh | sh -s -- --uninstall
#
# Environment: ORBIT_BIN_DIR — where to put the command (default: ~/.local/bin).

set -eu

URL="https://raw.githubusercontent.com/dszhlt/orbit-terminal-universe/main/orbit.py"
BIN_DIR="${ORBIT_BIN_DIR:-$HOME/.local/bin}"
DEST="$BIN_DIR/orbit"

say() { printf '%s\n' "$*"; }
die() { printf 'orbit: %s\n' "$*" >&2; exit 1; }

if [ "${1:-}" = "--uninstall" ]; then
    if [ -e "$DEST" ]; then
        rm -f "$DEST"
        say "Removed $DEST"
    else
        say "Nothing to remove: $DEST does not exist"
    fi
    exit 0
fi

# ── requirements ────────────────────────────────────────────────────────
command -v python3 >/dev/null 2>&1 || die "python3 is required (3.8 or newer)"
python3 -c 'import sys; sys.exit(sys.version_info < (3, 8))' \
    || die "Python 3.8 or newer is required, found $(python3 -V 2>&1)"
python3 -c 'import curses' 2>/dev/null \
    || die "this Python has no curses module (on Debian/Ubuntu it is part of python3; on Windows use pipx — see README)"

# ── get orbit.py: from this clone if run as ./install.sh, else from GitHub ──
tmp="$(mktemp "${TMPDIR:-/tmp}/orbit.XXXXXX")"
trap 'rm -f "$tmp"' EXIT INT TERM

here=""
case "$0" in
    *install.sh) here="$(cd "$(dirname "$0")" && pwd)" ;;
esac
if [ -n "$here" ] && [ -f "$here/orbit.py" ]; then
    cp "$here/orbit.py" "$tmp"
    from="$here/orbit.py"
else
    if command -v curl >/dev/null 2>&1; then
        curl -fsSL "$URL" -o "$tmp" || die "download failed: $URL"
    elif command -v wget >/dev/null 2>&1; then
        wget -qO "$tmp" "$URL" || die "download failed: $URL"
    else
        die "need curl or wget to download orbit"
    fi
    from="GitHub"
fi
head -n 1 "$tmp" | grep -q '^#!/usr/bin/env python3' || die "downloaded file does not look like orbit.py"
python3 -c 'import ast, sys; ast.parse(open(sys.argv[1], encoding="utf-8").read())' "$tmp" \
    || die "downloaded orbit.py is broken, try again"

# ── install ─────────────────────────────────────────────────────────────
mkdir -p "$BIN_DIR"
chmod 755 "$tmp"
mv -f "$tmp" "$DEST"
trap - EXIT INT TERM
say "Installed orbit → $DEST (from $from)"

# ── make sure the command is on PATH ────────────────────────────────────
case ":$PATH:" in
    *":$BIN_DIR:"*)
        say ""
        say "Done! Type  orbit  to launch (orbit --lang ru for Russian)."
        exit 0 ;;
esac

case "$BIN_DIR" in                       # keep it readable: $HOME/.local/bin
    "$HOME"/*) shown="\$HOME${BIN_DIR#"$HOME"}" ;;
    *)         shown="$BIN_DIR" ;;
esac
line="export PATH=\"$shown:\$PATH\""
case "$(basename "${SHELL:-sh}")" in
    zsh)  rc="${ZDOTDIR:-$HOME}/.zshrc" ;;
    bash) rc="$HOME/.bashrc" ;;
    fish) rc="$HOME/.config/fish/conf.d/orbit.fish"
          line="fish_add_path \"$shown\"" ;;
    *)    rc="$HOME/.profile" ;;
esac
if [ -f "$rc" ] && grep -qF "$line" "$rc"; then
    :
else
    mkdir -p "$(dirname "$rc")"
    printf '\n# added by the orbit installer\n%s\n' "$line" >> "$rc"
    say "Added $BIN_DIR to PATH in $rc"
fi
say ""
say "Done! Open a new terminal and type  orbit  to launch (orbit --lang ru for Russian)."
