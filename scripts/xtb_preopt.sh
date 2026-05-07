#!/bin/bash
# xtb_preopt.sh — GFN2-xTB geometry pre-optimization for rough starting geometries.
#
# Use this BEFORE DFT optimization when starting from 2D-generated structures
# (SDF → OpenBabel --gen3d). GFN2-xTB is orders of magnitude faster than DFT
# and will clean up bad bond angles, contacts, and conformer issues so the
# subsequent DFT SCF converges without problems.
#
# Runs TURBOMOLE's bundled xtb binary on the molecule's coord file.
# Updates the molecule's .xyz file with the optimized geometry.
#
# Usage:
#   scripts/xtb_preopt.sh <molecule> [options]
#
# Options:
#   --gfn N              GFN version: 0, 1, or 2 (default: 2)
#   --opt-level LEVEL    Optimization level: crude, sloppy, loose, lax,
#                        normal, tight, vtight, extreme (default: tight)
#   --slurm              Submit as a SLURM job instead of running locally
#   --partition NAME     SLURM partition (default: from config.sh)
#   --cpus N             CPU count (default: 16)
#   --mem SIZE           Memory (default: 20000M)
#   --time HH:MM:SS      Wall time (default: 02:00:00)
#
# Examples:
#   # Quick local pre-optimization (login node, small molecule)
#   scripts/xtb_preopt.sh vancomycin_2d
#
#   # On compute node for larger peptides
#   scripts/xtb_preopt.sh bombesin --slurm --partition bigmem --cpus 72
#
#   # GFN0 first (no SCF, always converges), then GFN2
#   scripts/xtb_preopt.sh mymolecule --gfn 0
#   scripts/xtb_preopt.sh mymolecule --gfn 2
# -----------------------------------------------------------------------------

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
export REPO_ROOT
source "$REPO_ROOT/config.sh"

# --- Parse arguments ----------------------------------------------------------
MOLECULE=""
GFN_VERSION=2
OPT_LEVEL="tight"
USE_SLURM=false
OVR_PARTITION=""
OVR_CPUS="16"
OVR_MEM="20000M"
OVR_TIME="02:00:00"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --gfn)        GFN_VERSION="$2"; shift 2 ;;
    --opt-level)  OPT_LEVEL="$2"; shift 2 ;;
    --slurm)      USE_SLURM=true; shift ;;
    --partition)  OVR_PARTITION="$2"; shift 2 ;;
    --cpus)       OVR_CPUS="$2"; shift 2 ;;
    --mem)        OVR_MEM="$2"; shift 2 ;;
    --time)       OVR_TIME="$2"; shift 2 ;;
    --help|-h)
      head -n 38 "$0" | grep '^#' | sed 's/^# \?//'
      exit 0
      ;;
    *)
      if [[ -z "$MOLECULE" ]]; then
        MOLECULE="$1"
      else
        echo "ERROR: unexpected argument: $1" >&2
        exit 2
      fi
      shift
      ;;
  esac
done

if [[ -z "$MOLECULE" ]]; then
  echo "Usage: $0 <molecule> [--gfn 2] [--opt-level tight] [--slurm] [--cpus N]" >&2
  exit 2
fi

MOL_DIR="$REPO_ROOT/molecules/$MOLECULE"
XTB_DIR="$MOL_DIR/GFN-xTB-OPT"
LOG_DIR="$XTB_DIR/logs"

# --- Pre-flight checks --------------------------------------------------------
if [[ ! -d "$MOL_DIR" ]]; then
  echo "ERROR: molecule directory not found: $MOL_DIR" >&2
  exit 2
fi
if [[ ! -f "$MOL_DIR/$MOLECULE.xyz" ]]; then
  echo "ERROR: $MOL_DIR/$MOLECULE.xyz not found." >&2
  exit 2
fi

# Read charge
CHARGE_FILE="$MOL_DIR/charge.txt"
if [[ -f "$CHARGE_FILE" ]]; then
  CHARGE="$(cat "$CHARGE_FILE" | tr -d '[:space:]')"
