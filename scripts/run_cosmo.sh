#!/bin/bash
# run_cosmo.sh — End-to-end: prep + submit in one command.
#
# Usage:
#   scripts/run_cosmo.sh <molecule> [protocol] [options]
#
# Options:
#   --slurm              Submit prep as a SLURM job (large molecules)
#   --bigmem             Shortcut: --slurm --partition bigmem --cpus 72 --mem 2000000M
#   --partition NAME     Override SLURM partition
#   --cpus N             Override CPU count
#   --mem SIZE           Override memory
#   --time HH:MM:SS      Override wall time
# -----------------------------------------------------------------------------

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
source "$REPO_ROOT/config.sh"

# Separate positional args from flags
MOLECULE=""
PROTOCOL=""
EXTRA_ARGS=()

for arg in "$@"; do
  if [[ "$arg" == --* ]]; then
    break
  fi
  if [[ -z "$MOLECULE" ]]; then
    MOLECULE="$arg"
    shift
  elif [[ -z "$PROTOCOL" ]]; then
    PROTOCOL="$arg"
    shift
  fi
done
EXTRA_ARGS=("$@")

if [[ -z "$MOLECULE" ]]; then
  echo "Usage: $0 <molecule> [protocol] [--slurm] [--bigmem] [--partition P] [--cpus N] [--mem M] [--time T]" >&2
  exit 2
fi

PROTO_ARG=()
[[ -n "$PROTOCOL" ]] && PROTO_ARG=("$PROTOCOL")

# Check if --slurm or --bigmem is present (implies no auto-submit)
USE_SLURM=false
for a in "${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"}"; do
  [[ "$a" == "--slurm" || "$a" == "--bigmem" ]] && USE_SLURM=true
done

echo "========================================="
echo "  COSMO pipeline: $MOLECULE"
echo "========================================="
echo

"$SCRIPT_DIR/prep_cosmo.sh" "$MOLECULE" "${PROTO_ARG[@]}" "${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"}"
echo

if $USE_SLURM; then
  echo "Prep submitted as SLURM job. Verify prep, then submit SCF manually."
  echo "  scripts/submit_cosmo.sh $MOLECULE ${PROTOCOL:-$DEFAULT_PROTOCOL} ${EXTRA_ARGS[*]+"${EXTRA_ARGS[*]}"}"
else
  "$SCRIPT_DIR/submit_cosmo.sh" "$MOLECULE" "${PROTO_ARG[@]}" "${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"}"
fi
