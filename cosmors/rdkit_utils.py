"""Thin RDKit helpers, lazily imported.

RDKit is imported inside functions so that importing the core package (config,
models, workdir, cli) never hard-requires it. Only stages that actually do
chemistry pull it in; a clear error is raised if it is missing.
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Tuple


class RDKitMissing(RuntimeError):
    pass


def require_rdkit():
    try:
        from rdkit import Chem
        from rdkit.Chem import AllChem
        return Chem, AllChem
    except ImportError as exc:  # pragma: no cover
        raise RDKitMissing(
            "RDKit is required for this stage. Install with `pip install rdkit` "
            "(or `conda install -c conda-forge rdkit`)."
        ) from exc


def embed_from_smiles(smiles: str, seed: int = 0xF00D):
    """SMILES -> 3D mol with explicit H, MMFF (UFF fallback) optimised."""
    Chem, AllChem = require_rdkit()
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ValueError(f"RDKit could not parse SMILES: {smiles!r}")
    mol = Chem.AddHs(mol)
    params = AllChem.ETKDGv3()
    params.randomSeed = seed
    if AllChem.EmbedMolecule(mol, params) != 0:
        raise ValueError(f"RDKit could not embed 3D coords for SMILES: {smiles!r}")
    if AllChem.MMFFOptimizeMolecule(mol) != 0:
        AllChem.UFFOptimizeMolecule(mol)
    return mol


def read_mol(path: str, add_hs: bool = False):
    """Read a single-molecule structure (SDF / PDB / MOL) as an RDKit mol."""
    Chem, AllChem = require_rdkit()
    p = str(path)
    low = p.lower()
    if low.endswith((".sdf", ".mol")):
        supplier = Chem.SDMolSupplier(p, removeHs=False, sanitize=True)
        mols = [m for m in supplier if m is not None]
        if not mols:
            raise ValueError(f"No readable molecule in {p}")
        mol = mols[0]
    elif low.endswith(".pdb"):
        mol = Chem.MolFromPDBFile(p, removeHs=False, sanitize=True)
        if mol is None:
            raise ValueError(f"RDKit could not read PDB {p}")
    elif low.endswith(".xyz"):
        mol = _mol_from_xyz(p)
    else:
        raise ValueError(f"Unsupported input format: {p} (use SDF/PDB/xyz or a SMILES)")
    if add_hs:
        mol = Chem.AddHs(mol, addCoords=True)
    return mol


def _mol_from_xyz(path: str):
    """Best-effort xyz -> mol with perceived bonds (needs rdDetermineBonds)."""
    Chem, _ = require_rdkit()
    raw = Chem.MolFromXYZFile(str(path))
    if raw is None:
        raise ValueError(f"RDKit could not read xyz {path}")
    try:
        from rdkit.Chem import rdDetermineBonds
        mol = Chem.Mol(raw)
        rdDetermineBonds.DetermineBonds(mol)
        return mol
    except Exception as exc:
        raise ValueError(
            f"xyz input {path} needs connectivity perception (rdDetermineBonds "
            f"unavailable): {exc}. Provide an SDF or SMILES instead."
        ) from exc


def read_conformers(path: str) -> List:
    """Read a multi-entry SDF as a list of single-conformer mols (order preserved)."""
    Chem, _ = require_rdkit()
    supplier = Chem.SDMolSupplier(str(path), removeHs=False, sanitize=True)
    mols = [m for m in supplier if m is not None]
    if not mols:
        raise ValueError(f"No readable conformers in {path}")
    return mols


def formal_charge(mol) -> int:
    Chem, _ = require_rdkit()
    return Chem.GetFormalCharge(mol)


def write_xyz(path: str, mol, conf_id: int = 0, comment: str = "") -> None:
    conf = mol.GetConformer(conf_id)
    lines = [str(mol.GetNumAtoms()), comment]
    for i, atom in enumerate(mol.GetAtoms()):
        pos = conf.GetAtomPosition(i)
        lines.append(f"{atom.GetSymbol():<2s} {pos.x:>14.8f} {pos.y:>14.8f} {pos.z:>14.8f}")
    Path(path).write_text("\n".join(lines) + "\n")


def write_sdf(path: str, mols: List, prop: Optional[dict] = None) -> None:
    """Write a list of mols to a multi-entry SDF."""
    Chem, _ = require_rdkit()
    writer = Chem.SDWriter(str(path))
    try:
        for i, mol in enumerate(mols):
            if prop:
                for k, v in prop.get(i, {}).items():
                    mol.SetProp(str(k), str(v))
            writer.write(mol)
    finally:
        writer.close()


def best_rms(probe, ref) -> float:
    """Symmetry-aware best RMSD between two conformers of the same molecule."""
    Chem, _ = require_rdkit()
    from rdkit.Chem import rdMolAlign
    return rdMolAlign.GetBestRMS(Chem.Mol(probe), Chem.Mol(ref))