else
  echo "WARN: $CHARGE_FILE not found — defaulting to charge=0" >&2
  CHARGE="0"
fi

mkdir -p "$XTB_DIR"
mkdir -p "$LOG_DIR"

# --- Load TURBOMOLE (for x2t and xtb) ----------------------------------------
if [[ ! -f "$TURBOMOLE_ROOT/vars" ]]; then
  echo "ERROR: TURBOMOLE vars not found at $TURBOMOLE_ROOT/vars" >&2
  exit 3
fi

# ==============================================================================
# Core xTB optimization function (used in both local and SLURM modes)
# ==============================================================================
run_xtb_opt() {
  local WORK="$1"
  cd "$WORK"

  echo "=== GFN${GFN_VERSION}-xTB Pre-Optimization ==="
  echo "  Molecule:  $MOLECULE"
  echo "  Charge:    $CHARGE"
  echo "  GFN:       $GFN_VERSION"
  echo "  Opt level: $OPT_LEVEL"
  echo "  Workdir:   $WORK"
  echo

  # Step 1: Convert XYZ to TURBOMOLE coord
  echo "[1/3] x2t: $MOLECULE.xyz -> coord"
  x2t "$MOL_DIR/$MOLECULE.xyz" > coord
  if ! head -n 1 coord | grep -q '^\$coord'; then
    echo "ERROR: coord file does not start with \$coord — x2t failed?" >&2
    exit 4
  fi
  echo "      coord ok ($(wc -l < coord) lines)"

  # Step 2: Run xTB geometry optimization
  echo "[2/3] xtb --opt $OPT_LEVEL --gfn $GFN_VERSION --chrg $CHARGE"
  if ! xtb coord --opt "$OPT_LEVEL" --gfn "$GFN_VERSION" --chrg "$CHARGE" \
       > "$LOG_DIR/xtb_opt.log" 2>&1; then
    echo "ERROR: xtb exited non-zero. See $LOG_DIR/xtb_opt.log" >&2
    tail -n 30 "$LOG_DIR/xtb_opt.log" >&2
    exit 5
  fi

  if [[ ! -f xtbopt.coord ]]; then
    echo "ERROR: xtb did not produce xtbopt.coord" >&2
    exit 5
  fi
  echo "      xtb optimization converged"

  # Step 3: Convert optimized coord back to XYZ and update molecule
  echo "[3/3] Updating $MOLECULE.xyz with optimized geometry"

  # Backup original XYZ
  cp "$MOL_DIR/$MOLECULE.xyz" "$MOL_DIR/${MOLECULE}_pre_xtb.xyz"

  # Use TURBOMOLE's t2x to convert coord back to XYZ
  if ! t2x xtbopt.coord > "$MOL_DIR/$MOLECULE.xyz" 2>/dev/null; then
    # Fallback: manual conversion from coord to xyz
    echo "WARN: t2x failed, using manual conversion" >&2
    python3 -c "
import sys
lines = open('xtbopt.coord').readlines()
atoms = []
reading = False
for line in lines:
    line = line.strip()
    if line == '\$coord':
        reading = True
        continue
    if line.startswith('\$'):
        break
    if reading:
        parts = line.split()
        if len(parts) >= 4:
            # Convert Bohr to Angstrom
            x = float(parts[0]) * 0.529177249
            y = float(parts[1]) * 0.529177249
            z = float(parts[2]) * 0.529177249
            elem = parts[3].capitalize()
            atoms.append((elem, x, y, z))
with open('$MOL_DIR/$MOLECULE.xyz', 'w') as f:
    f.write(f'{len(atoms)}\n')
    f.write(f'GFN${GFN_VERSION}-xTB optimized geometry\n')
    for elem, x, y, z in atoms:
        f.write(f'{elem:2s} {x:16.10f} {y:16.10f} {z:16.10f}\n')
"
  fi

  # Copy optimized coord to xTB directory for reference
  cp xtbopt.coord "$XTB_DIR/coord_optimized"
  cp xtbopt.log "$XTB_DIR/" 2>/dev/null || true

  # Extract final energy from log
  FINAL_E=$(grep "TOTAL ENERGY" "$LOG_DIR/xtb_opt.log" | tail -1 | awk '{print $4}')
  N_CYCLES=$(grep -c "GEOMETRY OPTIMIZATION CYCLE" "$LOG_DIR/xtb_opt.log" 2>/dev/null || echo "?")

  # Write stamp
  echo "XTB_PREOPT_OK" > "$XTB_DIR/xtb_ok.stamp"
  echo "$(date -Iseconds)" >> "$XTB_DIR/xtb_ok.stamp"
  echo "gfn=$GFN_VERSION opt=$OPT_LEVEL charge=$CHARGE cycles=$N_CYCLES energy=$FINAL_E" >> "$XTB_DIR/xtb_ok.stamp"

  echo
  echo "Pre-optimization complete for $MOLECULE"
  echo "  Cycles:    $N_CYCLES"
  echo "  Energy:    $FINAL_E Hartree"
  echo "  Original:  $MOL_DIR/${MOLECULE}_pre_xtb.xyz (backup)"
  echo "  Optimized: $MOL_DIR/$MOLECULE.xyz (updated)"
  echo
  echo "  Next: run DFT optimization"
  echo "  scripts/run_cosmo.sh $MOLECULE BP-TZVPD-OPT"
}

