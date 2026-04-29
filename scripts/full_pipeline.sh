#!/bin/bash
# full_pipeline.sh — End-to-end: PDB → clean → protonate → XYZ → TURBOMOLE → submit
#
# Universal workflow: specify any PDB, any pH, and optionally which chains.
# Handles protonation, charge determination, and TURBOMOLE setup automatically.
#
# Usage:
#   scripts/full_pipeline.sh <input.pdb> <molecule> <pH> [options]
#
# Options:
#   --chains A,C          Keep only these chains (default: all)
#   --protocol NAME       TURBOMOLE protocol (default: BP-TZVPD-OPT)
#   --prep-only           Stop after prepare_molecule.py (don't run TURBOMOLE prep)
#   --no-submit           Run prep_cosmo.sh but don't submit to SLURM
#   --slurm               Submit prep as a SLURM job (for large molecules)
#   --xtb-preopt          Run GFN2-xTB pre-optimization before DFT (recommended for SDF input)
#   --bigmem              Shortcut: --slurm --partition bigmem --cpus 72 --mem 2000000M
#   --partition NAME      Override SLURM partition
#   --cpus N              Override CPU count
#   --mem SIZE            Override memory (e.g. 2000000M)
#   --time HH:MM:SS       Override wall time
#
# Examples:
#   # Vancomycin at pH 2.6, chains A+C, full geometry optimization
#   scripts/full_pipeline.sh molecules/vancomycin/1SHO.pdb vancomycin 2.6 --chains A,C
#
#   # Bradykinin at pH 7.4, all chains, single-point only
#   scripts/full_pipeline.sh molecules/bradykinin/bradykinin.pdb bradykinin 7.4 --protocol BP-TZVPD-FINE
#
#   # Large protein on bigmem (prep on compute node, verify, then submit SCF manually)
#   scripts/full_pipeline.sh molecules/lysozyme/2LYZ.pdb lysozyme 4.5 --bigmem
#
#   # 2D SDF with xTB pre-optimization (recommended)
#   scripts/full_pipeline.sh molecules/vancomycin_2d/vancomycin_2d.sdf vancomycin_2d --xtb-preopt
#
#   # Just prepare XYZ locally (no HPC needed)
#   scripts/full_pipeline.sh input.pdb mymolecule 7.4 --prep-only
# -----------------------------------------------------------------------------

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
source "$REPO_ROOT/config.sh"

# --- Parse arguments ----------------------------------------------------------
INPUT_PDB=""
MOLECULE=""
PH=""
CHAINS=""
PROTOCOL="$DEFAULT_PROTOCOL"
PREP_ONLY=false
NO_SUBMIT=false
USE_SLURM=false
XTB_PREOPT=false
OVR_PARTITION=""
OVR_CPUS=""
OVR_MEM=""
OVR_TIME=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --chains)    CHAINS="$2"; shift 2 ;;
    --protocol)  PROTOCOL="$2"; shift 2 ;;
    --prep-only)    PREP_ONLY=true; shift ;;
    --no-submit)    NO_SUBMIT=true; shift ;;
    --xtb-preopt)   XTB_PREOPT=true; shift ;;
    --slurm)        USE_SLURM=true; shift ;;
    --bigmem)
      USE_SLURM=true
      OVR_PARTITION="${OVR_PARTITION:-bigmem}"
      OVR_CPUS="${OVR_CPUS:-${SLURM_BIGMEM_CPUS:-72}}"
      OVR_MEM="${OVR_MEM:-${SLURM_BIGMEM_MEM:-2000000M}}"
      shift
      ;;
    --partition)  OVR_PARTITION="$2"; shift 2 ;;
    --cpus)       OVR_CPUS="$2"; shift 2 ;;
    --mem)        OVR_MEM="$2"; shift 2 ;;
    --time)       OVR_TIME="$2"; shift 2 ;;
    --help|-h)
      head -n 35 "$0" | grep '^#' | sed 's/^# \?//'
      exit 0
      ;;
    *)
      if [[ -z "$INPUT_PDB" ]]; then
        INPUT_PDB="$1"
      elif [[ -z "$MOLECULE" ]]; then
        MOLECULE="$1"
      elif [[ -z "$PH" ]]; then
        PH="$1"
      else
        echo "ERROR: unexpected argument: $1" >&2
        exit 2
      fi
      shift
      ;;
  esac
done

