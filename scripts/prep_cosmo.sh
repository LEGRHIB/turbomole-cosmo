#!/bin/bash
# prep_cosmo.sh — Run x2t + define + cosmoprep for one molecule / one protocol.
#
# Run on the HPC login node (NOT inside a SLURM job).
#
# Usage:
#   scripts/prep_cosmo.sh <molecule> [protocol]
#
# Examples:
#   scripts/prep_cosmo.sh bradykinin def2-SVP
#   scripts/prep_cosmo.sh vancomycin BP-TZVPD-FINE
#   scripts/prep_cosmo.sh vancomycin                  # uses DEFAULT_PROTOCOL
# -----------------------------------------------------------------------------

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
export REPO_ROOT
source "$REPO_ROOT/config.sh"

MOLECULE="${1:-}"
PROTOCOL="${2:-$DEFAULT_PROTOCOL}"

if [[ -z "$MOLECULE" ]]; then
  echo "Usage: $0 <molecule> [protocol]" >&2
  echo "       Available protocols: $(ls "$REPO_ROOT/protocols" | tr '\n' ' ')" >&2
  exit 2
fi

MOL_DIR="$REPO_ROOT/molecules/$MOLECULE"
PROTO_DIR="$REPO_ROOT/protocols/$PROTOCOL"
LOG_DIR="$MOL_DIR/logs"

# --- Pre-flight checks --------------------------------------------------------
if [[ ! -d "$MOL_DIR" ]]; then
  echo "ERROR: molecule directory not found: $MOL_DIR" >&2
  exit 2
fi
if [[ ! -f "$MOL_DIR/$MOLECULE.xyz" ]]; then
  echo "ERROR: $MOL_DIR/$MOLECULE.xyz not found." >&2
  echo "       Convert your PDB to XYZ first using Avogadro (Open OnDemand VNC):" >&2
  echo "       1. Open .pdb in Avogadro" >&2
  echo "       2. Build -> Add Hydrogens" >&2
  echo "       3. Save As -> $MOLECULE.xyz" >&2
  echo "       4. Place in $MOL_DIR/" >&2
  exit 2
fi
if [[ ! -d "$PROTO_DIR" ]]; then
  echo "ERROR: protocol not found: $PROTO_DIR" >&2
  echo "       Available: $(ls "$REPO_ROOT/protocols" | tr '\n' ' ')" >&2
  exit 2
fi
for f in define.in cosmoprep.in; do
  if [[ ! -f "$PROTO_DIR/$f" ]]; then
    echo "ERROR: protocol file missing: $PROTO_DIR/$f" >&2
    exit 2
  fi
done

mkdir -p "$LOG_DIR"

# --- Load TURBOMOLE -----------------------------------------------------------
if [[ ! -f "$TURBOMOLE_ROOT/vars" ]]; then
  echo "ERROR: TURBOMOLE vars not found at $TURBOMOLE_ROOT/vars" >&2
  exit 3
fi
source "$TURBOMOLE_ROOT/vars"
export PARA_ARCH=SMP
export TURBOMOLE_SYSNAME
export PATH="$TURBOMOLE_ROOT/bin/$TURBOMOLE_SYSNAME:$TURBOMOLE_ROOT/scripts:$PATH"

echo "=== prep_cosmo ==="
echo "  Molecule: $MOLECULE"
echo "  Protocol: $PROTOCOL"
echo "  Workdir : $MOL_DIR"
echo

cd "$MOL_DIR"

# --- Step 1: xyz -> coord -----------------------------------------------------
echo "[1/4] x2t: $MOLECULE.xyz -> coord"
x2t "$MOLECULE.xyz" > coord
if ! head -n 1 coord | grep -q '^\$coord'; then
  echo "ERROR: coord file does not start with \$coord — x2t failed?" >&2
  head coord >&2
  exit 4
fi
echo "      coord ok ($(wc -l < coord) lines)"

# --- Step 2: define -----------------------------------------------------------
echo "[2/4] define < $PROTOCOL/define.in"
rm -f control basis mos auxbasis
if ! define < "$PROTO_DIR/define.in" > "$LOG_DIR/define.log" 2>&1; then
  echo "ERROR: define exited non-zero. See $LOG_DIR/define.log" >&2
  tail -n 30 "$LOG_DIR/define.log" >&2
  exit 5
fi
for f in control basis mos; do
  if [[ ! -s "$f" ]]; then
    echo "ERROR: define did not produce $f. See $LOG_DIR/define.log" >&2
    tail -n 30 "$LOG_DIR/define.log" >&2
    exit 5
  fi
done
echo "      control/basis/mos ok"

# --- Step 3: cosmoprep --------------------------------------------------------
echo "[3/4] cosmoprep < $PROTOCOL/cosmoprep.in (with __MOLECULE__ = $MOLECULE)"
COSMO_TMP="$(mktemp)"
trap 'rm -f "$COSMO_TMP"' EXIT
sed "s/__MOLECULE__/$MOLECULE/g" "$PROTO_DIR/cosmoprep.in" > "$COSMO_TMP"
if ! cosmoprep < "$COSMO_TMP" > "$LOG_DIR/cosmoprep.log" 2>&1; then
  echo "ERROR: cosmoprep exited non-zero. See $LOG_DIR/cosmoprep.log" >&2
  tail -n 30 "$LOG_DIR/cosmoprep.log" >&2
  exit 6
fi
if ! grep -q 'cosmoprep ended normally' "$LOG_DIR/cosmoprep.log"; then
  echo "WARN: cosmoprep log does not say 'ended normally' — inspect manually:" >&2
  tail -n 20 "$LOG_DIR/cosmoprep.log" >&2
fi

# --- Step 4: verify control has $cosmo_out -----------------------------------
echo "[4/4] verifying control has \$cosmo_out ..."
if ! grep -q "^\$cosmo_out file=$MOLECULE.cosmo" control; then
  echo "ERROR: control does not contain '\$cosmo_out file=$MOLECULE.cosmo'" >&2
  echo "       Inspect control and $LOG_DIR/cosmoprep.log" >&2
  exit 7
fi
echo "      \$cosmo_out ok"

# Protocol-specific sanity (BP-TZVPD-FINE must have DFT + RI)
if [[ "$PROTOCOL" == "BP-TZVPD-FINE" ]]; then
  for needle in '\$dft' '\$rij' 'def2-TZVPD'; do
    if ! grep -q "$needle" control basis 2>/dev/null; then
      echo "WARN: expected '$needle' in control/basis for $PROTOCOL but not found" >&2
    fi
  done
fi

echo
echo "✅ Prep complete for $MOLECULE ($PROTOCOL)."
echo "   Next: scripts/submit_cosmo.sh $MOLECULE $PROTOCOL"
