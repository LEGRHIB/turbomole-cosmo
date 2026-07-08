"""Core data structures passed between stages."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional


@dataclass
class Conformer:
    """One geometry of the solute as it moves through the pipeline."""
    id: str
    source: str = "unknown"            # md | cosmoconf | supplied | ...
    xyz_path: Optional[str] = None
    charge: Optional[int] = None
    energy_hartree: Optional[float] = None   # gas-phase energy (.energy / EHfile)
    cosmo_path: Optional[str] = None         # .cosmo produced in Stage 2
    weight: Optional[float] = None           # COSMOtherm Boltzmann weight (per phase, filled later)


@dataclass
class Ensemble:
    """A set of conformers of a single compound."""
    compound: str
    charge: Optional[int] = None
    conformers: List[Conformer] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.conformers)

    def add(self, conf: Conformer) -> None:
        self.conformers.append(conf)


@dataclass
class WeightTable:
    """Per-phase COSMOtherm conformer weights: phase -> {conformer_id: weight}."""
    phases: Dict[str, Dict[str, float]] = field(default_factory=dict)

    def dominant(self, phase: str):
        """(conformer_id, weight) of the highest-weight conformer in a phase."""
        w = self.phases.get(phase, {})
        if not w:
            return (None, 0.0)
        cid = max(w, key=w.get)
        return (cid, w[cid])

    def max_weight(self, phase: str) -> float:
        return self.dominant(phase)[1]


@dataclass
class SensitivityVerdict:
    """Output of the sensitivity report — the Stage-4 decision gate."""
    single_conformer_sufficient: bool
    dominant_flips: bool
    max_weight_per_phase: Dict[str, float] = field(default_factory=dict)
    dominant_per_phase: Dict[str, Optional[str]] = field(default_factory=dict)
    recommendation: str = ""
    is_mock: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class StageResult:
    """Uniform return value from every stage function."""
    stage: str
    status: str                        # done | dry-run | skipped | error
    workdir: str = ""
    artifacts: List[str] = field(default_factory=list)
    message: str = ""

    @property
    def ok(self) -> bool:
        return self.status in ("done", "dry-run", "skipped")

    def __str__(self) -> str:
        arts = f"  [{', '.join(self.artifacts)}]" if self.artifacts else ""
        msg = f"  {self.message}" if self.message else ""
        return f"[{self.status:>7}] {self.stage}{msg}{arts}"
