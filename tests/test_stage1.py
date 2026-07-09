"""Stage 1 — conformer ingest (single fallback + multi-conformer SDF)."""
import json

import pytest

pytest.importorskip("rdkit")
from rdkit import Chem

from cosmors.config import load_config
from cosmors.workdir import WorkDir
from cosmors import stage0_input, stage1_confgen, rdkit_utils as ru


def test_single_geometry_fallback(tmp_path):
    cfg = load_config(None)
    cfg.compound.name = "ethanol"
    cfg.compound.smiles = "CCO"
    wd = WorkDir(str(tmp_path), "ethanol")
    stage0_input.run(cfg, wd.stage_dir("input"), wd=wd, mock=False, dry_run=False)
    res = stage1_confgen.run(cfg, wd.stage_dir("confgen"), wd=wd, mock=False, dry_run=False)
    assert res.status == "done"
    meta = json.loads((wd.stage_dir("confgen") / "ensemble.json").read_text())
    assert meta["n_conformers"] == 1


def test_multi_sdf_ingest(tmp_path):
    base = ru.embed_from_smiles("CCO")
    mols = [Chem.Mol(base), Chem.Mol(base), Chem.Mol(base)]
    sdf = tmp_path / "multi.sdf"
    ru.write_sdf(str(sdf), mols)

    cfg = load_config(None)
    cfg.compound.name = "ethanol"
    cfg.conformers.multi_sdf = str(sdf)
    wd = WorkDir(str(tmp_path), "ethanol")
    stage1_confgen.run(cfg, wd.stage_dir("confgen"), wd=wd, mock=False, dry_run=False)
    meta = json.loads((wd.stage_dir("confgen") / "ensemble.json").read_text())
    assert meta["n_conformers"] == 3
