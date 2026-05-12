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

# Per-job FDIR populated with symlinks to:
#   1. The solute (molecule's .cosmo from molecule/protocol dir)
#   2. Every solvent .cosmo we'll need (from COSMObase BP-TZVPD-FINE)
# COSMOtherm only searches FDIR for f="bare-name" references and does
# NOT accept absolute paths in f= lines, so we build a unified FDIR
# containing both the user molecule AND the relevant solvents.
COSMOBASE_DB="$CT_COSMO_DB_PATH/BP-TZVPD-FINE"
LOCAL_FDIR="$WORK_DIR/cosmo-files"

echo "=== cosmotherm_screen ==="
echo "  Molecule:     $MOLECULE"
echo "  DFT protocol: $DFT_PROTOCOL"
echo "  Solute .cosmo: $COSMO_FILE"
echo "  Workdir:      $WORK_DIR"
echo "  Local FDIR:   $LOCAL_FDIR"
echo "  COSMObase:    $COSMOBASE_DB"
echo

# --- Build local FDIR (symlinks: solute + every solvent we'll reference) ---
mkdir -p "$LOCAL_FDIR"
ln -sf "$COSMO_FILE" "$LOCAL_FDIR/${MOLECULE}.cosmo"

# Always include water (required for force_qspr fusion-energy estimate)
declare -A NEEDED_SOLVENTS
NEEDED_SOLVENTS[h2o_c0.cosmo]=1

# Pure-solvent panel — first token only (ignores inline comments)
while IFS= read -r line || [[ -n "$line" ]]; do
    [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
    sname=$(echo "$line" | awk '{print $1}')
    [[ -n "$sname" ]] && NEEDED_SOLVENTS["${sname}_c0.cosmo"]=1
done < "$PROTO_DIR/solvents-pure.list"

# Solvents from binary mixtures
while IFS= read -r line || [[ -n "$line" ]]; do
    [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
    read -r _ sol1 sol2 _ _ _ <<< "$line"
    [[ -n "$sol1" ]] && NEEDED_SOLVENTS["${sol1}_c0.cosmo"]=1
    [[ -n "$sol2" ]] && NEEDED_SOLVENTS["${sol2}_c0.cosmo"]=1
done < "$PROTO_DIR/mixtures-binary.list"

# Strip inline comments from solvent names (e.g. "chcl3                    # chloroform")
N_OK=0
N_MISS=0
for sname in "${!NEEDED_SOLVENTS[@]}"; do
    src=$(find "$COSMOBASE_DB" -name "$sname" 2>/dev/null | head -1)
    if [[ -n "$src" ]]; then
        ln -sf "$src" "$LOCAL_FDIR/$sname"
        N_OK=$((N_OK + 1))
    else
        echo "  WARN: $sname not found in COSMObase" >&2
        N_MISS=$((N_MISS + 1))
    fi
done
echo "  staged $N_OK solvents into local FDIR ($N_MISS missing)"

# Use the local FDIR for all subsequent template substitutions
FDIR="$LOCAL_FDIR"

# --- 1. Render pure-solvent batch list (strip comments / blanks, append _c0.cosmo) ---
SOLVENTS_LIST="$WORK_DIR/solvents-batch.list"
grep -v '^[[:space:]]*#' "$PROTO_DIR/solvents-pure.list" \
    | sed 's/[[:space:]]*$//' \
    | grep -v '^[[:space:]]*$' \
    | awk '{print $1}' \
    | sed 's|$|_c0.cosmo|' \
    > "$SOLVENTS_LIST"
N_PURE=$(wc -l < "$SOLVENTS_LIST")
echo "[1/2] pure-solvent screen ($N_PURE solvents)..."

# --- 2. Render the pure-screen input ---
# All compounds referenced by bare filename; FDIR=$LOCAL_FDIR contains them all.
PURE_INP="$WORK_DIR/pure-screen.inp"
sed \
    -e "s|__CT_PARAM_PATH__|$CT_PARAM_PATH|g" \
    -e "s|__CT_LICENSE_DIR__|$CT_LICENSE_DIR|g" \
    -e "s|__FDIR__|$FDIR|g" \
    -e "s|__MOLECULE__|$MOLECULE|g" \
    -e "s|__SOLVENTS_LIST__|$SOLVENTS_LIST|g" \
    "$PROTO_DIR/screen-pure.tmpl" > "$PURE_INP"

# Run pure screen (cosmotherm reads input from cwd, writes <input>.{out,tab})
( cd "$WORK_DIR" && cosmotherm "$(basename "$PURE_INP")" ) || true
PURE_TAB="$WORK_DIR/pure-screen.tab"
if [[ -f "$PURE_TAB" && -s "$PURE_TAB" ]]; then
    echo "  -> $PURE_TAB ($(wc -l < "$PURE_TAB") rows)"
else
    echo "  ✗ pure-screen FAILED — no .tab produced. See $WORK_DIR/pure-screen.out"
    grep -m 5 -E 'ERROR|Error' "$WORK_DIR/pure-screen.out" 2>/dev/null | sed 's/^/    /'
fi

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
    MIX_TAB="$WORK_DIR/mix-${label}.tab"
    sed \
        -e "s|__CT_PARAM_PATH__|$CT_PARAM_PATH|g" \
        -e "s|__CT_LICENSE_DIR__|$CT_LICENSE_DIR|g" \
        -e "s|__FDIR__|$FDIR|g" \
        -e "s|__MOLECULE__|$MOLECULE|g" \
        -e "s|__MIX_LABEL__|$label|g" \
        -e "s|__SOLVENT1__|$sol1|g" \
        -e "s|__SOLVENT2__|$sol2|g" \
        -e "s|__X_SOLVENT1__|$x1|g" \
        -e "s|__X_SOLVENT2__|$x2|g" \
        "$PROTO_DIR/screen-mixture.tmpl" > "$MIX_INP"

    printf '  [%2d] %-30s %s/%s = %s/%s ... ' "$i" "$label" "$sol1" "$sol2" "$x1" "$x2"
    ( cd "$WORK_DIR" && cosmotherm "$(basename "$MIX_INP")" ) >/dev/null 2>&1 || true
    if [[ -f "$MIX_TAB" && -s "$MIX_TAB" ]]; then
        echo "ok"
        ok=$((ok + 1))
    else
        echo "FAIL (no .tab)"
        fail=$((fail + 1))
    fi
done < "$PROTO_DIR/mixtures-binary.list"

echo
echo "[done] pure: 1 + mixtures: $ok ok / $fail fail (total $i)"
echo "       Outputs in: $WORK_DIR"
echo "       Aggregate:  scripts/cosmotherm_postprocess.py $MOLECULE $DFT_PROTOCOL"
