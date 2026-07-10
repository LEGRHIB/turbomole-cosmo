"""OpenMM high-temperature MD (lazy, optional).

Sandbox-testable in principle, but OpenMM is a heavy optional dependency; it is
imported only when actually running MD. Standard-residue peptides parametrise from
amber14 directly; non-standard chemistry (e.g. bombesin's pyroglutamate) needs a
small-molecule force field (GAFF/OpenFF) — flagged rather than guessed.
"""
from __future__ import annotations

from pathlib import Path
from typing import List


def available() -> bool:
    try:
        import openmm  # noqa: F401
        return True
    except ImportError:
        return False


def run_md(seed_pdb: str, cfg, out_dir: str) -> List:
    """High-T Langevin MD (implicit solvent) from a PDB; return frames as RDKit mols.

    Best-effort amber14 setup for standard peptides — validate for your system.
    """
    if not available():
        raise RuntimeError("OpenMM not installed (`pip install openmm`); MD runs on the HPC.")
    from openmm import LangevinMiddleIntegrator, unit
    from openmm.app import PDBFile, ForceField, Modeller, Simulation, PDBReporter, NoCutoff, HBonds, GBn2

    pdb = PDBFile(seed_pdb)
    ff = ForceField("amber14-all.xml", "implicit/gbn2.xml")
    modeller = Modeller(pdb.topology, pdb.positions)
    modeller.addHydrogens(ff)
    system = ff.createSystem(modeller.topology, nonbondedMethod=NoCutoff,
                             constraints=HBonds, implicitSolvent=GBn2)
    integrator = LangevinMiddleIntegrator(cfg.md.temperature_K * unit.kelvin,
                                          1.0 / unit.picosecond, 2.0 * unit.femtoseconds)
    sim = Simulation(modeller.topology, system, integrator)
    sim.context.setPositions(modeller.positions)
    sim.minimizeEnergy()

    traj = str(Path(out_dir) / "traj.pdb")
    interval = 500
    sim.reporters.append(PDBReporter(traj, interval))
    sim.step(cfg.md.n_frames * interval)
    return _frames_from_multimodel_pdb(traj)


def _frames_from_multimodel_pdb(pdb_path: str) -> List:
    """Split a multi-MODEL PDB and read each frame as an RDKit mol."""
    from rdkit import Chem

    text = Path(pdb_path).read_text()
    blocks, cur = [], []
    for line in text.splitlines():
        if line.startswith("ENDMDL"):
            blocks.append("\n".join(cur)); cur = []
        elif not line.startswith("MODEL"):
            cur.append(line)
    if cur and any(l.startswith(("ATOM", "HETATM")) for l in cur):
        blocks.append("\n".join(cur))
    mols = [Chem.MolFromPDBBlock(b, removeHs=False, sanitize=True) for b in blocks]
    return [m for m in mols if m is not None]
