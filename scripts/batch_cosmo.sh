#!/bin/bash
# batch_cosmo.sh — Run prep + submit for all molecules that have .xyz but no .cosmo
#
# Usage:
#   scripts/batch_cosmo.sh [protocol] [options]
#
# Options:
#   --slurm              Submit prep as SLURM jobs (large molecules)
#   --bigmem             Shortcut: --slurm --partition bigmem --cpus 72 --mem 2000000M
#   --partition NAME     Override SLURM partition
#   --cpus N             Override CPU count
#   --mem SIZE           Override memory
#   --time HH:MM:SS      Override wall time
# -----------------------------------------------------------------------------

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
source "$REPO_ROOT/config.sh"

# First positional arg is protocol, rest are flags
PROTOCOL="${1:-$DEFAULT_PROTOCOL}"
if [[ "$PROTOCOL" != --* ]]; then
  shift 2>/dev/null || true
else
  PROTOCOL="$DEFAULT_PROTOCOL"
fi
EXTRA_ARGS=("$@")

echo "=== batch_cosmo (protocol: $PROTOCOL) ==="
echo

SUBMITTED=0
SKIPPED=0

for MOL_DIR in "$REPO_ROOT"/molecules/*/; do
  MOLECULE=$(basename "$MOL_DIR")
  XYZ="$MOL_DIR/$MOLECULE.xyz"
  COSMO="$MOL_DIR/$PROTOCOL/$MOLECULE.cosmo"

  if [[ ! -f "$XYZ" ]]; then
    continue
  fi

  if [[ -f "$COSMO" ]]; then
    echo "SKIP : $MOLECULE (already has .cosmo file)"
    SKIPPED=$((SKIPPED + 1))
    continue
  fi

  echo "--- $MOLECULE ---"
  "$SCRIPT_DIR/run_cosmo.sh" "$MOLECULE" "$PROTOCOL" "${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"}"
  echo
  SUBMITTED=$((SUBMITTED + 1))
done

echo "=== batch complete: $SUBMITTED submitted, $SKIPPED skipped ==="
