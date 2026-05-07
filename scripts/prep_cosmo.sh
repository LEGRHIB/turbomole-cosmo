#!/bin/bash
# prep_cosmo.sh — Run x2t + define + cosmoprep for one molecule / one protocol.
#
# By default runs on the login node (small molecules).
# With --slurm, submits as a SLURM job (large molecules needing bigmem).
#
# Output goes into molecules/<molecule>/<protocol>/ so multiple protocols
# can coexist without overwriting each other.
#
# Usage:
#   scripts/prep_cosmo.sh <molecule> [protocol] [options]
#
# Options:
#   --slurm              Submit prep as a SLURM job instead of running locally
#   --partition NAME     SLURM partition (default: from config.sh)
#   --cpus N             CPU count for SLURM prep job
#   --mem SIZE           Memory for SLURM prep job (e.g. 2000000M)
#   --time HH:MM:SS      Wall time for SLURM prep job
#
# Examples:
#   scripts/prep_cosmo.sh bradykinin def2-SVP
#   scripts/prep_cosmo.sh vancomycin BP-TZVPD-FINE
#   scripts/prep_cosmo.sh lysozyme BP-TZVPD-FINE --slurm --partition bigmem --cpus 72 --mem 2000000M
# -----------------------------------------------------------------------------

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
export REPO_ROOT
source "$REPO_ROOT/config.sh"

# --- Parse arguments ----------------------------------------------------------
MOLECULE=""
PROTOCOL=""
USE_SLURM=false
OVR_PARTITION=""
OVR_CPUS=""
OVR_MEM=""
OVR_TIME=""

POSITIONAL=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --slurm)      USE_SLURM=true; shift ;;
    --partition)  OVR_PARTITION="$2"; shift 2 ;;
    --cpus)       OVR_CPUS="$2"; shift 2 ;;
    --mem)        OVR_MEM="$2"; shift 2 ;;
    --time)       OVR_TIME="$2"; shift 2 ;;
    --help|-h)
      head -n 25 "$0" | grep '^#' | sed 's/^# \?//'
      exit 0
      ;;
    *)
      POSITIONAL+=("$1"); shift ;;
  esac
done

MOLECULE="${POSITIONAL[0]:-}"
PROTOCOL="${POSITIONAL[1]:-$DEFAULT_PROTOCOL}"

if [[ -z "$MOLECULE" ]]; then
  echo "Usage: $0 <molecule> [protocol] [--slurm] [--partition P] [--cpus N] [--mem M] [--time T]" >&2
  echo "       Available protocols: $(ls "$REPO_ROOT/protocols" | tr '\n' ' ')" >&2
  exit 2
fi

MOL_DIR="$REPO_ROOT/molecules/$MOLECULE"
PROTO_DIR="$REPO_ROOT/protocols/$PROTOCOL"
WORK_DIR="$MOL_DIR/$PROTOCOL"
LOG_DIR="$WORK_DIR/logs"

# --- Pre-flight checks --------------------------------------------------------
if [[ ! -d "$MOL_DIR" ]]; then
  echo "ERROR: molecule directory not found: $MOL_DIR" >&2
  exit 2
fi
if [[ ! -f "$MOL_DIR/$MOLECULE.xyz" ]]; then
  echo "ERROR: $MOL_DIR/$MOLECULE.xyz not found." >&2
  echo "       Run prepare_molecule.py first to generate the XYZ:" >&2
  echo "       python3 scripts/prepare_molecule.py <input.pdb> $MOLECULE <pH> [--chains A,C]" >&2
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

mkdir -p "$WORK_DIR"
mkdir -p "$LOG_DIR"

# --- Read molecular charge ----------------------------------------------------
CHARGE_FILE="$MOL_DIR/charge.txt"
if [[ -f "$CHARGE_FILE" ]]; then
  CHARGE="$(cat "$CHARGE_FILE" | tr -d '[:space:]')"
