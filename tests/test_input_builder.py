"""COSMOtherm input builder — conformer-resolved AUTOC + relative solubility."""
from cosmors.config import load_config
from cosmors.solvent import ResolvedPanel, PureSolvent, Mixture
from cosmors.stage3_cosmotherm import input_builder as ib

CONFS = ["conf01.cosmo", "conf02.cosmo", "conf03.cosmo"]
PANEL = ResolvedPanel(
    pures=[PureSolvent("ethanol", "ethanol"), PureSolvent("water", "h2o")],
    mixtures=[Mixture("EtOH:H2O 9:1", "ethanol", "h2o", 0.7358, 0.2642)],
    reference="h2o",
)


def test_pure_input_lists_all_conformers_as_one_compound():
    txt = ib.build_pure_input(load_config(None), CONFS, PANEL)
    # every conformer appears on the compound-1 line
    for c in CONFS:
        assert f'f="{c}"' in txt
    assert "autoc" in txt
    assert "EHfile" in txt                 # gas-phase energies from .energy
    assert "relative" in txt
    assert "force_qspr" in txt             # pure screen uses QSPR
    assert "solute=1 pure=3" in txt


def test_mixture_input_has_mole_fractions_and_no_qspr():
    txt = ib.build_mixture_input(load_config(None), CONFS, PANEL.mixtures[0])
    assert "xs={0.0 0.73580 0.26420}" in txt
    assert 'f="ethanol_c0.cosmo"' in txt
    assert 'f="h2o_c0.cosmo"' in txt
    assert "relative" in txt
    assert "force_qspr" not in txt         # mixtures don't use QSPR


def test_build_inputs_writes_files(tmp_path):
    written = ib.build_inputs(load_config(None), CONFS, PANEL, tmp_path)
    assert "pure-screen.inp" in written
    assert "solvents.list" in written
    assert any(f.startswith("mix-") for f in written)
    assert (tmp_path / "solvents.list").read_text().splitlines() == ["ethanol", "h2o"]
