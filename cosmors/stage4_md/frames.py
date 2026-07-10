"""Frame handling: extract -> RMSD cluster -> multi-conformer SDF.

MD only PROPOSES geometries. This module turns a trajectory (or, in the sandbox,
synthetic frames) into a small set of RMSD-distinct cluster representatives that
Stage 1 ingests; DFT then re-optimises them and COSMOtherm assigns the weights.
"""
from __future__ import annotations

import random
from typing import List, Tuple

from .. import rdkit_utils as ru
from ..cluster import rmsd_cluster


def synthetic_frames(seed_mol, n: int, scale: float = 0.5, seed: int = 0) -> List:
    """Sandbox stand-in for MD: n Gaussian-perturbed copies of the seed geometry.

    Clearly synthetic — used only when no MD engine is available, so the
    frames -> cluster -> SDF machinery can be exercised end-to-end.
    """
    from rdkit import Chem
    from rdkit.Geometry import Point3D

    rng = random.Random(seed)
    frames = []
    for _ in range(n):
        m = Chem.Mol(seed_mol)
        conf = m.GetConformer()
        for i in range(m.GetNumAtoms()):
            p = conf.GetAtomPosition(i)
            conf.SetAtomPosition(i, Point3D(p.x + rng.gauss(0, scale),
                                            p.y + rng.gauss(0, scale),
                                            p.z + rng.gauss(0, scale)))
        frames.append(m)
    return frames


def cluster_frames(frames: List, rmsd_cutoff: float, max_reps=None) -> Tuple[List, dict]:
    kept_idx, report = rmsd_cluster(frames, cutoff=rmsd_cutoff, max_conformers=max_reps)
    return [frames[i] for i in kept_idx], report


def write_reps(reps: List, path: str) -> None:
    ru.write_sdf(str(path), reps)
