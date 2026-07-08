from pathlib import Path

import pytest

from cosmors.config import load_config, validate, require_runtime

TEMPLATE = str(Path(__file__).parents[1] / "config" / "config.template.yaml")


def test_defaults_are_valid():
    cfg = load_config(None)
    errors, _ = validate(cfg)
    assert errors == []
    assert cfg.compound.name == "bombesin"
    assert cfg.cosmotherm.property == "relative_solubility"


def test_template_loads():
    cfg = load_config(TEMPLATE)
    errors, warnings = validate(cfg)
    assert errors == []
    assert cfg.ctd.default == "BP_TZVPD_FINE_25.ctd"
    assert cfg.ctd.default in cfg.ctd.licensed
    assert str(cfg.theory.cosmo_epsilon).lower() in ("infinity", "inf")


def test_env_override_scalar_and_bool(monkeypatch):
    monkeypatch.setenv("COSMORS_CONFORMERS_RMSD_CUTOFF", "1.5")
    monkeypatch.setenv("COSMORS_MD_ENABLED", "false")
    monkeypatch.setenv("ACCOUNT", "lp_other")
    cfg = load_config(TEMPLATE)
    assert cfg.conformers.rmsd_cutoff == 1.5
    assert cfg.md.enabled is False
    assert cfg.slurm.account == "lp_other"


def test_epsilon_must_be_infinity():
    cfg = load_config(None)
    cfg.theory.cosmo_epsilon = "4.0"
    errors, _ = validate(cfg)
    assert any("cosmo_epsilon" in e for e in errors)


def test_default_ctd_must_be_licensed():
    cfg = load_config(None)
    cfg.ctd.default = "SOMETHING_ELSE.ctd"
    errors, _ = validate(cfg)
    assert any("licensed" in e for e in errors)


def test_unsupported_property_rejected():
    cfg = load_config(None)
    cfg.cosmotherm.property = "absolute_solubility"
    errors, _ = validate(cfg)
    assert any("property" in e for e in errors)


def test_require_runtime_flags_missing_paths():
    cfg = load_config(None)  # template paths for ct_* are null
    missing = require_runtime(cfg)
    assert any("CDIR" in m for m in missing)
