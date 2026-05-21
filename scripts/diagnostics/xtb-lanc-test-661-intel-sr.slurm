#!/bin/bash -l
# xtb-lanc-test-661-intel-sr.slurm
# -----------------------------------------------------------------------------
# Diagnostic: does xtb 6.6.1-intel-2021a (Intel toolchain, iomp5 runtime)
# survive the L-ANC optimizer crash on lysozyme (1963 atoms, +11) on
# Sapphire Rapids, where xtb 6.7.1-gfbf-2024a (GCC + libgomp) segfaults?
#
# One of three sibling tests that vary exactly one factor each:
#   - this file: 6.6.1 + intel-2021a + SR partition
#   - xtb-lanc-test-671-gfbf-sr.slurm: 6.7.1 + gfbf-2024a + SR partition (+ OMP_STACKSIZE fix)
#   - xtb-lanc-test-671-gfbf-il.slurm: 6.7.1 + gfbf-2024a + IceLake partition
#
# Inputs:  $VSC_DATA/turbomole-cosmo/molecules/lysozyme/lysozyme.xyz
# Outputs: $VSC_SCRATCH/xtb-lanc-tests/661-intel-sr-<jobid>/
# Logs:    $VSC_SCRATCH/xtb-lanc-tests/661-intel-sr-<jobid>.{out,err}
# -----------------------------------------------------------------------------
#SBATCH --clusters=wice
#SBATCH --partition=batch_sapphirerapids
#SBATCH --account=lp_cheme_cfd
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --time=01:00:00
#SBATCH --mem=64G
#SBATCH --job-name=xtb-lanc-661-intel-sr
#SBATCH --output=/vsc-hard-mounts/leuven-user/385/vsc38535/xtb-lanc-tests/661-intel-sr-%j.out
#SBATCH --error=/vsc-hard-mounts/leuven-user/385/vsc38535/xtb-lanc-tests/661-intel-sr-%j.err

set -uo pipefail   # NOT -e: we need the post-mortem to run after xtb crashes

mkdir -p $VSC_SCRATCH/xtb-lanc-tests

# --- TURBOMOLE for x2t, then xtb module on top -------------------------------
source /data/leuven/301/vsc30101/turbomole7.8/vars
export PARA_ARCH=SMP
export TURBOMOLE_SYSNAME=em64t-unknown-linux-gnu
export PATH=/data/leuven/301/vsc30101/turbomole7.8/bin/$TURBOMOLE_SYSNAME:/data/leuven/301/vsc30101/turbomole7.8/scripts:$PATH

module load xtb/6.6.1-intel-2021a

# --- L-ANC workaround knobs --------------------------------------------------
ulimit -s unlimited
export OMP_STACKSIZE=4000m
export OMP_NUM_THREADS=4
export MKL_NUM_THREADS=4

# --- Diagnostic block --------------------------------------------------------
echo "=== Node + build info ==="
echo "Hostname: $(hostname)"
echo "Arch:     $(uname -m) / $(cat /sys/devices/cpu/caps/pmu_name 2>/dev/null || echo unknown)"
echo "xtb path: $(which xtb)"
xtb --version 2>&1 | head -5
ldd $(which xtb) | grep -E 'omp|gfortran|libgcc|libimf' | head
echo "OMP runtime symbols:"
ldd $(which xtb) | grep -E 'libgomp|libiomp|libomp' || echo "  (none matched)"
echo "Stack limit: $(ulimit -s)"
echo "OMP_NUM_THREADS=$OMP_NUM_THREADS OMP_STACKSIZE=$OMP_STACKSIZE"
echo

# --- Set up workdir ----------------------------------------------------------
WORKDIR=$VSC_SCRATCH/xtb-lanc-tests/661-intel-sr-$SLURM_JOB_ID
rm -rf "$WORKDIR" && mkdir -p "$WORKDIR" && cd "$WORKDIR"

echo "=== Converting xyz -> coord ==="
x2t /data/leuven/385/vsc38535/turbomole-cosmo/molecules/lysozyme/lysozyme.xyz > coord
echo "coord lines: $(wc -l < coord)"
echo

# --- The actual experiment: GFN-FF opt that previously crashed in L-ANC -----
echo "=== xtb --opt loose --gfnff --gbsa h2o --chrg 11 ==="
date
xtb coord --opt loose --gfnff --gbsa h2o --chrg 11
XTB_RC=$?
date
echo

# --- Post-mortem -------------------------------------------------------------
echo "=== Post-mortem ==="
echo "xtb exit code: $XTB_RC"
if [[ -f xtbopt.coord ]]; then
  echo "RESULT: L-ANC SURVIVED  (xtbopt.coord written, $(wc -l < xtbopt.coord) lines)"
  ls -la xtbopt.coord
else
  echo "RESULT: L-ANC STILL CRASHES  (no xtbopt.coord produced)"
  echo "--- Last 30 lines of xtb output (if any captured by SLURM) ---"
fi