if [[ -z "$INPUT_PDB" || -z "$MOLECULE" ]]; then
  echo "Usage: $0 <input> <molecule> [pH] [--chains A,C] [--protocol NAME] [--bigmem]" >&2
  echo "       pH is required for PDB input, optional for SDF input." >&2
  echo "       $0 --help for full usage" >&2
  exit 2
fi

# --bigmem or --slurm implies --no-submit (manual verification between prep and SCF)
if $USE_SLURM; then
  NO_SUBMIT=true
fi

echo "================================================================"
echo "  TURBOMOLE COSMO Full Pipeline"
echo "================================================================"
echo "  Input:      $INPUT_PDB"
echo "  Molecule:   $MOLECULE"
echo "  pH:         ${PH:-not set (SDF mode)}"
echo "  Chains:     ${CHAINS:-all}"
echo "  Protocol:   $PROTOCOL"
echo "  xTB preopt: $XTB_PREOPT"
echo "  Prep only:  $PREP_ONLY"
echo "  SLURM prep: $USE_SLURM"
echo "  No submit:  $NO_SUBMIT"
if [[ -n "$OVR_PARTITION" || -n "$OVR_CPUS" || -n "$OVR_MEM" || -n "$OVR_TIME" ]]; then
echo "  Partition:  ${OVR_PARTITION:-default}"
echo "  CPUs:       ${OVR_CPUS:-default}"
echo "  Memory:     ${OVR_MEM:-default}"
echo "  Wall time:  ${OVR_TIME:-default}"
fi
echo "================================================================"
echo

# --- Step 1: Prepare molecule (PDB → clean → protonate → XYZ + charge) -------
echo ">>> STEP 1: Preparing molecule"
echo "---"

PREP_ARGS=("$INPUT_PDB" "$MOLECULE")
[[ -n "$PH" ]] && PREP_ARGS+=("$PH")
if [[ -n "$CHAINS" ]]; then
  PREP_ARGS+=(--chains "$CHAINS")
fi

python3 "$SCRIPT_DIR/prepare_molecule.py" "${PREP_ARGS[@]}"

MOL_DIR="$REPO_ROOT/molecules/$MOLECULE"

# Verify outputs
if [[ ! -f "$MOL_DIR/$MOLECULE.xyz" ]]; then
  echo "ERROR: prepare_molecule.py did not produce $MOL_DIR/$MOLECULE.xyz" >&2
  exit 3
fi
if [[ ! -f "$MOL_DIR/charge.txt" ]]; then
  echo "ERROR: prepare_molecule.py did not produce $MOL_DIR/charge.txt" >&2
  exit 3
fi

CHARGE=$(cat "$MOL_DIR/charge.txt" | tr -d '[:space:]')
N_ATOMS=$(head -n1 "$MOL_DIR/$MOLECULE.xyz")

echo
echo "  XYZ ready:  $MOL_DIR/$MOLECULE.xyz ($N_ATOMS atoms, charge=$CHARGE)"
echo

if $PREP_ONLY; then
  echo ">>> --prep-only specified. Stopping here."
  echo "    XYZ:    $MOL_DIR/$MOLECULE.xyz"
  echo "    Charge: $MOL_DIR/charge.txt (charge=$CHARGE)"
  echo
  echo "    To continue on the HPC login node:"
  echo "    scripts/prep_cosmo.sh $MOLECULE $PROTOCOL"
  echo "    scripts/submit_cosmo.sh $MOLECULE $PROTOCOL"
  exit 0
fi

# --- Step 1b (optional): GFN-xTB pre-optimization ----------------------------
if $XTB_PREOPT; then
  echo ">>> STEP 1b: GFN2-xTB pre-optimization"
  echo "---"

  XTB_ARGS=("$MOLECULE")
  if $USE_SLURM; then
    XTB_ARGS+=(--slurm)
    [[ -n "$OVR_PARTITION" ]] && XTB_ARGS+=(--partition "$OVR_PARTITION")
    [[ -n "$OVR_CPUS" ]]      && XTB_ARGS+=(--cpus "$OVR_CPUS")
    [[ -n "$OVR_MEM" ]]       && XTB_ARGS+=(--mem "$OVR_MEM")
  fi

  "$SCRIPT_DIR/xtb_preopt.sh" "${XTB_ARGS[@]}"

  if $USE_SLURM; then
    echo
    echo ">>> xTB pre-optimization submitted as SLURM job. Pipeline paused."
    echo "    After xTB job finishes, re-run without --xtb-preopt to continue DFT:"
    echo "    scripts/full_pipeline.sh $INPUT_PDB $MOLECULE ${PH:-} --protocol $PROTOCOL"
    exit 0
  fi

  echo
  echo "  xTB pre-optimization done. Updated XYZ: $MOL_DIR/$MOLECULE.xyz"
  echo
