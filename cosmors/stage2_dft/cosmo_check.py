"""Validate a .cosmo: ideal-conductor (epsilon = infinity) + non-trivial.

The hard invariant of the whole pipeline: every .cosmo MUST be an ideal-conductor
surface (epsilon = infinity). A solvent-specific .cosmo would silently corrupt the
COSMO-RS thermodynamics, so we refuse it here.
"""
from __future__ import annotations

import re
from pathlib import Path

_IDEAL = ("infinity", "inf")
_EPS_RE = re.compile(r"epsilon\s*=\s*([A-Za-z0-9.+\-]+)", re.IGNORECASE)


def check_cosmo(path: str) -> dict:
    text = Path(path).read_text(errors="ignore")
    m = _EPS_RE.search(text)
    eps = m.group(1) if m else None
    ideal = eps is not None and eps.lower() in _IDEAL
    has_seg = "$segment_information" in text
    n_seg = 0
    if has_seg:
        block = text.split("$segment_information", 1)[1]
        for line in block.splitlines():
            s = line.strip()
            if s.startswith("$"):
                break
            if s and not s.startswith("#") and s.split()[0].lstrip("-").isdigit():
                n_seg += 1
    return {
        "epsilon": eps,
        "ideal_conductor": ideal,
        "has_segments": has_seg,
        "n_segments": n_seg,
        "ok": ideal and has_seg,
    }


def assert_ideal_conductor(path: str) -> dict:
    r = check_cosmo(path)
    if not r["ideal_conductor"]:
        raise ValueError(
            f"{Path(path).name}: COSMO epsilon is {r['epsilon']!r}, expected infinity "
            f"(ideal conductor). Refusing a solvent-specific .cosmo."
        )
    if not r["has_segments"]:
        raise ValueError(f"{Path(path).name}: no $segment_information — .cosmo is empty/invalid.")
    return r
