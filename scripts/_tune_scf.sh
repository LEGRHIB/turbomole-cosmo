#!/bin/bash
# _tune_scf.sh — Apply protocol-specific SCF tuning to control file in cwd.
#
# For BP-TZVPD-* | BP-SVP-FINE | BP-SVP-FINE-ANNEAL | BP-TZVPD-FINE-ANNEAL
# protocols, replaces the default scfiterlimit / scfdamp / scforbitalshift
# lines in `control` with values tuned for difficult convergence on large
# molecules:
#   $scfiterlimit      300
#   $scfdamp   start=0.700  step=0.050  min=0.050
#   $scforbitalshift  automatic=.3
# Plus appends a Fermi smearing data group as a safety net for systems
# with metallic-character HOMO/LUMO gaps (e.g. large peptides/proteins).
# The $fermi block flavor depends on the protocol:
#
#   - default (BP-TZVPD-FINE, BP-TZVPD-OPT, BP-SVP-FINE):
#       $fermi tmstrt=300 tmend=300 tmfac=1.0 hlcrt=1.0e-3 stop=1.0e-3
#     Constant 300 K Fermi smearing. Activates only if HOMO/LUMO gap < 1 mHa.
#
#   - *FINE-ANNEAL (BP-SVP-FINE-ANNEAL, BP-TZVPD-FINE-ANNEAL): annealed
#     schedule for systems where the gap fluctuates around kT(300 K) ≈ 1 mHa
#     — Fermi window keeps switching between "sees the gap" and "sees
#     through it", losing the bracket, COSMO cavity construction
#     fragments, and the SCF diverges (~+200k Eh blowup) — observed on
#     lysozyme +11 at BP-TZVPD-FINE in jobs 66867524 / 66871359 (2026-05-22):
#       $fermi tmstrt=2000 tmend=300 tmfac=0.95 hlcrt=1.0e-3 stop=1.0e-3
#     Start at 2000 K (kT ≈ 6 mHa — wide enough to smooth a 2-30 mHa gap
#     fluctuation), anneal back to 300 K at 5% per SCF cycle.
#
# For other protocols (def2-SVP, etc.), this is a no-op.
#
# Run from the molecule's protocol working directory (where `control` lives).
#
# Usage:
#   _tune_scf.sh <protocol>
# -----------------------------------------------------------------------------

set -euo pipefail

PROTOCOL="${1:?usage: _tune_scf.sh <protocol>}"

if [[ ! -f control ]]; then
  echo "ERROR: no 'control' file in $(pwd) — run define+cosmoprep first" >&2
  exit 1
fi

case "$PROTOCOL" in
  BP-TZVPD-*|BP-TZVP-*|BP-SVP-FINE|BP-SVP-FINE-ANNEAL)
    # Hard-case SCF tuning for ill-conditioned (near-linearly-dependent) systems:
    # any *HARD* protocol uses TURBOMOLE's recommended heavy damping + large level
    # shift (suppresses occ-virt mixing into the near-singular subspace); all other
    # protocols keep the standard tuning.
    if [[ "$PROTOCOL" == *HARD* ]]; then
      sed -i \
        -e 's|^\$scfiterlimit.*|$scfiterlimit      999|' \
        -e 's|^\$scfdamp.*|$scfdamp   start=5.000  step=0.050  min=0.500|' \
        -e 's|^\$scforbitalshift.*|$scforbitalshift  automatic=1.0|' \
        control
      echo "  HARD SCF tuning: scfiterlimit=999, scfdamp 5.000/0.050/0.500, scforbitalshift=1.0"
    else
      sed -i \
        -e 's|^\$scfiterlimit.*|$scfiterlimit      300|' \
        -e 's|^\$scfdamp.*|$scfdamp   start=0.700  step=0.050  min=0.050|' \
        -e 's|^\$scforbitalshift.*|$scforbitalshift  automatic=.3|' \
        control
      echo "  tuned SCF applied: scfiterlimit=300, scfdamp 0.700/0.050/0.050, scforbitalshift=.3"
    fi

    # Verify the three SCF groups are present (value-agnostic)
    if ! grep -q '^\$scfdamp' control \
       || ! grep -q '^\$scfiterlimit' control \
       || ! grep -q '^\$scforbitalshift' control; then
      echo "ERROR: SCF tuning sed-patch did not fully apply to control" >&2
      echo "       Current SCF block:" >&2
      grep -E 'scfiterlimit|scfdamp|scforbitalshift' control >&2 || true
      exit 1
    fi

    # Pick the $fermi flavor based on protocol.
    # Any *FINE-ANNEAL variant (BP-SVP-FINE-ANNEAL, BP-TZVPD-FINE-ANNEAL, ...)
    # uses the annealed 2000K -> 300K schedule. Empirically required for
    # highly-charged proteins where the HOMO/LUMO gap fluctuates around
    # kT(300 K) ≈ 1 mHa: a constant 300 K Fermi window keeps losing the
    # bracket, the system enters a Fermi-recovery loop, COSMO cavities
    # fracture, and the SCF diverges around cycle 6-25 with +200k Eh
    # energy blowups (observed on lysozyme +11 at BP-TZVPD-FINE in
    # jobs 66867524 / 66871359, 2026-05-22).
    if [[ "$PROTOCOL" == *FINE-ANNEAL* ]]; then
      FERMI_LINE='$fermi tmstrt=2000 tmend=300 tmfac=0.95 hlcrt=1.0e-3 stop=1.0e-3'
      FERMI_DESC="annealed Fermi (2000 K -> 300 K, factor 0.95/cycle)"
    else
      FERMI_LINE='$fermi tmstrt=300 tmend=300 tmfac=1.0 hlcrt=1.0e-3 stop=1.0e-3'
      FERMI_DESC="constant 300 K Fermi safety net"
    fi

    # Append Fermi smearing (only activates when HOMO/LUMO gap < 1 mHa).
    # Idempotent: skips if $fermi already present.
    if ! grep -q '^\$fermi' control; then
      sed -i "/^\\\$end/i $FERMI_LINE" control
      if ! grep -q '^\$fermi' control; then
        echo "ERROR: failed to append \$fermi block to control" >&2
        exit 1
      fi
      echo "  $FERMI_DESC added (auto-activates if HOMO/LUMO gap < 1 mHa)"
    else
      echo "  Fermi smearing already present in control — leaving as-is"
    fi
    ;;
  *)
    echo "  no SCF tuning for protocol $PROTOCOL"
    ;;
esac
