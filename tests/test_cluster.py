"""The RMSD clustering gate — proves near-identical geometries are dropped."""
import random

import pytest

rdkit = pytest.importorskip("rdkit")
from rdkit import Chem
from rdkit.Chem import AllChem
from rdkit.Geometry import Point3D

from cosmors.cluster import rmsd_cluster


def _ethanol():
    m = Chem.AddHs(Chem.MolFromSmiles("CCO"))
    p = AllChem.ETKDGv3()
    p.randomSeed = 1
    AllChem.EmbedMolecule(m, p)
    AllChem.MMFFOptimizeMolecule(m)
    return m


def _perturb(mol, scale, seed):
    rng = random.Random(seed)
    m = Chem.Mol(mol)
    conf = m.GetConformer()
    for i in range(m.GetNumAtoms()):
        pos = conf.GetAtomPosition(i)
        conf.SetAtomPosition(i, Point3D(pos.x + rng.gauss(0, scale),
                                        pos.y + rng.gauss(0, scale),
                                        pos.z + rng.gauss(0, scale)))
    return m


def test_gate_collapses_near_identical():
    base = _ethanol()
    near = _perturb(base, 0.005, 1)   # ~0.01 A -> same cluster as base
    far = _perturb(base, 2.0, 2)      # large RMSD -> its own cluster
    kept, report = rmsd_cluster([base, near, far], cutoff=1.0)
    assert report["n_in"] == 3
    assert report["n_kept"] == 2
    assert report["n_dropped"] == 1


def test_cutoff_must_be_positive():
    base = _ethanol()
    with pytest.raises(ValueError):
        rmsd_cluster([base, base], cutoff=0.0)


def test_max_conformers_cap():
    base = _ethanol()
    mols = [_perturb(base, 2.0, s) for s in (1, 2, 3)]  # all far apart
    kept, report = rmsd_cluster(mols, cutoff=1.0, max_conformers=2)
    assert len(kept) == 2
    assert report["n_kept"] == 2


def test_energy_window_drops_high_energy():
    base = _ethanol()
    mols = [_perturb(base, 2.0, 1), _perturb(base, 2.0, 2)]
    kept, report = rmsd_cluster(mols, cutoff=1.0, energies=[0.0, 100.0], energy_window=5.0)
    assert 0 in kept and 1 not in kept
