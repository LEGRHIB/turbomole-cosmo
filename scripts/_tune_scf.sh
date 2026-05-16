#!/bin/bash
# _tune_scf.sh — Apply protocol-specific SCF tuning to control file in cwd.
#
# For BP-TZVPD-* protocols, replaces the default scfiterlimit / scfdamp /
# scforbitalshift lines in `control` with values tuned for difficult
# convergence on large molecules:
#   $scfiterlimit      300
#   $scfdamp   start=0.700  step=0.050  min=0.050
#   $scforbitalshift  automatic=.3
# Plus appends a Fermi smearing data group as a safety net for systems
# with metallic-character HOMO/LUMO gaps (e.g. large peptides/proteins):
#   $fermi tmstrt=300 tmend=300 tmfac=1.0 hlcrt=1.0e-3 stop=1.0e-3
# Smearing only activates if the gap is < 1 mHa (~27 meV), so it's a
# no-op for normal-gap molecules and a rescue for metallic-character ones.
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
  BP-TZVPD-*|BP-SVP-FINE)
    sed -i \
      -e 's|^\$scfiterlimit.*|$scfiterlimit      300|' \
      -e 's|^\$scfdamp.*|$scfdamp   start=0.700  step=0.050  min=0.050|' \
      -e 's|^\$scforbitalshift.*|$scforbitalshift  automatic=.3|' \
      control

    # Verify the patch landed on all three lines
    if ! grep -q '^\$scfdamp.*start=0\.700' control \
       || ! grep -q '^\$scfiterlimit *300' control \
       || ! grep -q '^\$scforbitalshift *automatic=\.3' control; then
      echo "ERROR: SCF tuning sed-patch did not fully apply to control" >&2
      echo "       Current SCF block:" >&2
      grep -E 'scfiterlimit|scfdamp|scforbitalshift' control >&2 || true
      exit 1
    fi
    echo "  tuned SCF applied: scfiterlimit=300, scfdamp 0.700/0.050/0.050, scforbitalshift=.3"

    # Append Fermi smearing safety net (only activates when HOMO/LUMO gap < 1 mHa).
    # Idempotent: skips if $fermi already present.
    if ! grep -q '^\$fermi' control; then
      sed -i '/^\$end/i $fermi tmstrt=300 tmend=300 tmfac=1.0 hlcrt=1.0e-3 stop=1.0e-3' control
      if ! grep -q '^\$fermi' control; then
        echo "ERROR: failed to append \$fermi block to control" >&2
        exit 1
      fi
      echo "  Fermi smearing added (auto-activates if HOMO/LUMO gap < 1 mHa)"
    else
      echo "  Fermi smearing already present in control — leaving as-is"
    fi
    ;;
  *)
    echo "  no SCF tuning for protocol $PROTOCOL"
    ;;
esac
