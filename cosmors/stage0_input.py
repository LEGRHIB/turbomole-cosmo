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

    if kind == "file" and value.lower().endswith(".cif"):
        return _run_alphafold(cfg, stage_dir, value)

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


def _run_alphafold(cfg: Config, stage_dir: Path, cif: str) -> StageResult:
    """Stage 0 for an AlphaFold mmCIF: pLDDT gate + (optional) template transplant."""
    from . import af_intake
    d = Path(stage_dir)
    try:
        r = af_intake.intake(cif, cfg.compound.template, cfg.compound.charge,
                             cfg.compound.plddt_gate)
    except Exception as exc:
        return StageResult("input", "error", str(d), message=f"AlphaFold intake: {exc}")

    (d / "plddt.json").write_text(json.dumps(r["plddt"], indent=2) + "\n")
    charge = r["charge"]
    if r["mode"] == "template":
        mol = r["mol"]
        from rdkit.Chem import rdMolDescriptors
        formula, natoms = rdMolDescriptors.CalcMolFormula(mol), mol.GetNumAtoms()
        ru.write_xyz(str(d / "geometry.xyz"), mol,
                     comment=f"{cfg.compound.name} from AlphaFold (template)")
        ru.write_sdf(str(d / "input.sdf"), [mol])
        arts = ["geometry.xyz", "charge.txt", "input.sdf", "plddt.json", "input_meta.json"]
    else:
        (d / "geometry.xyz").write_text(r["xyz"])
        formula, natoms = f"{r['n_atoms']} heavy atoms", r["n_atoms"]
        arts = ["geometry.xyz", "charge.txt", "plddt.json", "input_meta.json"]

    (d / "charge.txt").write_text(f"{charge}\n")
    meta = {"compound": cfg.compound.name, "source_kind": "alphafold_cif", "source": cif,
            "mode": r["mode"], "charge": charge,
            "plddt_mean": round(r["plddt"]["mean"], 1),
            "weak_residues": r["plddt"]["weak_residues"],
            "formula": formula, "n_atoms": natoms}
    (d / "input_meta.json").write_text(json.dumps(meta, indent=2) + "\n")

    weak = r["plddt"]["weak_residues"]
    return StageResult(
        "input", "done", str(d), artifacts=arts,
        message=f"AF {r['mode']}: pLDDT mean {r['plddt']['mean']:.1f}, "
                f"{len(weak)} weak residue(s), charge={charge} -> seeds MD",
    )
