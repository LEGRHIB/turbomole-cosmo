#!/bin/bash
# diff_against_known_good.sh — Regression-test prep output against a reference.
#
# Usage:
#   scripts/diff_against_known_good.sh <molecule>
#
# Expects:
#   molecules/<molecule>/reference/{coord,control,basis,mos}
# -----------------------------------------------------------------------------

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

MOLECULE="${1:-}"
if [[ -z "$MOLECULE" ]]; then
  echo "Usage: $0 <molecule>" >&2
  exit 2
fi

MOL_DIR="$REPO_ROOT/molecules/$MOLECULE"
REF_DIR="$MOL_DIR/reference"

if [[ ! -d "$REF_DIR" ]]; then
  echo "ERROR: reference dir not found: $REF_DIR" >&2
  echo "       Place your known-good coord/control/basis/mos files there." >&2
  exit 2
fi

FILES=(coord control basis mos)
FAIL=0

for f in "${FILES[@]}"; do
  if [[ ! -f "$MOL_DIR/$f" ]]; then
    echo "MISSING (generated): $f"
    FAIL=1
    continue
  fi
  if [[ ! -f "$REF_DIR/$f" ]]; then
    echo "MISSING (reference): $f — skipping"
    continue
  fi
  if diff -q "$REF_DIR/$f" "$MOL_DIR/$f" > /dev/null; then
    echo "OK   : $f (identical)"
  else
    echo "DIFF : $f"
    diff "$REF_DIR/$f" "$MOL_DIR/$f" | sed 's/^/       /'
    FAIL=1
  fi
done

if [[ $FAIL -eq 0 ]]; then
  echo
  echo "✅ All files match reference."
  exit 0
else
  echo
  echo "❌ Differences found. Cosmetic diffs (timestamps) are ok; semantic diffs need fixing." >&2
  exit 1
fi
