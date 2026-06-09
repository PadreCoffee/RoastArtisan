#!/usr/bin/env bash
#
# make-windows-build-archive.sh
#
# Build a clean .zip containing exactly the files needed to build RoastArtisan
# on Windows (i.e. to run build-windows-x64-local.bat on the Windows machine).
#
# It uses `git archive`, so the archive contains ONLY git-tracked source:
#   - the full src/ tree
#   - the committed generated files the default build relies on
#     (src/uic/*.py, src/translations/*.qm, ...)
#   - src/requirements.txt, the PyInstaller *.spec files
#   - the *.bat build scripts, the NSIS installer (setup-install3-pi.nsi),
#     version-metadata.yml, WINDOWS-BUILD-README.txt, RUN-FROM-SOURCE-WINDOWS.bat
#
# Everything heavy / junk is excluded automatically because it is not tracked:
#   the mac/win virtualenvs (.venv-*), src/build, src/dist, __pycache__,
#   *.pyc, .DS_Store, built installers/dmgs.
#
# The Windows side creates its own .venv-win-x64 and downloads vc_redist.x64.exe,
# so neither is needed in the archive.
#
# Usage:
#   ./make-windows-build-archive.sh [REF] [OUTPUT_ZIP]
#
#     REF         git ref to package           (default: HEAD)
#     OUTPUT_ZIP  destination .zip path        (default: ../RoastArtisan-win-src-<sha>-<stamp>.zip)
#
# Examples:
#   ./make-windows-build-archive.sh
#   ./make-windows-build-archive.sh HEAD ~/Desktop/roastartisan-win.zip
#
set -euo pipefail

# --- resolve repo root so the script works from any working directory ---------
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(git -C "$script_dir" rev-parse --show-toplevel)"
cd "$repo_root"

ref="${1:-HEAD}"

# --- validate the ref ---------------------------------------------------------
if ! git rev-parse --verify --quiet "${ref}^{commit}" >/dev/null; then
  echo "error: '$ref' is not a valid git commit/ref" >&2
  exit 1
fi

short_sha="$(git rev-parse --short "$ref")"
stamp="$(date +%Y%m%d-%H%M)"
default_out="$(cd .. && pwd)/RoastArtisan-win-src-${short_sha}-${stamp}.zip"
out="${2:-$default_out}"

# Make the output path absolute (git archive -o is relative to cwd otherwise).
case "$out" in
  /*) : ;;                       # already absolute
  *)  out="$(pwd)/$out" ;;
esac

# --- warn (do not block) on a dirty working tree ------------------------------
# We archive the committed REF, not the working tree, so uncommitted edits are
# intentionally NOT included. Surface that so it is never a silent surprise.
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "warning: working tree has uncommitted changes." >&2
  echo "         Archiving the committed ref '$ref' ($short_sha) — local edits are NOT included." >&2
  echo "         Commit them first if you want them in the build." >&2
fi

echo "Packing tracked source at $ref ($short_sha)"
echo "  -> $out"

# --prefix gives a single clean top-level folder when unzipped on Windows.
git archive --format=zip --prefix="RoastArtisan-${short_sha}/" -o "$out" "$ref"

size="$(du -h "$out" | cut -f1 | tr -d ' ')"
count="$(git ls-tree -r --name-only "$ref" | wc -l | tr -d ' ')"

cat <<EOF

Done.
  Archive : $out
  Size    : $size
  Files   : $count tracked files

On the Windows machine:
  1. Unzip the archive.
  2. Open the  RoastArtisan-${short_sha}  folder.
  3. Install 64-bit Python 3.11+.
  4. Run  build-windows-x64-local.bat
       -> creates .venv-win-x64, downloads vc_redist, builds
          src\\dist\\RoastArtisan\\RoastArtisan.exe
  See WINDOWS-BUILD-README.txt for the fast run-from-source path and installer notes.
EOF
