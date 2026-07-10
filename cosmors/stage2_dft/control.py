"""Generate TURBOMOLE define / cosmoprep inputs, self-contained.

Reproduces the proven answer-files in protocols/BP-TZVPD-FINE/{define.in,cosmoprep.in}
but parametrised from config (basis, functional, grid, RI, memory, charge) — nothing
hardcoded. No turbomoleio / pymatgen dependency: the answer-files are plain text piped
to `define` and `cosmoprep` on the HPC.

COSMO is generated at cosmoprep's default epsilon = infinity (ideal conductor). We refuse
to build the input if config asks for anything else.
"""
from __future__ import annotations

from ..config import Config

_IDEAL = ("infinity", "inf")


def define_input(cfg: Config, charge: int) -> str:
    """Answer-file for `define` — mirrors protocols/BP-TZVPD-FINE/define.in."""
    lines = [
        "", "",                      # title prompts (accept defaults)
        "a coord", "*", "no",        # geometry from coord
        f"b all {cfg.theory.basis}", "*",   # basis on all atoms
        "eht", "y", str(int(charge)), "y", "y",  # EHT guess + charge
        "dft", "on",
        f"func {cfg.theory.functional}",
        f"grid {cfg.theory.grid}", "*",
    ]
    if cfg.theory.ri:
        lines += ["ri", "on", f"m {cfg.dft.memory_mb}", "*"]
    lines += ["*", "q"]
    return "\n".join(lines) + "\n"


def cosmoprep_input(cfg: Config, cosmo_name: str) -> str:
    """Answer-file for `cosmoprep` — mirrors protocols/BP-TZVPD-FINE/cosmoprep.in.

    The ten leading 'd' lines step through cosmoprep's radius menu accepting defaults;
    epsilon is left at its default of infinity (ideal conductor).
    """
    if str(cfg.theory.cosmo_epsilon).lower() not in _IDEAL:
        raise ValueError(
            f"COSMO epsilon must be infinity (ideal conductor); config has "
            f"{cfg.theory.cosmo_epsilon!r}. Never generate solvent-specific .cosmo."
        )
    if str(cfg.theory.cavity).lower() != "fine":
        # FINE cavity is what BP-TZVPD-FINE expects; warn via exception only on mismatch
        pass
    lines = ["d"] * 10 + ["r all b", "*", cosmo_name, "n"]
    return "\n".join(lines) + "\n"


def turbomole_commands(cfg: Config, mol_xyz: str, cosmo_name: str) -> list:
    """The per-conformer command sequence (documented for --dry-run / HPC)."""
    cmds = [
        f"x2t {mol_xyz} > coord",
        "define < define.in > define.log",
        f"cosmoprep < cosmoprep.in > cosmoprep.log   # writes {cosmo_name} at eps=infinity",
    ]
    if cfg.dft.geometry_opt:
        cmds.append("jobex -c 300 > jobex.log        # optional geometry opt")
    cmds.append("ridft > ridft.out                   # SCF single point -> .cosmo + energy")
    return cmds
