#!/bin/bash
# cosmotherm_screen.sh — Run COSMO-RS pure-solvent screen + binary mixtures
# for one molecule's .cosmo file (from a given DFT protocol output).
#
# Usage:
#   scripts/cosmotherm_screen.sh <molecule> <dft-protocol>
#
# Example:
#   scripts/cosmotherm_screen.sh vancomycin BP-TZVPD-FINE
#
# Output:
#   molecules/<mol>/<dft-protocol>/cosmotherm/
#     ├── pure-screen.{inp,out,tab}
#     ├── mix-<label>.{inp,out,tab}    (one per binary mixture)
#     └── solvents-batch.list           (rendered batch list for COSMOtherm f_batch)
#
# After this finishes, run scripts/cosmotherm_postprocess.py to aggregate.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Source COSMOtherm env — populates PATH, CT_PARAM_PATH, CT_COSMO_DB_PATH, CT_LICENSE_DIR
# shellcheck source=cosmotherm_setup.sh
source "$SCRIPT_DIR/cosmotherm_setup.sh"

MOLECULE="${1:?usage: $0 <molecule> <dft-protocol>}"
DFT_PROTOCOL="${2:?usage: $0 <molecule> <dft-protocol>}"

MOL_DIR="$REPO_ROOT/molecules/$MOLECULE/$DFT_PROTOCOL"
COSMO_FILE="$MOL_DIR/$MOLECULE.cosmo"
PROTO_DIR="$REPO_ROOT/protocols/cosmotherm-screen"
WORK_DIR="$MOL_DIR/cosmotherm"

# --- pre-flight ---
if [[ ! -f "$COSMO_FILE" ]]; then
    echo "ERROR: .cosmo file not found at $COSMO_FILE" >&2
    echo "       Run prep + SCF for $MOLECULE/$DFT_PROTOCOL first." >&2
    exit 2
fi
for f in screen-pure.tmpl screen-mixture.tmpl solvents-pure.list mixtures-binary.list; do
    if [[ ! -f "$PROTO_DIR/$f" ]]; then
        echo "ERROR: missing $PROTO_DIR/$f" >&2
        exit 2
    fi
done

mkdir -p "$WORK_DIR"

# Reference path for solvent .cosmo files (BP-TZVPD-FINE COSMObase)
FDIR="$CT_COSMO_DB_PATH/BP-TZVPD-FINE"

echo "=== cosmotherm_screen ==="
echo "  Molecule:     $MOLECULE"
echo "  DFT protocol: $DFT_PROTOCOL"
echo "  Solute .cosmo: $COSMO_FILE"
echo "  Workdir:      $WORK_DIR"
echo "  COSMObase:    $FDIR"
echo

# --- 1. Render pure-solvent batch list (strip comments / blanks, append _c0.cosmo) ---
SOLVENTS_LIST="$WORK_DIR/solvents-batch.list"
grep -v '^[[:space:]]*#' "$PROTO_DIR/solvents-pure.list" \
    | sed 's/[[:space:]]*$//' \
    | grep -v '^[[:space:]]*$' \
    | sed 's|$|_c0.cosmo|' \
    > "$SOLVENTS_LIST"
N_PURE=$(wc -l < "$SOLVENTS_LIST")
echo "[1/2] pure-solvent screen ($N_PURE solvents)..."

# --- 2. Render the pure-screen input ---
PURE_INP="$WORK_DIR/pure-screen.inp"
sed \
    -e "s|__CT_PARAM_PATH__|$CT_PARAM_PATH|g" \
    -e "s|__CT_LICENSE_DIR__|$CT_LICENSE_DIR|g" \
    -e "s|__FDIR__|$FDIR|g" \
    -e "s|__MOLECULE__|$MOLECULE|g" \
    -e "s|__MOL_COSMO__|$COSMO_FILE|g" \
    -e "s|__SOLVENTS_LIST__|$SOLVENTS_LIST|g" \
    "$PROTO_DIR/screen-pure.tmpl" > "$PURE_INP"

# Run pure screen (cosmotherm reads input from cwd, writes <input>.{out,tab})
( cd "$WORK_DIR" && cosmotherm "$(basename "$PURE_INP")" )
echo "  -> $WORK_DIR/pure-screen.tab"

# --- 3. Mixture screens ---
echo
echo "[2/2] binary-mixture screens..."
i=0
ok=0
fail=0
while IFS= read -r line || [[ -n "$line" ]]; do
    # Skip comments and blanks
    [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue

    # Parse: label sol1 sol2 x1 x2 (whitespace-separated)
    read -r label sol1 sol2 x1 x2 _ <<< "$line"
    [[ -z "$label" ]] && continue
    i=$((i + 1))

    MIX_INP="$WORK_DIR/mix-${label}.inp"
    sed \
        -e "s|__CT_PARAM_PATH__|$CT_PARAM_PATH|g" \
        -e "s|__CT_LICENSE_DIR__|$CT_LICENSE_DIR|g" \
        -e "s|__FDIR__|$FDIR|g" \
        -e "s|__MOLECULE__|$MOLECULE|g" \
        -e "s|__MOL_COSMO__|$COSMO_FILE|g" \
        -e "s|__MIX_LABEL__|$label|g" \
        -e "s|__SOLVENT1__|$sol1|g" \
        -e "s|__SOLVENT2__|$sol2|g" \
        -e "s|__X_SOLVENT1__|$x1|g" \
        -e "s|__X_SOLVENT2__|$x2|g" \
        "$PROTO_DIR/screen-mixture.tmpl" > "$MIX_INP"

    printf '  [%2d] %-30s %s/%s = %s/%s ... ' "$i" "$label" "$sol1" "$sol2" "$x1" "$x2"
    if ( cd "$WORK_DIR" && cosmotherm "$(basename "$MIX_INP")" ) >/dev/null 2>&1; then
        echo "ok"
        ok=$((ok + 1))
    else
        echo "FAIL (see $WORK_DIR/mix-${label}.out)"
        fail=$((fail + 1))
    fi
done < "$PROTO_DIR/mixtures-binary.list"

echo
echo "[done] pure: 1 + mixtures: $ok ok / $fail fail (total $i)"
echo "       Outputs in: $WORK_DIR"
echo "       Aggregate:  scripts/cosmotherm_postprocess.py $MOLECULE $DFT_PROTOCOL"
