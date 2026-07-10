"""Sigma-profile parsing + normalization."""
from pathlib import Path

import pytest

pytest.importorskip("numpy")

from cosmors.sigma_profile import parse_cosmo, sigma_profile

TINY = str(Path(__file__).parent / "fixtures" / "tiny.cosmo")


def test_parse_cosmo_segments():
    sigma, area, natoms = parse_cosmo(TINY)
    assert len(sigma) == 8
    assert natoms == 3
    assert abs(area.sum() - 1.87) < 1e-6


def test_profile_area_is_conserved():
    sigma, area, _ = parse_cosmo(TINY)
    _, hist = sigma_profile(sigma, area, bins=61, srange=(-0.03, 0.03))
    # every segment's sigma is inside the range, so the histogram holds all the area
    assert abs(hist.sum() - area.sum()) < 1e-6


def test_normalized_profile_sums_to_one():
    sigma, area, _ = parse_cosmo(TINY)
    _, hist = sigma_profile(sigma, area)
    normalized = hist / hist.sum()
    assert abs(normalized.sum() - 1.0) < 1e-9