# ==============================================================================
# SLURM mode
# ==============================================================================
if $USE_SLURM; then
  PREP_PARTITION="${OVR_PARTITION:-${PARTITION}}"
  SLURM_SCRIPT="$XTB_DIR/xtb_preopt_${MOLECULE}.slurm"

  cat > "$SLURM_SCRIPT" <<SLURM_EOF
#!/bin/bash -l
#SBATCH --clusters=${CLUSTER}
#SBATCH --partition=${PREP_PARTITION}
#SBATCH --account=${ACCOUNT}
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=${OVR_CPUS}
#SBATCH --time=${OVR_TIME}
#SBATCH --mem=${OVR_MEM}
#SBATCH --job-name=${MOLECULE}-xtb-opt
#SBATCH --output=${XTB_DIR}/xtb-preopt.out
#SBATCH --error=${XTB_DIR}/xtb-preopt.err

set -euo pipefail

module load xtb/6.7.1-gfbf-2024a
source ${TURBOMOLE_ROOT}/vars
export PARA_ARCH=SMP
export TURBOMOLE_SYSNAME=${TURBOMOLE_SYSNAME}
export PATH=${TURBOMOLE_ROOT}/bin/${TURBOMOLE_SYSNAME}:${TURBOMOLE_ROOT}/scripts:\$PATH
export OMP_NUM_THREADS=\$SLURM_CPUS_PER_TASK

WORKDIR=\$VSC_SCRATCH/${MOLECULE}-xtb-\$SLURM_JOB_ID
mkdir -p "\$WORKDIR"

# --- Inline the optimization steps ---
cd "\$WORKDIR"

echo "=== GFN${GFN_VERSION}-xTB Pre-Optimization (SLURM job \$SLURM_JOB_ID) ==="
echo "  Molecule:  ${MOLECULE}"
echo "  Charge:    ${CHARGE}"
echo "  GFN:       ${GFN_VERSION}"
echo "  Opt level: ${OPT_LEVEL}"
echo "  Node:      \$(hostname)"
echo "  CPUs:      \$SLURM_CPUS_PER_TASK"
echo

echo "[1/3] x2t: ${MOLECULE}.xyz -> coord"
x2t "${MOL_DIR}/${MOLECULE}.xyz" > coord

echo "[2/3] xtb --opt ${OPT_LEVEL} --gfn ${GFN_VERSION} --chrg ${CHARGE}"
xtb coord --opt "${OPT_LEVEL}" --gfn "${GFN_VERSION}" --chrg "${CHARGE}" \
    > "${LOG_DIR}/xtb_opt.log" 2>&1

if [[ ! -f xtbopt.coord ]]; then
  echo "ERROR: xtb did not produce xtbopt.coord" >&2
  exit 5
