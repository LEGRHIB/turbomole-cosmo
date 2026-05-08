#!/bin/bash
# cosmotherm_setup.sh — source COSMOtherm env and validate.
# Idempotent. Designed to be sourced from other scripts:
#   source "$REPO_ROOT/scripts/cosmotherm_setup.sh"
# or run standalone for a smoke-test:
#   ./scripts/cosmotherm_setup.sh

# Allow override via env var, default to the install at our path.
COSMOTHERM_ENV="${COSMOTHERM_ENV:-/data/leuven/385/vsc38535/cosmotherm/cosmotherm-env.sh}"

if [[ ! -f "$COSMOTHERM_ENV" ]]; then
    echo "cosmotherm_setup.sh: ERROR cosmotherm-env.sh not found at $COSMOTHERM_ENV" >&2
    return 1 2>/dev/null || exit 1
fi

# shellcheck source=/dev/null
source "$COSMOTHERM_ENV" || {
    echo "cosmotherm_setup.sh: ERROR failed to source $COSMOTHERM_ENV" >&2
    return 1 2>/dev/null || exit 1
}

# Confirm binary on PATH
if ! command -v cosmotherm >/dev/null 2>&1; then
    echo "cosmotherm_setup.sh: ERROR cosmotherm not on PATH after sourcing env" >&2
    return 1 2>/dev/null || exit 1
fi

# Confirm parameterization is reachable
if [[ ! -f "$CT_PARAM_PATH/BP_TZVPD_FINE_25.ctd" ]]; then
    echo "cosmotherm_setup.sh: ERROR BP_TZVPD_FINE_25.ctd not found in $CT_PARAM_PATH" >&2
    return 1 2>/dev/null || exit 1
fi

# Confirm reference solvent database
if [[ ! -d "$CT_COSMO_DB_PATH/BP-TZVPD-FINE" ]]; then
    echo "cosmotherm_setup.sh: ERROR BP-TZVPD-FINE database not found in $CT_COSMO_DB_PATH" >&2
    return 1 2>/dev/null || exit 1
fi

# Quiet by default; verbose when run standalone (BASH_SOURCE[0] == $0).
if [[ "${BASH_SOURCE[0]:-}" == "${0:-}" ]]; then
    VERSION=$(cosmotherm --version 2>&1 | head -1 | tr -s ' ')
    echo "$VERSION"
    echo "  COSMOTHERM_ROOT : $COSMOTHERM_ROOT"
    echo "  CTD             : $CT_PARAM_PATH/BP_TZVPD_FINE_25.ctd"
    echo "  Solvent DB      : $CT_COSMO_DB_PATH/BP-TZVPD-FINE"
    echo "  License         : $CT_LICENSE_DIR/license.txt"
fi
