from pathlib import Path

import pytest

from cosmors.cli import main
from cosmors.stages import PIPELINE

ROOT = Path(__file__).parents[1]
TEMPLATE = str(ROOT / "config" / "config.template.yaml")
FIXTURE = str(ROOT / "tests" / "fixtures" / "ethanol_config.yaml")  # ethanol / SMILES


def test_validate_config_ok(capsys):
    rc = main(["--config", TEMPLATE, "validate-config"])
    assert rc == 0
    assert "config OK" in capsys.readouterr().out


def test_real_stage_runs_without_mock(tmp_path):
    pytest.importorskip("rdkit")
    rc = main(["--config", FIXTURE, "--workdir", str(tmp_path), "input"])
    assert rc == 0
    assert (tmp_path / "ethanol" / "input" / "geometry.xyz").exists()


def test_dry_run_writes_nothing(tmp_path):
    rc = main(["--config", TEMPLATE, "--workdir", str(tmp_path), "--dry-run", "run"])
    assert rc == 0
    base = tmp_path / "bombesin"
    if base.exists():
        assert not list(base.rglob(".done"))
        assert not list(base.rglob("*.mock.*"))


# --- integration: real Stage 0/1/cluster + mock commercial stages on ethanol --- #
def test_run_mock_full_pipeline(tmp_path):
    pytest.importorskip("rdkit")
    rc = main(["--config", FIXTURE, "--workdir", str(tmp_path), "--mock", "run"])
    assert rc == 0
    base = tmp_path / "ethanol"
    for key, _ in PIPELINE:
        assert (base / key / ".done").exists(), f"{key} not stamped"
    # real artifacts from the RDKit stages
    assert (base / "input" / "geometry.xyz").exists()
    assert (base / "md" / "cluster_reps.sdf").exists()   # MD front-end ran (synthetic frames)
    assert (base / "confgen" / "ensemble.sdf").exists()
    assert (base / "cluster" / "kept.sdf").exists()
    assert (base / "cluster" / "clusters.json").exists()
    # real Stage 2 produced a .cosmo at eps=infinity + the generated define/cosmoprep inputs
    assert (base / "dft" / "conf01.cosmo").exists()
    assert (base / "dft" / "define.in").exists()
    from cosmors.stage2_dft.cosmo_check import check_cosmo
    assert check_cosmo(str(base / "dft" / "conf01.cosmo"))["ideal_conductor"]
    # real Stage 3 built the AUTOC input; sensitivity produced a verdict
    assert (base / "cosmotherm" / "pure-screen.inp").exists()
    assert (base / "sensitivity" / "sensitivity.json").exists()


def test_run_mock_is_resumable(tmp_path, capsys):
    pytest.importorskip("rdkit")
    main(["--config", FIXTURE, "--workdir", str(tmp_path), "--mock", "run"])
    capsys.readouterr()
    main(["--config", FIXTURE, "--workdir", str(tmp_path), "--mock", "run"])
    assert "skipped" in capsys.readouterr().out


def test_single_stage_mock(tmp_path):
    pytest.importorskip("rdkit")
    rc = main(["--config", FIXTURE, "--workdir", str(tmp_path), "--mock", "input"])
    assert rc == 0
    assert (tmp_path / "ethanol" / "input" / ".done").exists()
    assert (tmp_path / "ethanol" / "input" / "geometry.xyz").exists()
