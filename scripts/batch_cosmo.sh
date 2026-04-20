#!/bin/bash
# batch_cosmo.sh — Run prep + submit for all molecules that have .xyz but no .cosmo
#
# Usage:
#   scripts/batch_cosmo.sh [protocol]
# -----------------------------------------------------------------------------

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
source "$REPO_ROOT/config.sh"

PROTOCOL="${1:-$DEFAULT_PROTOCOL}"

echo "=== batch_cosmo (protocol: $PROTOCOL) ==="
echo

SUBMITTED=0
SKIPPED=0

for MOL_DIR in "$REPO_ROOT"/molecules/*/; do
  MOLECULE=$(basename "$MOL_DIR")
  XYZ="$MOL_DIR/$MOLECULE.xyz"
  COSMO="$MOL_DIR/$MOLECULE.cosmo"

  if [[ ! -f "$XYZ" ]]; then
    continue
  fi

  if [[ -f "$COSMO" ]]; then
    echo "SKIP : $MOLECULE (already has .cosmo file)"
    SKIPPED=$((SKIPPED + 1))
    continue
  fi

  echo "--- $MOLECULE ---"
  "$SCRIPT_DIR/run_cosmo.sh" "$MOLECULE" "$PROTOCOL"
  echo
  SUBMITTED=$((SUBMITTED + 1))
done

echo "=== batch complete: $SUBMITTED submitted, $SKIPPED skipped ==="
