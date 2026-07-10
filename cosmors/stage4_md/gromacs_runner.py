"""GROMACS high-temperature MD adapter (HPC). Commands documented, not run here."""
from __future__ import annotations

from typing import List


def commands(cfg, seed_pdb: str = "seed.pdb") -> List[str]:
    return [
        f"gmx pdb2gmx -f {seed_pdb} -o conf.gro -p topol.top -water none -ff amber99sb-ildn",
        "gmx editconf -f conf.gro -o box.gro -c -d 1.0 -bt cubic",
        f"gmx grompp -f md_hot.mdp -c box.gro -p topol.top -o md.tpr   # ref_t={cfg.md.temperature_K} K",
        "gmx mdrun -deffnm md",
        f"gmx trjconv -s md.tpr -f md.xtc -o frame_.pdb -sep           # -> {cfg.md.n_frames} frames",
    ]