else
  echo "WARN: $CHARGE_FILE not found — defaulting to charge=0" >&2
  echo "      Run prepare_molecule.py first for correct pH-dependent charge." >&2
  CHARGE="0"
fi

# --- Atom count hint ----------------------------------------------------------
if [[ -f "$MOL_DIR/$MOLECULE.xyz" ]]; then
  N_ATOMS=$(head -n1 "$MOL_DIR/$MOLECULE.xyz" | tr -d '[:space:]')
  if [[ "$N_ATOMS" -gt 500 ]] && ! $USE_SLURM; then
    echo "NOTE: $MOLECULE has $N_ATOMS atoms. Consider using --slurm --partition bigmem for define." >&2
    echo "      define's EHT guess with def2-TZVPD may need >200GB RAM for large molecules." >&2
    echo
  fi
fi

# ==============================================================================
# SLURM mode: generate a prep job script and submit it
# ==============================================================================
if $USE_SLURM; then
  PREP_CPUS="${OVR_CPUS:-${SLURM_BIGMEM_CPUS:-72}}"
  PREP_MEM="${OVR_MEM:-${SLURM_BIGMEM_MEM:-2000000M}}"
  PREP_TIME="${OVR_TIME:-${SLURM_BIGMEM_TIME:-72:00:00}}"
  PREP_PARTITION="${OVR_PARTITION:-${PARTITION}}"

  SLURM_SCRIPT="$WORK_DIR/prep_${MOLECULE}.slurm"

  cat > "$SLURM_SCRIPT" <<SLURM_EOF
#!/bin/bash -l
#SBATCH --clusters=${CLUSTER}
#SBATCH --partition=${PREP_PARTITION}
#SBATCH --account=${ACCOUNT}
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=${PREP_CPUS}
#SBATCH --time=${PREP_TIME}
#SBATCH --mem=${PREP_MEM}
#SBATCH --job-name=${MOLECULE}-${PROTOCOL}-prep
#SBATCH --output=${WORK_DIR}/prep-cosmo.out
#SBATCH --error=${WORK_DIR}/prep-cosmo.err

set -euo pipefail

# --- Paths ---
MOL_DIR="${MOL_DIR}"
PROTO_DIR="${PROTO_DIR}"
WORK_DIR="${WORK_DIR}"
LOG_DIR="${LOG_DIR}"
MOLECULE="${MOLECULE}"
PROTOCOL="${PROTOCOL}"
CHARGE="${CHARGE}"

cd "\$WORK_DIR"

# Remove any stale stamp from previous attempts
rm -f prep_ok.stamp

# --- Load TURBOMOLE ---
source ${TURBOMOLE_ROOT}/vars
export PARA_ARCH=SMP
export TURBOMOLE_SYSNAME=${TURBOMOLE_SYSNAME}
export PATH=${TURBOMOLE_ROOT}/bin/${TURBOMOLE_SYSNAME}:${TURBOMOLE_ROOT}/scripts:\$PATH

echo "=== prep_cosmo (SLURM job \$SLURM_JOB_ID) ==="
echo "  Molecule: \$MOLECULE"
echo "  Protocol: \$PROTOCOL"
echo "  Charge:   \$CHARGE"
echo "  Workdir:  \$WORK_DIR"
echo "  Node:     \$(hostname)"
echo "  CPUs:     \$SLURM_CPUS_PER_TASK"
echo "  Memory:   ${PREP_MEM}"
echo

# --- Step 1: xyz -> coord ---
echo "[1/4] x2t: \$MOLECULE.xyz -> coord"
x2t "\$MOL_DIR/\$MOLECULE.xyz" > coord
if ! head -n 1 coord | grep -q '^\\\$coord'; then
  echo "ERROR: coord file does not start with \\\$coord — x2t failed?" >&2
  head coord >&2
  exit 4
fi
echo "      coord ok (\$(wc -l < coord) lines)"

# --- Step 2: define ---
echo "[2/4] define < \$PROTOCOL/define.in (charge=\$CHARGE)"
rm -f control basis mos auxbasis
DEFINE_TMP="\$(mktemp)"
sed "s/__CHARGE__/\$CHARGE/g" "\$PROTO_DIR/define.in" > "\$DEFINE_TMP"
if ! cat "\$DEFINE_TMP" | define > "\$LOG_DIR/define.log" 2>&1; then
  echo "ERROR: define exited non-zero. See \$LOG_DIR/define.log" >&2
  tail -n 30 "\$LOG_DIR/define.log" >&2
  rm -f "\$DEFINE_TMP"
  exit 5
fi
rm -f "\$DEFINE_TMP"
for f in control basis mos; do
  if [[ ! -s "\$f" ]]; then
    echo "ERROR: define did not produce \$f. See \$LOG_DIR/define.log" >&2
    tail -n 30 "\$LOG_DIR/define.log" >&2
    exit 5
  fi
done
echo "      control/basis/mos ok"

# --- Step 3: cosmoprep ---
echo "[3/4] cosmoprep < \$PROTOCOL/cosmoprep.in (with __MOLECULE__ = \$MOLECULE)"
COSMO_TMP="\$(mktemp)"
sed "s/__MOLECULE__/\$MOLECULE/g" "\$PROTO_DIR/cosmoprep.in" > "\$COSMO_TMP"
if ! cosmoprep < "\$COSMO_TMP" > "\$LOG_DIR/cosmoprep.log" 2>&1; then
  echo "ERROR: cosmoprep exited non-zero. See \$LOG_DIR/cosmoprep.log" >&2
  tail -n 30 "\$LOG_DIR/cosmoprep.log" >&2
  rm -f "\$COSMO_TMP"
  exit 6
fi
rm -f "\$COSMO_TMP"
if ! grep -q 'cosmoprep ended normally' "\$LOG_DIR/cosmoprep.log"; then
  echo "WARN: cosmoprep log does not say 'ended normally' — inspect manually:" >&2
  tail -n 20 "\$LOG_DIR/cosmoprep.log" >&2
fi

# --- Step 4: verify control has \$cosmo_out ---
echo "[4/4] verifying control has \\\$cosmo_out ..."
if ! grep -q "^\\\$cosmo_out file=\$MOLECULE.cosmo" control; then
  echo "ERROR: control does not contain '\\\$cosmo_out file=\$MOLECULE.cosmo'" >&2
  echo "       Inspect control and \$LOG_DIR/cosmoprep.log" >&2
  exit 7
fi
echo "      \\\$cosmo_out ok"

# Protocol-specific sanity (BP-TZVPD-* must have DFT + RI)
if [[ "\$PROTOCOL" == BP-TZVPD-* ]]; then
  for needle in '\\\$dft' '\\\$rij' 'def2-TZVPD'; do
    if ! grep -q "\$needle" control basis 2>/dev/null; then
      echo "WARN: expected '\$needle' in control/basis for \$PROTOCOL but not found" >&2
    fi
  done
fi

# --- Step 4b: Apply protocol-specific SCF tuning ---
echo "[4b/4] applying protocol SCF tuning"
bash "${REPO_ROOT}/scripts/_tune_scf.sh" "\$PROTOCOL"

# --- Success stamp ---
echo "PREP_OK" > prep_ok.stamp
echo "\$(date -Iseconds)" >> prep_ok.stamp
echo "job=\$SLURM_JOB_ID node=\$(hostname) protocol=\$PROTOCOL charge=\$CHARGE" >> prep_ok.stamp

