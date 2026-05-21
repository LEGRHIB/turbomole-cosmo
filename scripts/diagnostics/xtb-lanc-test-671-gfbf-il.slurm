#!/bin/bash -l
# xtb-lanc-test-671-gfbf-il.slurm
# -----------------------------------------------------------------------------
# Diagnostic: same xtb 6.7.1-gfbf-2024a module, same source, but Lmod will
# auto-route to the IceLake-native binary because this job runs on
# batch_icelake. If this passes where the SR sibling crashes, the bug is
# uniquely present in the SR-arch build of the same module — a clean VSC
# ticket: "rebuild xtb/6.7.1-gfbf-2024a for sapphirerapids/."
#
# IceLake DefMemPerCPU=3400 → 4 cpus * 3400 MB = ~13G ceiling. We request
# 12G to stay safely under.
#
# One of three sibling tests; see xtb-lanc-test-661-intel-sr.slurm header.
# -----------------------------------------------------------------------------
#SBATCH --clusters=wice
#SBATCH --partition=batch_icelake
#SBATCH --account=lp_cheme_cfd
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --time=01:00:00
#SBATCH --mem=12G
#SBATCH --job-name=xtb-lanc-671-gfbf-il
#SBATCH --output=/vsc-hard-mounts/leuven-user/385/vsc38535/xtb-lanc-tests/671-gfbf-il-%j.out
#SBATCH --error=/vsc-hard-mounts/leuven-user/385/vsc38535/xtb-lanc-tests/671-gfbf-il-%j.err

set -uo pipefail

mkdir -p $VSC_SCRATCH/xtb-lanc-tests

source /data/leuven/301/vsc30101/turbomole7.8/vars
export PARA_ARCH=SMP
export TURBOMOLE_SYSNAME=em64t-unknown-linux-gnu
export PATH=/data/leuven/301/vsc30101/turbomole7.8/bin/$TURBOMOLE_SYSNAME:/data/leuven/301/vsc30101/turbomole7.8/scripts:$PATH

module load xtb/6.7.1-gfbf-2024a

ulimit -s unlimited
export OMP_STACKSIZE=4000m
export OMP_NUM_THREADS=4
export MKL_NUM_THREADS=4

echo "=== Node + build info ==="
echo "Hostname: $(hostname)"
echo "Arch:     $(uname -m)"
echo "xtb path: $(which xtb)"
echo "(expect IceLake binary path: /apps/leuven/rocky9/icelake/2024a/software/xtb/...)"
xtb --version 2>&1 | head -5
ldd $(which xtb) | grep -E 'omp|gfortran|libgcc' | head
echo "Stack limit: $(ulimit -s)"
echo "OMP_NUM_THREADS=$OMP_NUM_THREADS OMP_STACKSIZE=$OMP_STACKSIZE"
echo

WORKDIR=$VSC_SCRATCH/xtb-lanc-tests/671-gfbf-il-$SLURM_JOB_ID
rm -rf "$WORKDIR" && mkdir -p "$WORKDIR" && cd "$WORKDIR"

echo "=== Converting xyz -> coord ==="
x2t /data/leuven/385/vsc38535/turbomole-cosmo/molecules/lysozyme/lysozyme.xyz > coord
echo "coord lines: $(wc -l < coord)"
echo

echo "=== xtb --opt loose --gfnff --gbsa h2o --chrg 11 ==="
date
xtb coord --opt loose --gfnff --gbsa h2o --chrg 11
XTB_RC=$?
date
echo

echo "=== Post-mortem ==="
echo "xtb exit code: $XTB_RC"
if [[ -f xtbopt.coord ]]; then
  echo "RESULT: L-ANC SURVIVED  (xtbopt.coord written, $(wc -l < xtbopt.coord) lines)"
  ls -la xtbopt.coord
else
  echo "RESULT: L-ANC STILL CRASHES  (no xtbopt.coord produced)"
fi
