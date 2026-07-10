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


def test_apply_scf_tuning(tmp_path):
    ctrl = tmp_path / "control"
    ctrl.write_text("$title\n$scfiterlimit 30\n$scfdamp start=0.500 step=0.050 min=0.100\n$end\n")
    control.apply_scf_tuning(str(ctrl))
    t = ctrl.read_text()
    assert "$scfiterlimit      300" in t          # raised from the default 30
    assert "start=0.700" in t                     # damping replaced
    assert "$scforbitalshift  automatic=.3" in t  # inserted (was absent)
    assert "$fermi" in t                          # Fermi net appended
    assert t.count("$end") == 1                   # still exactly one $end
