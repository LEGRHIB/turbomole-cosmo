"""Sensitivity decision gate + weight parsing."""
from cosmors.models import WeightTable
from cosmors.sensitivity import evaluate
from cosmors import parse


def _wt(phases):
    w = WeightTable()
    w.phases = phases
    return w


def test_single_conformer_sufficient():
    wt = _wt({
        "gas": {"1": 0.99, "2": 0.01},
        "h2o": {"1": 0.97, "2": 0.03},
        "ethanol": {"1": 0.98, "2": 0.02},
    })
    v = evaluate(wt, threshold=0.95)
    assert v.single_conformer_sufficient is True
    assert v.dominant_flips is False
    assert "single-conformer sufficient" in v.recommendation


def test_dominant_conformer_flips():
    wt = _wt({
        "gas": {"1": 0.90, "2": 0.10},
        "h2o": {"1": 0.20, "2": 0.80},   # conformer 2 now dominates
    })
    v = evaluate(wt, threshold=0.95)
    assert v.dominant_flips is True
    assert v.single_conformer_sufficient is False
    assert "conformers matter" in v.recommendation


def test_weights_spread_no_dominant():
    wt = _wt({
        "gas": {"1": 0.55, "2": 0.45},
        "h2o": {"1": 0.52, "2": 0.48},
    })
    v = evaluate(wt, threshold=0.95)
    assert v.single_conformer_sufficient is False
    assert v.dominant_flips is False
    assert "spread" in v.recommendation


def test_parse_weights_text():
    text = (
        "Conformer weights (phase = gas):\n"
        "  1   0.8234\n"
        "  2   0.1766\n"
        "\n"
        "Conformer weights (phase = h2o):\n"
        "  1   0.4012\n"
        "  2   0.5988\n"
    )
    wt = parse.parse_weights_text(text)
    assert set(wt.phases) == {"gas", "h2o"}
    assert abs(wt.phases["gas"]["1"] - 0.8234) < 1e-9
    assert wt.dominant("h2o")[0] == "2"
