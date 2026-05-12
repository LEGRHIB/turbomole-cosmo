# turbomole-cosmo / config.sh
# -----------------------------------------------------------------------------
# Edit this once for your environment. All scripts source it.
# -----------------------------------------------------------------------------

# --- TURBOMOLE installation ---------------------------------------------------
export TURBOMOLE_ROOT="/data/leuven/301/vsc30101/turbomole7.8"
export TURBOMOLE_SYSNAME="em64t-unknown-linux-gnu"

# --- VSC / SLURM defaults -----------------------------------------------------
export CLUSTER="wice"
export PARTITION="batch"
export ACCOUNT="lp_cheme_cfd"
export USER_BASE="/vsc-hard-mounts/leuven-user/385/vsc38535/my_turbomole"

# --- Default protocol ---------------------------------------------------------
export DEFAULT_PROTOCOL="BP-TZVPD-FINE"

# --- Per-protocol SLURM resource defaults ------------------------------------
# def2-SVP: cheap, serial dscf
export SLURM_SVP_CPUS=4
export SLURM_SVP_MEM="20000M"
export SLURM_SVP_TIME="06:00:00"

# BP-TZVPD-FINE: BP86 + RI + TZVPD + m4 + fine cavity; needs fat node
export SLURM_FINE_CPUS=16
export SLURM_FINE_MEM="120000M"
export SLURM_FINE_TIME="72:00:00"

# BP-TZVPD-OPT: geometry optimization with BP86 + RI + TZVPD + COSMO
# These are defaults for medium molecules (~200 atoms)
# Override per-molecule with: submit_cosmo.sh mol protocol --partition bigmem --cpus 72 --mem 2000000M
export SLURM_OPT_CPUS=16
export SLURM_OPT_MEM="120000M"
export SLURM_OPT_TIME="168:00:00"   # 7d — jobex on large peptides routinely needs this

# Bigmem defaults: used by --bigmem shortcut in full_pipeline.sh / prep_cosmo.sh
# For large proteins (>500 atoms) that need bigmem partition for both prep and SCF
export SLURM_BIGMEM_CPUS=72
export SLURM_BIGMEM_MEM="2000000M"
export SLURM_BIGMEM_TIME="72:00:00"

# --- Repo self-location -------------------------------------------------------
if [[ -z "${REPO_ROOT:-}" ]]; then
  export REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi
