#!/bin/bash
# run_cosmo.sh — End-to-end: prep + submit in one command.
#
# Usage:
#   scripts/run_cosmo.sh <molecule> [protocol]
# -----------------------------------------------------------------------------

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

MOLECULE="${1:-}"
PROTOCOL="${2:-}"

if [[ -z "$MOLECULE" ]]; then
  echo "Usage: $0 <molecule> [protocol]" >&2
  exit 2
fi

PROTO_ARG=()
[[ -n "$PROTOCOL" ]] && PROTO_ARG=("$PROTOCOL")

echo "========================================="
echo "  COSMO pipeline: $MOLECULE"
echo "========================================="
echo

"$SCRIPT_DIR/prep_cosmo.sh" "$MOLECULE" "${PROTO_ARG[@]}"
echo
"$SCRIPT_DIR/submit_cosmo.sh" "$MOLECULE" "${PROTO_ARG[@]}"
