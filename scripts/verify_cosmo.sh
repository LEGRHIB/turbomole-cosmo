#!/bin/bash
# verify_cosmo.sh — Post-job sanity checks on COSMO output.
#
# Usage:
#   scripts/verify_cosmo.sh <molecule>
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
FAIL=0

echo "=== verify_cosmo: $MOLECULE ==="
echo

# --- Check .cosmo file --------------------------------------------------------
COSMO_FILE="$MOL_DIR/$MOLECULE.cosmo"
if [[ -f "$COSMO_FILE" ]]; then
  SIZE=$(stat -c%s "$COSMO_FILE" 2>/dev/null || stat -f%z "$COSMO_FILE" 2>/dev/null)
  if [[ "$SIZE" -gt 1024 ]]; then
    echo "OK   : $MOLECULE.cosmo exists (${SIZE} bytes)"
  else
    echo "WARN : $MOLECULE.cosmo exists but is very small ($SIZE bytes) — may be incomplete"
    FAIL=1
  fi
else
  echo "FAIL : $MOLECULE.cosmo not found"
  FAIL=1
fi

# --- Check SCF convergence ----------------------------------------------------
SCF_LOG=""
for f in ridft.out dscf.out; do
  [[ -f "$MOL_DIR/$f" ]] && SCF_LOG="$MOL_DIR/$f" && break
done

if [[ -n "$SCF_LOG" ]]; then
  LOG_NAME=$(basename "$SCF_LOG")
  if grep -q "convergence criteria satisfied" "$SCF_LOG"; then
    echo "OK   : SCF converged ($LOG_NAME)"
  elif grep -q "ENERGY CONVERGED" "$SCF_LOG"; then
    echo "OK   : SCF converged ($LOG_NAME)"
  else
    echo "FAIL : SCF did not converge in $LOG_NAME"
    echo "       Last energy lines:"
    grep -i "total energy" "$SCF_LOG" | tail -5 | sed 's/^/         /'
    FAIL=1
  fi
else
  echo "FAIL : no SCF output (ridft.out / dscf.out) found"
  FAIL=1
fi

# --- Check control $cosmo_out ------------------------------------------------
if grep -q '^\$cosmo_out' "$MOL_DIR/control" 2>/dev/null; then
  echo "OK   : \$cosmo_out present in control"
else
  echo "WARN : \$cosmo_out missing from control"
fi

# --- Summary ------------------------------------------------------------------
echo
if [[ $FAIL -eq 0 ]]; then
  echo "✅ $MOLECULE.cosmo is ready for COSMOtherm."
else
  echo "❌ Issues found — inspect the output files above."
  exit 1
fi