echo
echo "Prep complete for \$MOLECULE (\$PROTOCOL)."
echo "prep_ok.stamp written — verify, then submit SCF job."
SLURM_EOF

  chmod +x "$SLURM_SCRIPT"

  echo "=== prep_cosmo (SLURM mode) ==="
  echo "  Molecule:  $MOLECULE"
  echo "  Protocol:  $PROTOCOL"
  echo "  Charge:    $CHARGE"
  echo "  Workdir:   $WORK_DIR"
  echo "  SLURM:     $SLURM_SCRIPT"
  echo "  Cluster:   $CLUSTER / $PREP_PARTITION / $ACCOUNT"
  echo "  Resources: ${PREP_CPUS} CPUs, ${PREP_MEM} mem, ${PREP_TIME} wall"
  echo

  JOB_OUTPUT=$(sbatch "$SLURM_SCRIPT")
  JOB_ID=$(echo "$JOB_OUTPUT" | grep -oP '\d+')

  echo "$JOB_OUTPUT"
  echo
  echo "Prep Job ID: $JOB_ID"
  echo "Monitor:     squeue --clusters=$CLUSTER -j $JOB_ID"
  echo
  echo "After job completes, verify prep succeeded:"
  echo "  1. Check stamp:  cat $WORK_DIR/prep_ok.stamp"
  echo "  2. Check logs:   tail $LOG_DIR/define.log $LOG_DIR/cosmoprep.log"
  echo "  3. Check control: grep '\$cosmo_out' $WORK_DIR/control"
  echo
  echo "Then submit the SCF/optimization job:"
  echo "  scripts/submit_cosmo.sh $MOLECULE $PROTOCOL --partition $PREP_PARTITION --cpus $PREP_CPUS --mem $PREP_MEM"

  exit 0
fi

# ==============================================================================
# Local mode (login node): original behavior
# ==============================================================================

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
echo "  Charge:   $CHARGE"
echo "  Workdir : $WORK_DIR"
echo

cd "$WORK_DIR"

# --- Step 1: xyz -> coord -----------------------------------------------------
echo "[1/4] x2t: $MOLECULE.xyz -> coord"
x2t "$MOL_DIR/$MOLECULE.xyz" > coord
if ! head -n 1 coord | grep -q '^\$coord'; then
  echo "ERROR: coord file does not start with \$coord — x2t failed?" >&2
  head coord >&2
  exit 4
fi
echo "      coord ok ($(wc -l < coord) lines)"

# --- Step 2: define -----------------------------------------------------------
echo "[2/4] define < $PROTOCOL/define.in (charge=$CHARGE)"
rm -f control basis mos auxbasis
DEFINE_TMP="$(mktemp)"
sed "s/__CHARGE__/$CHARGE/g" "$PROTO_DIR/define.in" > "$DEFINE_TMP"
if ! cat "$DEFINE_TMP" | define > "$LOG_DIR/define.log" 2>&1; then
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
trap 'rm -f "$COSMO_TMP" "$DEFINE_TMP"' EXIT
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

# Protocol-specific sanity (BP-TZVPD-* must have DFT + RI)
if [[ "$PROTOCOL" == BP-TZVPD-* ]]; then
  for needle in '\$dft' '\$rij' 'def2-TZVPD'; do
    if ! grep -q "$needle" control basis 2>/dev/null; then
      echo "WARN: expected '$needle' in control/basis for $PROTOCOL but not found" >&2
    fi
  done
fi

# --- Step 4b: Apply protocol-specific SCF tuning -----------------------------
echo "[4b/4] applying protocol SCF tuning"
bash "$REPO_ROOT/scripts/_tune_scf.sh" "$PROTOCOL"

# Write prep_ok.stamp for consistency
echo "PREP_OK" > prep_ok.stamp
echo "$(date -Iseconds)" >> prep_ok.stamp
echo "local protocol=$PROTOCOL charge=$CHARGE" >> prep_ok.stamp

echo
echo "✅ Prep complete for $MOLECULE ($PROTOCOL)."
echo "   Next: scripts/submit_cosmo.sh $MOLECULE $PROTOCOL"
