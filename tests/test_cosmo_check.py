"""The ideal-conductor (epsilon = infinity) gate on .cosmo files."""
from pathlib import Path

import pytest

from cosmors.stage2_dft.cosmo_check import check_cosmo, assert_ideal_conductor

FIX = Path(__file__).parent / "fixtures"
IDEAL = str(FIX / "ideal.cosmo")
SOLVENT = str(FIX / "solvent.cosmo")


def test_ideal_conductor_passes():
    r = check_cosmo(IDEAL)
    assert r["ideal_conductor"] is True
    assert r["ok"] is True
    assert r["n_segments"] == 3
    assert_ideal_conductor(IDEAL)          # does not raise


def test_solvent_specific_is_rejected():
    r = check_cosmo(SOLVENT)
    assert r["epsilon"] == "78.4"
    assert r["ideal_conductor"] is False
    with pytest.raises(ValueError):
        assert_ideal_conductor(SOLVENT)
