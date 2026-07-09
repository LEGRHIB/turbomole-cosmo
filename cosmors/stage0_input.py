"""Stage 0 — input prep.

SMILES / SDF / PDB / xyz  ->  normalized 3D geometry + total charge.

Produces, in the stage dir:
  geometry.xyz      3D coordinates
  charge.txt        integer total charge
  input.sdf         single-conformer SDF (interchange format for later stages)
  input_meta.json   provenance (source, charge origin, formula, atom count)
"""
from __future__ import annotations

import json
from pathlib import Path

from .config import Config
from .models import StageResult
from . import rdkit_utils as ru


def _resolve_source(cfg: Config):
    """(kind, value) for the input: ('smiles', str) or ('file', path)."""
    if cfg.compound.smiles:
        return "smiles", cfg.compound.smiles
    if cfg.compound.input_path:
        return "file", cfg.compound.input_path
    default = Path("molecules") / cfg.compound.name / f"{cfg.compound.name}.sdf"
    if default.is_file():
        return "file", str(default)
    return None, None


def run(cfg: Config, stage_dir: Path, *, wd, mock: bool, dry_run: bool) -> StageResult:
    stage = "input"
    kind, value = _resolve_source(cfg)

    if dry_run:
        src = f"{kind}={value}" if kind else "NO INPUT (set compound.smiles/input_path)"
        return StageResult(stage, "dry-run", str(stage_dir),
                           message=f"prepare {cfg.compound.name} from {src} "
                                   f"-> geometry.xyz + charge.txt (RDKit)")

    if kind is None:
        return StageResult(stage, "error", str(stage_dir),
                           message=f"no input for {cfg.compound.name}: set compound.smiles "
                                   f"or compound.input_path, or add molecules/"
                                   f"{cfg.compound.name}/{cfg.compound.name}.sdf")

    try:
        if kind == "smiles":
            mol = ru.embed_from_smiles(value)
        else:
            mol = ru.read_mol(value)
    except Exception as exc:
        return StageResult(stage, "error", str(stage_dir), message=str(exc))

    # charge: explicit config wins, else RDKit formal charge
    if cfg.compound.charge is not None:
        charge, charge_src = int(cfg.compound.charge), "config"
    else:
        charge, charge_src = ru.formal_charge(mol), "rdkit_formal_charge"

    from rdkit.Chem import rdMolDescriptors
    formula = rdMolDescriptors.CalcMolFormula(mol)

    ru.write_xyz(str(Path(stage_dir) / "geometry.xyz"), mol,
                 comment=f"{cfg.compound.name} charge={charge}")
    (Path(stage_dir) / "charge.txt").write_text(f"{charge}\n")
    ru.write_sdf(str(Path(stage_dir) / "input.sdf"), [mol])
    meta = {
        "compound": cfg.compound.name,
        "source_kind": kind, "source": value,
        "charge": charge, "charge_source": charge_src,
        "formula": formula, "n_atoms": mol.GetNumAtoms(),
    }
    (Path(stage_dir) / "input_meta.json").write_text(json.dumps(meta, indent=2) + "\n")

    return StageResult(
        stage, "done", str(stage_dir),
        artifacts=["geometry.xyz", "charge.txt", "input.sdf", "input_meta.json"],
        message=f"{formula}  charge={charge} ({charge_src})  {mol.GetNumAtoms()} atoms",
    )