fi

echo "[3/3] Updating ${MOLECULE}.xyz with optimized geometry"
cp "${MOL_DIR}/${MOLECULE}.xyz" "${MOL_DIR}/${MOLECULE}_pre_xtb.xyz"

if ! t2x xtbopt.coord > "${MOL_DIR}/${MOLECULE}.xyz" 2>/dev/null; then
  python3 -c "
lines = open('xtbopt.coord').readlines()
atoms = []
reading = False
for line in lines:
    line = line.strip()
    if line == '\\\$coord':
        reading = True
        continue
    if line.startswith('\\\$'):
        break
    if reading:
        parts = line.split()
        if len(parts) >= 4:
            x = float(parts[0]) * 0.529177249
            y = float(parts[1]) * 0.529177249
            z = float(parts[2]) * 0.529177249
            elem = parts[3].capitalize()
            atoms.append((elem, x, y, z))
with open('${MOL_DIR}/${MOLECULE}.xyz', 'w') as f:
    f.write(f'{len(atoms)}\n')
    f.write('GFN${GFN_VERSION}-xTB optimized geometry\n')
    for elem, x, y, z in atoms:
        f.write(f'{elem:2s} {x:16.10f} {y:16.10f} {z:16.10f}\n')
"
fi

cp xtbopt.coord "${XTB_DIR}/coord_optimized"
cp xtbopt.log "${XTB_DIR}/" 2>/dev/null || true

FINAL_E=\$(grep "TOTAL ENERGY" "${LOG_DIR}/xtb_opt.log" | tail -1 | awk '{print \$4}')
N_CYCLES=\$(grep -c "GEOMETRY OPTIMIZATION CYCLE" "${LOG_DIR}/xtb_opt.log" 2>/dev/null || echo "?")

echo "XTB_PREOPT_OK" > "${XTB_DIR}/xtb_ok.stamp"
echo "\$(date -Iseconds)" >> "${XTB_DIR}/xtb_ok.stamp"
echo "gfn=${GFN_VERSION} opt=${OPT_LEVEL} charge=${CHARGE} cycles=\$N_CYCLES energy=\$FINAL_E job=\$SLURM_JOB_ID" >> "${XTB_DIR}/xtb_ok.stamp"

echo
echo "Pre-optimization complete: \$N_CYCLES cycles, energy=\$FINAL_E"
echo "Optimized XYZ: ${MOL_DIR}/${MOLECULE}.xyz"

# Cleanup scratch
rm -rf "\$WORKDIR"
SLURM_EOF

  chmod +x "$SLURM_SCRIPT"

  echo "=== xtb_preopt (SLURM mode) ==="
  echo "  Molecule:  $MOLECULE"
  echo "  GFN:       $GFN_VERSION"
  echo "  Opt level: $OPT_LEVEL"
  echo "  Charge:    $CHARGE"
  echo "  Partition: $PREP_PARTITION"
  echo "  CPUs:      $OVR_CPUS"
  echo

  JOB_OUTPUT=$(sbatch "$SLURM_SCRIPT")
  JOB_ID=$(echo "$JOB_OUTPUT" | grep -oP '\d+')

  echo "$JOB_OUTPUT"
  echo
  echo "xTB Job ID: $JOB_ID"
  echo "Monitor:    squeue --clusters=$CLUSTER -j $JOB_ID"
  echo
  echo "After job completes:"
  echo "  1. cat $XTB_DIR/xtb_ok.stamp"
  echo "  2. scripts/run_cosmo.sh $MOLECULE BP-TZVPD-OPT"

  exit 0
fi

# ==============================================================================
# Local mode (login node)
# ==============================================================================
source "$TURBOMOLE_ROOT/vars"
export PARA_ARCH=SMP
export TURBOMOLE_SYSNAME
export PATH="$TURBOMOLE_ROOT/bin/$TURBOMOLE_SYSNAME:$TURBOMOLE_ROOT/scripts:$PATH"

run_xtb_opt "$XTB_DIR"
