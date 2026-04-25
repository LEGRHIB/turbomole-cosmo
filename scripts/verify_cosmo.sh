#!/bin/bash
# verify_cosmo.sh — Post-job sanity checks on COSMO output.
#
# Usage:
#   scripts/verify_cosmo.sh <molecule> [protocol]
# -----------------------------------------------------------------------------

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
source "$REPO_ROOT/config.sh"

MOLECULE="${1:-}"
PROTOCOL="${2:-$DEFAULT_PROTOCOL}"

if [[ -z "$MOLECULE" ]]; then
  echo "Usage: $0 <molecule> [protocol]" >&2
  exit 2
fi

MOL_DIR="$REPO_ROOT/molecules/$MOLECULE"
WORK_DIR="$MOL_DIR/$PROTOCOL"
FAIL=0

echo "=== verify_cosmo: $MOLECULE / $PROTOCOL ==="
echo "    Workdir: $WORK_DIR"
echo

if [[ ! -d "$WORK_DIR" ]]; then
  echo "FAIL : work directory not found: $WORK_DIR" >&2
  echo "       Run prep_cosmo.sh first." >&2
  exit 2
fi

# --- Check .cosmo file --------------------------------------------------------
COSMO_FILE="$WORK_DIR/$MOLECULE.cosmo"
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
for f in ridft.out dscf.out jobex.out; do
  [[ -f "$WORK_DIR/$f" ]] && SCF_LOG="$WORK_DIR/$f" && break
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
  echo "FAIL : no SCF output (ridft.out / dscf.out / jobex.out) found"
  FAIL=1
fi

# --- Check control $cosmo_out ------------------------------------------------
if grep -q '^\$cosmo_out' "$WORK_DIR/control" 2>/dev/null; then
  echo "OK   : \$cosmo_out present in control"
else
  echo "WARN : \$cosmo_out missing from control"
fi

# --- Check prep stamp ---------------------------------------------------------
if [[ -f "$WORK_DIR/prep_ok.stamp" ]]; then
  echo "OK   : prep_ok.stamp present"
else
  echo "WARN : prep_ok.stamp missing (prep may not have completed cleanly)"
fi

# --- Summary ------------------------------------------------------------------
echo
if [[ $FAIL -eq 0 ]]; then
  echo "✅ $MOLECULE ($PROTOCOL) — .cosmo is ready for COSMOtherm."
else
  echo "❌ Issues found — inspect the output files above."
  exit 1
fi
