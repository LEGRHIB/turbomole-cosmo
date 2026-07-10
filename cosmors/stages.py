"""Stage registry.

Real (sandbox-capable, RDKit-based) stages: input, confgen, cluster.
Mock stubs still standing in for commercial-binary stages: md (P5), dft (P4),
cosmotherm + sensitivity (P3). Each stub:

  * --dry-run : prints the real command it *would* run on the HPC; writes nothing.
  * --mock    : writes a clearly-labelled synthetic artifact (`.mock.` filenames,
                MOCK banner). No real scientific numbers are invented.

Uniform signature: fn(cfg, stage_dir, *, wd, mock, dry_run) -> StageResult.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, List, Tuple

from .config import Config
from .models import StageResult
from . import stage0_input, stage1_confgen, cluster as _cluster
from . import stage2_dft, stage3_cosmotherm, sensitivity as _sensitivity

_MOCK_BANNER = "# MOCK ARTIFACT — synthetic placeholder, NOT a real result.\n"


def _mock_write(path: Path, payload) -> None:
    if isinstance(payload, (dict, list)):
        path.write_text(_MOCK_BANNER + json.dumps(payload, indent=2) + "\n")
    else:
        path.write_text(_MOCK_BANNER + str(payload) + "\n")


def _result(stage, stage_dir, *, dry_run, cmd, mock_files, message):
    if dry_run:
        return StageResult(stage=stage, status="dry-run", workdir=str(stage_dir),
                           message=f"would run: {cmd}")
    arts = []
    for name, payload in mock_files:
        _mock_write(Path(stage_dir) / name, payload)
        arts.append(name)
    return StageResult(stage=stage, status="done", workdir=str(stage_dir),
                       artifacts=arts, message=message)


# --------------------------------------------------------------------------- #
# Mock stubs (commercial-binary stages)
# --------------------------------------------------------------------------- #
def stage_md(cfg: Config, stage_dir: Path, *, wd, mock: bool, dry_run: bool) -> StageResult:
    """Stage 4 — MD front-end: frames -> RMSD cluster -> multi-conf SDF. Real: P5."""
    if not cfg.md.enabled:
        return StageResult("md", "skipped", str(stage_dir),
                           message="md.enabled=false — COSMOconf generation used instead")
    return _result(
        "md", stage_dir, dry_run=dry_run,
        cmd=f"{cfg.md.engine} {cfg.md.method} @ {cfg.md.temperature_K} K, "
            f"{cfg.md.n_frames} frames -> Butina(rmsd={cfg.md.cluster_rmsd}) -> reps.sdf",
        mock_files=[("cluster_reps.mock.sdf",
                     "MOCK: representative conformers from MD clustering")],
        message="MD proposed conformer representatives (mock)",
    )


# --------------------------------------------------------------------------- #
# Pipeline order
# --------------------------------------------------------------------------- #
StageFn = Callable[..., StageResult]

PIPELINE: List[Tuple[str, StageFn]] = [
    ("input", stage0_input.run),      # real (RDKit)
    ("md", stage_md),                 # mock  (P5)
    ("confgen", stage1_confgen.run),  # real (RDKit)
    ("cluster", _cluster.run),        # real (RDKit) — enforced RMSD gate
    ("dft", stage2_dft.run),          # real — COSMOconf / self-contained TURBOMOLE
    ("cosmotherm", stage3_cosmotherm.run),  # real — AUTOC input builder + runner
    ("sensitivity", _sensitivity.run),      # real — weight parse + decision gate
]

STAGES = dict(PIPELINE)