fi

# --- Step 2: TURBOMOLE prep (x2t + define + cosmoprep) ------------------------
echo ">>> STEP 2: TURBOMOLE prep (x2t + define + cosmoprep)"
echo "---"

# Build prep_cosmo.sh arguments
PREP_CMD_ARGS=("$MOLECULE" "$PROTOCOL")
if $USE_SLURM; then
  PREP_CMD_ARGS+=(--slurm)
fi
[[ -n "$OVR_PARTITION" ]] && PREP_CMD_ARGS+=(--partition "$OVR_PARTITION")
[[ -n "$OVR_CPUS" ]]      && PREP_CMD_ARGS+=(--cpus "$OVR_CPUS")
[[ -n "$OVR_MEM" ]]       && PREP_CMD_ARGS+=(--mem "$OVR_MEM")
[[ -n "$OVR_TIME" ]]      && PREP_CMD_ARGS+=(--time "$OVR_TIME")

"$SCRIPT_DIR/prep_cosmo.sh" "${PREP_CMD_ARGS[@]}"

echo

if $USE_SLURM; then
  echo ">>> Prep submitted as SLURM job. Pipeline paused here."
  echo
  echo "    After the prep job finishes, verify and submit SCF manually:"
  WORK_DIR="$MOL_DIR/$PROTOCOL"
  echo "    1. cat $WORK_DIR/prep_ok.stamp"
  echo "    2. scripts/verify_cosmo.sh $MOLECULE $PROTOCOL   (optional quick check)"

  # Build the submit command with the same resource overrides
  SUBMIT_CMD="scripts/submit_cosmo.sh $MOLECULE $PROTOCOL"
  [[ -n "$OVR_PARTITION" ]] && SUBMIT_CMD+=" --partition $OVR_PARTITION"
  [[ -n "$OVR_CPUS" ]]      && SUBMIT_CMD+=" --cpus $OVR_CPUS"
  [[ -n "$OVR_MEM" ]]       && SUBMIT_CMD+=" --mem $OVR_MEM"
  [[ -n "$OVR_TIME" ]]      && SUBMIT_CMD+=" --time $OVR_TIME"
  echo "    3. $SUBMIT_CMD"
  exit 0
fi

if $NO_SUBMIT; then
  echo ">>> --no-submit specified. Stopping here."
  echo "    Prepared in: $MOL_DIR/$PROTOCOL"
  echo
  echo "    To submit manually:"

  SUBMIT_CMD="scripts/submit_cosmo.sh $MOLECULE $PROTOCOL"
  [[ -n "$OVR_PARTITION" ]] && SUBMIT_CMD+=" --partition $OVR_PARTITION"
  [[ -n "$OVR_CPUS" ]]      && SUBMIT_CMD+=" --cpus $OVR_CPUS"
  [[ -n "$OVR_MEM" ]]       && SUBMIT_CMD+=" --mem $OVR_MEM"
  [[ -n "$OVR_TIME" ]]      && SUBMIT_CMD+=" --time $OVR_TIME"
  echo "    $SUBMIT_CMD"
  exit 0
fi

# --- Step 3: Submit SLURM job -------------------------------------------------
echo ">>> STEP 3: Submitting SLURM job"
echo "---"

# Build submit_cosmo.sh arguments
SUBMIT_ARGS=("$MOLECULE" "$PROTOCOL")
[[ -n "$OVR_PARTITION" ]] && SUBMIT_ARGS+=(--partition "$OVR_PARTITION")
[[ -n "$OVR_CPUS" ]]      && SUBMIT_ARGS+=(--cpus "$OVR_CPUS")
[[ -n "$OVR_MEM" ]]       && SUBMIT_ARGS+=(--mem "$OVR_MEM")
[[ -n "$OVR_TIME" ]]      && SUBMIT_ARGS+=(--time "$OVR_TIME")

"$SCRIPT_DIR/submit_cosmo.sh" "${SUBMIT_ARGS[@]}"

echo
echo "================================================================"
echo "  Pipeline complete for $MOLECULE"
echo "  After job finishes: scripts/verify_cosmo.sh $MOLECULE $PROTOCOL"
echo "================================================================"
