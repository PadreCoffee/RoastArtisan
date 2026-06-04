#!/bin/bash
# ABOUT
# Local (non-CI) macOS Apple Silicon (arm64) build for RoastArtisan.
# Produces dist/RoastArtisan.app and RoastArtisan-mac-<version>.dmg via PyInstaller.
#
# This is the local counterpart to build-windows-x64-local.bat. Unlike build-macos3.sh
# (which is Appveyor-CI only), this script runs on a developer Mac.
#
# Usage:
#   ./build-macos-silicon-local.sh
#
# Regenerate derived UI/help/translation files first (off by default, generated
# files are already committed):
#   RUN_DERIVED=1 ./build-macos-silicon-local.sh
# ----------------------------------------------------------------------
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
SRC="$ROOT/src"
VENV="$ROOT/.venv-mac-arm64"
PYINSTALLER_VERSION="6.19.0"

echo
echo "RoastArtisan local macOS (Apple Silicon) build"
echo "=============================================="
echo

# --- platform checks -------------------------------------------------------
if [ "$(uname -s)" != "Darwin" ]; then
    echo "This script must be run on macOS." >&2
    exit 1
fi
ARCH="$(uname -m)"
if [ "$ARCH" != "arm64" ]; then
    echo "WARNING: current architecture is '$ARCH', not 'arm64' (Apple Silicon)." >&2
    echo "         artisan-mac.spec targets arm64; building on Intel may fail or produce" >&2
    echo "         a non-native binary. Run this on an Apple Silicon Mac." >&2
fi
if ! command -v python3 >/dev/null 2>&1; then
    echo "python3 was not found. Install Python 3.11+ (arm64) and try again." >&2
    exit 1
fi

# --- virtual environment ---------------------------------------------------
if [ ! -x "$VENV/bin/python" ]; then
    echo "Creating virtual environment at $VENV ..."
    python3 -m venv "$VENV"
fi
# shellcheck disable=SC1091
source "$VENV/bin/activate"

echo "Installing Python dependencies ..."
# --retries/--timeout make pip resilient to flaky networks (transient IncompleteRead).
PIP_NET_OPTS="--retries 10 --timeout 120"
# shellcheck disable=SC2086
python -m pip install $PIP_NET_OPTS --upgrade pip
# shellcheck disable=SC2086
python -m pip install $PIP_NET_OPTS -r "$SRC/requirements.txt"
# Build-only tooling. qt6-applications provides lrelease used by build-derived.sh.
# shellcheck disable=SC2086
python -m pip install $PIP_NET_OPTS "pyinstaller==$PYINSTALLER_VERSION" qt6-applications

cd "$SRC"

# --- optional derived-file regeneration ------------------------------------
if [ "${RUN_DERIVED:-0}" = "1" ]; then
    echo "Building derived files (ui/help/translations) ..."
    ./build-derived.sh macos
else
    echo "Skipping derived file generation. Set RUN_DERIVED=1 to force it."
fi

# --- bundle with PyInstaller ----------------------------------------------
VERSION="$(python -c 'import artisanlib; print(artisanlib.__version__)')"
echo "Building RoastArtisan $VERSION ..."

rm -rf build dist
pyinstaller -y --log-level=WARN artisan-mac.spec

echo
echo "Build finished:"
echo "  App: $SRC/dist/RoastArtisan.app"
if [ -f "$SRC/RoastArtisan-mac-$VERSION.dmg" ]; then
    echo "  DMG: $SRC/RoastArtisan-mac-$VERSION.dmg"
fi
echo
echo "Done."
