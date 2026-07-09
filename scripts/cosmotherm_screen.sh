#!/bin/bash
# cosmotherm_screen.sh — ONE COSMOtherm solubility-screening job for a molecule:
# all pure solvents + all binary mixtures, each returning log10(x_RS) on one
# relative scale. Multi-conformer, reading COSMObase in place — matches the
# COSMOthermX desktop layout.
#
# Usage:
#   scripts/cosmotherm_screen.sh <molecule> <dft-protocol>
#
# Env:
#   GENERATE_ONLY=1   build screen.inp and stop (for inspection); do not run cosmotherm
#
# Output (molecules/<mol>/<dft-protocol>/cosmotherm/):
#   screen.inp   generated COSMOtherm input
#   screen.tab   results (pures + mixtures, log10(x_RS))   [after a real run]
#   screen.out   COSMOtherm log
#
# After a run: scripts/cosmotherm_postprocess.py <molecule> <dft-protocol>

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# shellcheck source=cosmotherm_setup.sh
source "$SCRIPT_DIR/cosmotherm_setup.sh"

MOLECULE="${1:?usage: $0 <molecule> <dft-protocol>}"
DFT_PROTOCOL="${2:?usage: $0 <molecule> <dft-protocol>}"

MOL_DIR="$REPO_ROOT/molecules/$MOLECULE/$DFT_PROTOCOL"
COSMO_FILE="$MOL_DIR/$MOLECULE.cosmo"
PROTO_DIR="$REPO_ROOT/protocols/cosmotherm-screen"
WORK_DIR="$MOL_DIR/cosmotherm"

# --- Level-aware parameterization + COSMObase (from the DFT protocol) ---
# TZVP solute -> BP_TZVP (BP-TZVP-COSMO); TZVPD -> BP_TZVPD_FINE (BP-TZVPD-FINE).
case "$DFT_PROTOCOL" in
    BP-TZVP-*)   CTD="BP_TZVP_25.ctd"       ; DB_NAME="BP-TZVP-COSMO" ;;
    BP-TZVPD-*)  CTD="BP_TZVPD_FINE_25.ctd" ; DB_NAME="BP-TZVPD-FINE" ;;
    *)           CTD="BP_TZVPD_FINE_25.ctd" ; DB_NAME="BP-TZVPD-FINE" ;;
esac
COSMOBASE_DB="$CT_COSMO_DB_PATH/$DB_NAME"

# --- pre-flight ---
[[ -f "$COSMO_FILE" ]] || { echo "ERROR: solute .cosmo not found: $COSMO_FILE" >&2; exit 2; }
for f in solvents-pure.list mixtures-binary.list; do
    [[ -f "$PROTO_DIR/$f" ]] || { echo "ERROR: missing $PROTO_DIR/$f" >&2; exit 2; }
done
[[ -d "$COSMOBASE_DB" ]] || { echo "ERROR: COSMObase dir not found: $COSMOBASE_DB" >&2; exit 2; }

mkdir -p "$WORK_DIR"
SCREEN_INP="$WORK_DIR/screen.inp"

echo "=== cosmotherm_screen ==="
echo "  Molecule:      $MOLECULE"
echo "  DFT protocol:  $DFT_PROTOCOL"
echo "  CTD:           $CTD"
echo "  COSMObase:     $COSMOBASE_DB"
echo "  Solute .cosmo: $COSMO_FILE"
echo "  Input:         $SCREEN_INP"
echo

# --- build the single screening input (multi-conformer + x={} mixtures) ---
python3 "$SCRIPT_DIR/build_screen_input.py" \
    --molecule     "$MOLECULE" \
    --solute-cosmo "$COSMO_FILE" \
    --db-root      "$COSMOBASE_DB" \
    --ctd          "$CTD" \
    --cdir         "$CT_PARAM_PATH" \
    --ldir         "$CT_LICENSE_DIR" \
    --solvents     "$PROTO_DIR/solvents-pure.list" \
    --mixtures     "$PROTO_DIR/mixtures-binary.list" \
    > "$SCREEN_INP"

echo "  wrote $(grep -c '^f = ' "$SCREEN_INP") compound-file lines"
echo "  job line (truncated):"
grep '^tc=' "$SCREEN_INP" | cut -c1-150 | sed 's/^/    /'
echo

if [[ "${GENERATE_ONLY:-0}" == "1" ]]; then
    echo "GENERATE_ONLY=1 — input written, cosmotherm NOT run."
    echo "Inspect: $SCREEN_INP"
    exit 0
fi

# --- run cosmotherm (writes screen.tab + screen.out in WORK_DIR) ---
echo "Running cosmotherm..."
( cd "$WORK_DIR" && cosmotherm "$(basename "$SCREEN_INP")" ) || true

SCREEN_TAB="$WORK_DIR/screen.tab"
if [[ -f "$SCREEN_TAB" && -s "$SCREEN_TAB" ]]; then
    echo "  -> $SCREEN_TAB ($(wc -l < "$SCREEN_TAB") rows)"
    echo "  Aggregate: scripts/cosmotherm_postprocess.py $MOLECULE $DFT_PROTOCOL"
else
    echo "  ✗ screen FAILED — no screen.tab produced. See $WORK_DIR/screen.out" >&2
    grep -m 8 -iE 'error' "$WORK_DIR/screen.out" 2>/dev/null | sed 's/^/    /'
    exit 1
fi
