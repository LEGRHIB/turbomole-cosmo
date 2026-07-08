from pathlib import Path

from cosmors.cli import main
from cosmors.stages import PIPELINE

TEMPLATE = str(Path(__file__).parents[1] / "config" / "config.template.yaml")


def test_validate_config_ok(capsys):
    rc = main(["--config", TEMPLATE, "validate-config"])
    assert rc == 0
    assert "config OK" in capsys.readouterr().out


def test_run_mock_full_pipeline(tmp_path):
    rc = main(["--config", TEMPLATE, "--workdir", str(tmp_path), "--mock", "run"])
    assert rc == 0
    base = tmp_path / "bombesin"
    for key, _ in PIPELINE:
        assert (base / key / ".done").exists(), f"{key} not stamped"
    # RMSD gate produced its clustering artifact; DFT produced eps=inf .cosmo mocks
    assert (base / "cluster" / "clusters.mock.json").exists()
    assert list((base / "dft").glob("*.mock.cosmo"))


def test_run_mock_is_resumable(tmp_path, capsys):
    main(["--config", TEMPLATE, "--workdir", str(tmp_path), "--mock", "run"])
    capsys.readouterr()
    main(["--config", TEMPLATE, "--workdir", str(tmp_path), "--mock", "run"])
    out = capsys.readouterr().out
    assert "skipped" in out  # every stage skipped on the second pass


def test_dry_run_writes_nothing(tmp_path):
    rc = main(["--config", TEMPLATE, "--workdir", str(tmp_path), "--dry-run", "run"])
    assert rc == 0
    base = tmp_path / "bombesin"
    # no stamps and no mock artifacts anywhere
    if base.exists():
        assert not list(base.rglob(".done"))
        assert not list(base.rglob("*.mock.*"))


def test_real_run_refused_without_flag(tmp_path, capsys):
    rc = main(["--config", TEMPLATE, "--workdir", str(tmp_path), "run"])
    assert rc == 3
    assert "Refusing to run" in capsys.readouterr().err


def test_single_stage_mock(tmp_path):
    rc = main(["--config", TEMPLATE, "--workdir", str(tmp_path), "--mock", "input"])
    assert rc == 0
    assert (tmp_path / "bombesin" / "input" / ".done").exists()
