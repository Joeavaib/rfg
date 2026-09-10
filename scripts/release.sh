#!/bin/sh
# Build a source archive + SHA256. Detached GPG signature if gpg is available.
# (cargo-dist/goreleaser are N/A for this Python CLI.)
set -eu
ROOT=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
VER=$(python3 -c "from rfg import __version__; print(__version__)" 2>/dev/null || echo 1.0.0)
DIST="$ROOT/dist"
mkdir -p "$DIST"
NAME="rfg-$VER"
TAR="$DIST/$NAME.tar.gz"
# portable archive of the CLI surface
tar -C "$ROOT" --exclude .git --exclude dist --exclude '__pycache__' \
  -czf "$TAR" rfg.py rfg schema docs LICENSE README.md Makefile justfile
if command -v sha256sum >/dev/null; then
  (cd "$DIST" && sha256sum "$NAME.tar.gz" > "$NAME.tar.gz.sha256")
elif command -v shasum >/dev/null; then
  (cd "$DIST" && shasum -a 256 "$NAME.tar.gz" > "$NAME.tar.gz.sha256")
fi
if command -v gpg >/dev/null && gpg --list-secret-keys >/dev/null 2>&1; then
  gpg --detach-sign --armor -o "$TAR.asc" "$TAR" || true
fi
echo "wrote $TAR"
ls -l "$DIST"
