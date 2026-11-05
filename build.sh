#!/usr/bin/env bash
# CaptionShot - build the macOS app.  Run:  ./build.sh
# Result: dist/CaptionShot.app and dist/CaptionShot-macOS-<arm64|x86_64>.zip
# Needs: Python 3.10-3.15 (set PYTHON=/path/to/python to choose one).
set -euo pipefail
cd "$(dirname "$0")"

[ "$(uname -s)" = "Darwin" ] || { echo "build.sh is for macOS. On Windows run build.bat." >&2; exit 1; }
PY="${PYTHON:-python3}"
ARCH="$(uname -m)"

echo "[1/4] Checking Python..."
"$PY" -c "import sys; v=sys.version_info; print('  Python %d.%d' % v[:2]); sys.exit(0 if (3,10)<=v[:2]<=(3,15) else 1)" \
  || { echo "  Use Python 3.10 to 3.15." >&2; exit 1; }

echo "[2/4] Creating a clean build environment (.venv-build)..."
[ -x .venv-build/bin/python ] || "$PY" -m venv .venv-build
VPY="$PWD/.venv-build/bin/python"
"$VPY" -m pip install --disable-pip-version-check -q --upgrade pip
"$VPY" -m pip install --disable-pip-version-check -q -r packaging/requirements-build.txt

echo "[3/4] Packaging the app with PyInstaller..."
rm -rf dist/CaptionShot dist/CaptionShot.app dist/CaptionShot-macOS-*.zip
"$VPY" -m PyInstaller --noconfirm --clean --distpath dist --workpath build packaging/CaptionShot.spec
[ -d dist/CaptionShot.app ] || { echo "  PyInstaller finished but CaptionShot.app is missing." >&2; exit 1; }

echo "[4/4] Self-test of the packaged app..."
REPORT="${TMPDIR:-/tmp}"
REPORT="${REPORT%/}/captionshot_selftest.txt"
rm -f "$REPORT"
RC=0
dist/CaptionShot.app/Contents/MacOS/CaptionShot --selftest || RC=$?
[ -f "$REPORT" ] || { echo "  The app did not start (no self-test report). Exit code $RC." >&2; exit 1; }
cat "$REPORT"; echo
[ "$RC" -eq 0 ] || exit 1

# ditto keeps the symlinks and code signature inside the bundle; plain zip can break them.
ditto -c -k --sequesterRsrc --keepParent dist/CaptionShot.app "dist/CaptionShot-macOS-$ARCH.zip"
echo "DONE: dist/CaptionShot-macOS-$ARCH.zip"
