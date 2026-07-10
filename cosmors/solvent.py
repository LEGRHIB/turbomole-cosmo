"""Solvent panel resolution.

Turns the v/v crystallization panel (config/solvent_panel.yaml) into COSMObase
compound names + mole fractions that COSMOtherm can consume.

Two reference tables (both standard textbook constants, NOT computed results):
  * COSMOBASE — panel name -> COSMObase basename, taken verbatim from
    protocols/cosmotherm-screen/screening-panel-names.txt. `None` marks solvents
    not present in this COSMObase (dropped + reported).
  * DENSITY_MW — density (g/mL, 25 C) and molar mass (g/mol) for the cosolvents
    that appear in the aqueous binaries, used only for the v/v -> mole-fraction
    conversion.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None


# panel name (lowercased) -> COSMObase basename  (None = not in this COSMObase)
COSMOBASE: Dict[str, Optional[str]] = {
    "water": "h2o", "h2o": "h2o",
    "methanol": "methanol", "meoh": "methanol",
    "ethanol": "ethanol", "etoh": "ethanol", "ethanol (etoh)": "ethanol",
    "1-propanol": "propanol", "propanol": "propanol", "n-propanol": "propanol",
    "2-propanol": "2-propanol", "2-propanol (ipa)": "2-propanol", "ipa": "2-propanol",
    "isopropanol": "2-propanol",
    "1-butanol": "1-butanol", "2-butanol": "2-butanol", "1-pentanol": "1-pentanol",
    "acetone": "propanone", "propanone": "propanone",
    "2-butanone (mek)": "butanone", "2-butanone": "butanone", "mek": "butanone",
    "4-methyl-2-pentanone (mibk)": "4-methyl-2-pentanone",
    "4-methyl-2-pentanone": "4-methyl-2-pentanone", "mibk": "4-methyl-2-pentanone",
    "acetonitrile": "acetonitrile", "acetonitrile (acn)": "acetonitrile", "acn": "acetonitrile",
    "thf": "thf",
    "1,4-dioxane": "dioxane", "dioxane": "dioxane",
    "anisole": "anisole",
    "ethyl acetate": "ethylacetate", "ethylacetate": "ethylacetate",
    "isopropyl acetate": "isopropylacetate",
    "n-propyl acetate": "n-propylacetate",
    "butyl acetate": "n-butylacetate",
    "heptane": "n-heptane", "n-heptane": "n-heptane",
    "methyl cyclohexane": "methylcyclohexane", "methylcyclohexane": "methylcyclohexane",
    "toluene": "toluene",
    "xylene": "1,3-dimethylbenzene",
    # not in this COSMObase (per screening-panel-names.txt):
    "cyclopentyl methyl ether (cpme)": None, "cyclopentyl methyl ether": None, "cpme": None,
    "2-methyl-thf": None, "2-methyl thf": None, "2-methyltetrahydrofuran": None,
    "isobutyl acetate": None,
}

# density (g/mL @ 25 C), molar mass (g/mol) — standard reference constants.
DENSITY_MW: Dict[str, Tuple[float, float]] = {
    "h2o": (0.9970, 18.015),
    "methanol": (0.7918, 32.042),
    "ethanol": (0.7893, 46.069),
    "propanol": (0.8035, 60.096),
    "2-propanol": (0.7855, 60.096),
    "propanone": (0.7899, 58.080),
    "acetonitrile": (0.7857, 41.053),
    "thf": (0.8892, 72.107),
    "dioxane": (1.0329, 88.106),
}


def _canon(name: str) -> Optional[str]:
    """Map a panel name to a COSMObase basename, tolerant of '(...)' suffixes."""
    key = name.strip().lower()
    if key in COSMOBASE:
        return COSMOBASE[key]
    base = re.sub(r"\s*\(.*?\)\s*", " ", key).strip()   # "water (h2o)" -> "water"
    if base in COSMOBASE:
        return COSMOBASE[base]
    m = re.search(r"\(([^)]+)\)", key)                  # "... (h2o)" -> "h2o"
    if m and m.group(1).strip() in COSMOBASE:
        return COSMOBASE[m.group(1).strip()]
    return "__UNKNOWN__"


def vv_to_mole_fraction(cb1: str, cb2: str, v1: float, v2: float) -> Tuple[float, float]:
    """Volume ratio v1:v2 of two COSMObase components -> (x1, x2) mole fractions."""
    for cb in (cb1, cb2):
        if cb not in DENSITY_MW:
            raise KeyError(f"no density/MW for {cb!r} — cannot convert v/v to mole fraction")
    rho1, mw1 = DENSITY_MW[cb1]
    rho2, mw2 = DENSITY_MW[cb2]
    n1 = v1 * rho1 / mw1
    n2 = v2 * rho2 / mw2
    tot = n1 + n2
    return n1 / tot, n2 / tot


@dataclass
class PureSolvent:
    name: str
    cosmobase: str


@dataclass
class Mixture:
    label: str
    comp1: str          # COSMObase name
    comp2: str
    x1: float           # mole fraction
    x2: float


@dataclass
class ResolvedPanel:
    pures: List[PureSolvent] = field(default_factory=list)
    mixtures: List[Mixture] = field(default_factory=list)
    dropped: List[Tuple[str, str]] = field(default_factory=list)   # (name, reason)
    reference: str = "h2o"

    def pure_names(self) -> List[str]:
        return [p.cosmobase for p in self.pures]


def load_panel(path: str) -> ResolvedPanel:
    """Read solvent_panel.yaml and resolve to COSMObase names + mole fractions."""
    if yaml is None:
        raise RuntimeError("pyyaml required to read the solvent panel")
    with open(path) as fh:
        data = yaml.safe_load(fh) or {}

    panel = ResolvedPanel()
    seen = set()
    for entry in data.get("pure", []):
        name = entry["name"]
        cb = _canon(name)
        if cb == "__UNKNOWN__":
            panel.dropped.append((name, "unmapped name (no COSMObase entry)"))
        elif cb is None:
            panel.dropped.append((name, "not in this COSMObase"))
        elif cb not in seen:
            panel.pures.append(PureSolvent(name=name, cosmobase=cb))
            seen.add(cb)

    for entry in data.get("mixtures", []):
        label = entry["name"]
        comps = entry.get("components", [])
        ratio = entry.get("ratio", [])
        if len(comps) != 2 or len(ratio) != 2:
            panel.dropped.append((label, "mixture needs exactly 2 components + ratio"))
            continue
        cb1, cb2 = _canon(comps[0]), _canon(comps[1])
        if cb1 in (None, "__UNKNOWN__") or cb2 in (None, "__UNKNOWN__"):
            panel.dropped.append((label, "component not in COSMObase"))
            continue
        try:
            x1, x2 = vv_to_mole_fraction(cb1, cb2, float(ratio[0]), float(ratio[1]))
        except KeyError as exc:
            panel.dropped.append((label, str(exc)))
            continue
        panel.mixtures.append(Mixture(label=label, comp1=cb1, comp2=cb2, x1=x1, x2=x2))

    for entry in data.get("buffers", []):
        panel.dropped.append((entry["name"],
                              f"approximated as {entry.get('approximate_as', 'water')}"))
    return panel
