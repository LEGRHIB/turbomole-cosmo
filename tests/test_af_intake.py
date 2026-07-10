"""AlphaFold mmCIF intake: parser + pLDDT gate + Stage 0 routing."""
from pathlib import Path

from cosmors.af_intake import parse_cif_atoms, plddt_summary, intake
from cosmors.config import load_config
from cosmors.workdir import WorkDir
from cosmors import stage0_input

MINI = str(Path(__file__).parent / "fixtures" / "mini_af.cif")


def test_parse_cif_atoms():
    atoms = parse_cif_atoms(MINI)
    assert len(atoms) == 8
    assert atoms[0]["comp"] == "GLY"
    assert atoms[0]["element"] == "N"
    assert atoms[4]["plddt"] == 40.0


def test_plddt_gate_flags_low_confidence():
    s = plddt_summary(parse_cif_atoms(MINI), gate_low=50.0)
    assert s["n_residues"] == 2
    assert "ALA2" in s["weak_residues"]      # mean ~30 < 50
    assert "GLY1" not in s["weak_residues"]  # mean ~85


def test_intake_heavy_atom_mode():
    r = intake(MINI)                         # no template
    assert r["mode"] == "heavy_atoms"
    assert r["n_atoms"] == 8
    assert r["charge"] == 0
    assert r["xyz"].splitlines()[0] == "8"


def test_stage0_routes_cif(tmp_path):
    cfg = load_config(None)
    cfg.compound.name = "mini"
    cfg.compound.input_path = MINI
    wd = WorkDir(str(tmp_path), "mini")
    res = stage0_input.run(cfg, wd.stage_dir("input"), wd=wd, mock=False, dry_run=False)
    assert res.status == "done"
    d = wd.stage_dir("input")
    assert (d / "geometry.xyz").exists()
    assert (d / "plddt.json").exists()
    assert (d / "charge.txt").read_text().strip() == "0"
