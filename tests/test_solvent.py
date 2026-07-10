"""Solvent panel resolution: COSMObase names + v/v -> mole fraction."""
from pathlib import Path

from cosmors.solvent import vv_to_mole_fraction, load_panel

PANEL = str(Path(__file__).parents[1] / "config" / "solvent_panel.yaml")


def test_vv_to_mole_fraction_ethanol_water_9_1():
    x_eth, x_w = vv_to_mole_fraction("ethanol", "h2o", 9, 1)
    # 9:1 v/v ethanol:water is ~0.74 mole fraction ethanol
    assert abs((x_eth + x_w) - 1.0) < 1e-9
    assert 0.72 < x_eth < 0.75


def test_panel_maps_to_cosmobase_names():
    panel = load_panel(PANEL)
    names = panel.pure_names()
    assert "h2o" in names
    assert "propanone" in names          # acetone -> propanone
    assert "1,3-dimethylbenzene" in names  # xylene
    assert "thf" in names


def test_panel_drops_solvents_not_in_cosmobase():
    panel = load_panel(PANEL)
    dropped = " ".join(f"{n} {r}" for n, r in panel.dropped).lower()
    assert "cpme" in dropped or "cyclopentyl" in dropped
    assert "not in this cosmobase" in dropped


def test_panel_mixtures_have_normalized_fractions():
    panel = load_panel(PANEL)
    assert panel.mixtures
    for m in panel.mixtures:
        assert abs((m.x1 + m.x2) - 1.0) < 1e-6
        assert 0.0 < m.x1 < 1.0
