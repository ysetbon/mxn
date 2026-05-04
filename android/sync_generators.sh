#!/usr/bin/env bash
# Sync the vendored generator modules from src/ into the android bundle.
# Run from the android/ directory after editing src/mxn_*.py.

set -euo pipefail

cd "$(dirname "$0")"
SRC_DIR="../src"
DEST_DIR="mxn_app/core/generators"

for name in mxn_lh.py mxn_rh.py mxn_lh_strech.py mxn_rh_stretch.py; do
    cp "$SRC_DIR/$name" "$DEST_DIR/$name"
    echo "synced $name"
done
