#!/bin/bash
# submit_cosmo.sh — Render SLURM template and submit the SCF job.
#
# Usage:
#   scripts/submit_cosmo.sh <molecule> [protocol]
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
PROTO_DIR="$REPO_ROOT/protocols/$PROTOCOL"
SLURM_TMPL="$PROTO_DIR/slurm.tmpl"

if [[ ! -f "$MOL_DIR/control" ]]; then
  echo "ERROR: $MOL_DIR/control not found." >&2
  echo "       Run prep_cosmo.sh first: scripts/prep_cosmo.sh $MOLECULE $PROTOCOL" >&2
  exit 2
fi
if [[ ! -f "$SLURM_TMPL" ]]; then
  echo "ERROR: SLURM template not found: $SLURM_TMPL" >&2
  exit 2
fi

case "$PROTOCOL" in
  def2-SVP)
    CPUS="${SLURM_SVP_CPUS:-4}"
    MEM="${SLURM_SVP_MEM:-20000M}"
    TIME="${SLURM_SVP_TIME:-06:00:00}"
    ;;
  BP-TZVPD-FINE)
    CPUS="${SLURM_FINE_CPUS:-16}"
    MEM="${SLURM_FINE_MEM:-120000M}"
    TIME="${SLURM_FINE_TIME:-72:00:00}"
    ;;
  *)
    CPUS="${SLURM_FINE_CPUS:-16}"
    MEM="${SLURM_FINE_MEM:-120000M}"
    TIME="${SLURM_FINE_TIME:-72:00:00}"
    ;;
esac

SLURM_SCRIPT="$MOL_DIR/run_${MOLECULE}.slurm"

sed \
  -e "s|__MOLECULE__|${MOLECULE}|g" \
  -e "s|__CLUSTER__|${CLUSTER}|g" \
  -e "s|__PARTITION__|${PARTITION}|g" \
  -e "s|__ACCOUNT__|${ACCOUNT}|g" \
  -e "s|__CPUS__|${CPUS}|g" \
  -e "s|__TIME__|${TIME}|g" \
  -e "s|__MEM__|${MEM}|g" \
  -e "s|__INDIR__|${MOL_DIR}|g" \
  -e "s|__TURBOMOLE_ROOT__|${TURBOMOLE_ROOT}|g" \
  -e "s|__SYSNAME__|${TURBOMOLE_SYSNAME}|g" \
  "$SLURM_TMPL" > "$SLURM_SCRIPT"

echo "=== submit_cosmo ==="
echo "  Molecule: $MOLECULE"
echo "  Protocol: $PROTOCOL"
echo "  SLURM   : $SLURM_SCRIPT"
echo "  Cluster : $CLUSTER / $PARTITION / $ACCOUNT"
echo "  Resources: ${CPUS} CPUs, ${MEM} mem, ${TIME} wall"
echo

JOB_OUTPUT=$(sbatch "$SLURM_SCRIPT")
JOB_ID=$(echo "$JOB_OUTPUT" | grep -oP '\d+')

echo "$JOB_OUTPUT"
echo
echo "Job ID: $JOB_ID"
echo "Monitor: squeue --clusters=$CLUSTER -j $JOB_ID"
echo "After completion: scripts/verify_cosmo.sh $MOLECULE"
