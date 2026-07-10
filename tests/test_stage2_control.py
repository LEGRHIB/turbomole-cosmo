"""Self-contained TURBOMOLE input generation (define / cosmoprep)."""
import pytest

from cosmors.config import load_config
from cosmors.stage2_dft import control


def test_define_input_matches_protocol():
    txt = control.define_input(load_config(None), charge=1)
    assert "a coord" in txt
    assert "b all def2-TZVPD" in txt
    assert "func b-p" in txt
    assert "grid m4" in txt
    assert "\nri\n" in txt                 # RI enabled by default
    assert "\n1\n" in txt                  # charge line
    assert txt.rstrip().endswith("q")


def test_define_ri_toggle_off():
    cfg = load_config(None)
    cfg.theory.ri = False
    txt = control.define_input(cfg, charge=0)
    assert "\nri\n" not in txt
    assert "\n0\n" in txt


def test_cosmoprep_names_output_and_is_ideal():
    txt = control.cosmoprep_input(load_config(None), "conf01.cosmo")
    assert "conf01.cosmo" in txt
    assert txt.split("\n").count("d") == 10   # radius-menu defaults


def test_cosmoprep_refuses_solvent_specific():
    cfg = load_config(None)
    cfg.theory.cosmo_epsilon = "78.4"
    with pytest.raises(ValueError):
        control.cosmoprep_input(cfg, "x.cosmo")
