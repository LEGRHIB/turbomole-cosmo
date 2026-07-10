"""Stage registry — every stage now has a real implementation.

Uniform signature: fn(cfg, stage_dir, *, wd, mock, dry_run) -> StageResult.
  --mock    keeps the commercial-binary steps (MD engine, DFT SCF, COSMOtherm run)
            synthetic — clearly labelled, no fabricated scientific numbers.
  --dry-run documents the exact HPC command per stage and writes nothing.

Execution order: Stage 4 (MD) runs before Stage 1 so, when enabled, MD is the
conformer source and COSMOconf's own generation is skipped.
"""
from __future__ import annotations

from typing import Callable, List, Tuple

from .models import StageResult
from . import stage0_input, stage4_md, stage1_confgen, cluster as _cluster
from . import stage2_dft, stage3_cosmotherm, sensitivity as _sensitivity

StageFn = Callable[..., StageResult]

PIPELINE: List[Tuple[str, StageFn]] = [
    ("input", stage0_input.run),          # SMILES/SDF/PDB/AlphaFold-CIF -> 3D + charge
    ("md", stage4_md.run),                # MD front-end -> cluster_reps.sdf (if md.enabled)
    ("confgen", stage1_confgen.run),      # ingest reps / COSMOconf generation
    ("cluster", _cluster.run),            # enforced RMSD gate before DFT
    ("dft", stage2_dft.run),              # COSMOconf / self-contained TURBOMOLE, eps=inf
    ("cosmotherm", stage3_cosmotherm.run),  # AUTOC input builder + runner
    ("sensitivity", _sensitivity.run),    # per-phase weights -> decision gate
]

STAGES = dict(PIPELINE)
