#!/bin/bash
# diff_against_known_good.sh — Regression-test prep output against a reference.
#
# Usage:
#   scripts/diff_against_known_good.sh <molecule> [protocol]
#
# Expects:
#   molecules/<molecule>/<protocol>/reference/{coord,control,basis,mos}
#
# Falls back to the legacy layout (pre protocol-subdir migration):
#   molecules/<molecule>/reference/{coord,control,basis,mos}
# -----------------------------------------------------------------------------

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
source "$REPO_ROOT/config.sh"

MOLECULE="${1:-}"
PROTOCOL="${2:-$DEFAULT_PROTOCOL}"

if [[ -z "$MOLECULE" ]]; then
  echo "Usage: $0 <molecule> [protocol]" >&2
  echo "       Available protocols: $(ls "$REPO_ROOT/protocols" | tr '\n' ' ')" >&2
  exit 2
fi

MOL_DIR="$REPO_ROOT/molecules/$MOLECULE/$PROTOCOL"
REF_DIR="$MOL_DIR/reference"

# Fallback to legacy layout if protocol-subdir reference not found
if [[ ! -d "$REF_DIR" ]]; then
  LEGACY_REF="$REPO_ROOT/molecules/$MOLECULE/reference"
  if [[ -d "$LEGACY_REF" ]]; then
    REF_DIR="$LEGACY_REF"
    echo "NOTE: using legacy reference dir at $LEGACY_REF" >&2
  else
    echo "ERROR: reference dir not found: $REF_DIR" >&2
    echo "       Place known-good coord/control/basis/mos files there." >&2
    exit 2
  fi
fi

if [[ ! -d "$MOL_DIR" ]]; then
  echo "ERROR: molecule/protocol dir not found: $MOL_DIR" >&2
  echo "       Run prep_cosmo.sh $MOLECULE $PROTOCOL first." >&2
  exit 2
fi

FILES=(coord control basis mos)
FAIL=0

echo "=== diff_against_known_good: $MOLECULE / $PROTOCOL ==="
echo "  Generated: $MOL_DIR"
echo "  Reference: $REF_DIR"
echo

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
  echo "All files match reference."
  exit 0
else
  echo
  echo "Differences found. Cosmetic diffs (timestamps) are ok; semantic diffs need fixing." >&2
  exit 1
fi
