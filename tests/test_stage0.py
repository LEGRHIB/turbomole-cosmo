"""Stage 0 — input prep from SMILES (RDKit)."""
import pytest

pytest.importorskip("rdkit")

from cosmors.config import load_config
from cosmors.workdir import WorkDir
from cosmors import stage0_input


def _run(tmp_path, smiles, name="ethanol", charge=None):
    cfg = load_config(None)
    cfg.compound.name = name
    cfg.compound.smiles = smiles
    cfg.compound.charge = charge
    wd = WorkDir(str(tmp_path), name)
    res = stage0_input.run(cfg, wd.stage_dir("input"), wd=wd, mock=False, dry_run=False)
    return res, wd


def test_smiles_neutral(tmp_path):
    res, wd = _run(tmp_path, "CCO")
    assert res.status == "done"
    d = wd.stage_dir("input")
    assert (d / "geometry.xyz").exists()
    assert (d / "input.sdf").exists()
    assert (d / "input_meta.json").exists()
    assert (d / "charge.txt").read_text().strip() == "0"


def test_smiles_cation_charge(tmp_path):
    res, wd = _run(tmp_path, "C[NH3+]")
    assert (wd.stage_dir("input") / "charge.txt").read_text().strip() == "1"


def test_explicit_charge_overrides(tmp_path):
    res, wd = _run(tmp_path, "CCO", charge=2)
    assert (wd.stage_dir("input") / "charge.txt").read_text().strip() == "2"


def test_dry_run_writes_nothing(tmp_path):
    cfg = load_config(None)
    cfg.compound.name = "ethanol"
    cfg.compound.smiles = "CCO"
    wd = WorkDir(str(tmp_path), "ethanol")
    res = stage0_input.run(cfg, wd.path("input"), wd=wd, mock=False, dry_run=True)
    assert res.status == "dry-run"
    assert not wd.path("input").exists()
