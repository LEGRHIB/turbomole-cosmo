#!/bin/bash
# _tune_scf.sh — Apply protocol-specific SCF tuning to control file in cwd.
#
# For BP-TZVPD-* protocols, replaces the default scfiterlimit / scfdamp /
# scforbitalshift lines in `control` with values tuned for difficult
# convergence on large molecules:
#   $scfiterlimit      300
#   $scfdamp   start=0.700  step=0.050  min=0.050
#   $scforbitalshift  automatic=.3
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
  BP-TZVPD-*)
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
    ;;
  *)
    echo "  no SCF tuning for protocol $PROTOCOL"
    ;;
esac
