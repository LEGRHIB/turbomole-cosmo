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


def stage_dft(cfg: Config, stage_dir: Path, *, wd, mock: bool, dry_run: bool) -> StageResult:
    """Stage 2 — COSMOconf-orchestrated TURBOMOLE DFT/COSMO (eps=inf). Real: P4."""
    files = [(f"conf{i:02d}.mock.cosmo", f"MOCK .cosmo (eps=infinity) conformer {i}")
             for i in (1, 2)]
    files += [(f"conf{i:02d}.mock.energy", f"MOCK gas-phase energy conformer {i}")
              for i in (1, 2)]
    return _result(
        "dft", stage_dir, dry_run=dry_run,
        cmd=f"cosmoconf-driven {cfg.theory.functional}/{cfg.theory.basis} "
            f"{cfg.theory.cavity} COSMO eps={cfg.theory.cosmo_epsilon} "
            f"(self-contained turbomoleio backend)",
        mock_files=files,
        message="2 .cosmo + .energy at eps=infinity (mock)",
    )


def stage_cosmotherm(cfg: Config, stage_dir: Path, *, wd, mock: bool, dry_run: bool) -> StageResult:
    """Stage 3 — COSMOtherm relative solubility, AUTOC conformers. Real: P3."""
    out = (
        "MOCK COSMOtherm output — relative solubility (log x_RS). Placeholders only.\n"
        f"ctd={cfg.ctd.default}  T={cfg.cosmotherm.temperature_C}C\n"
        "solvent        log10(x_RS)\nwater          -9.99  (MOCK)\nethanol        -9.99  (MOCK)\n"
    )
    return _result(
        "cosmotherm", stage_dir, dry_run=dry_run,
        cmd=f"{cfg.paths.cosmotherm_bin} <input>  (AUTOC folder-of-.cosmo, "
            f"relative solub, force_qspr={cfg.cosmotherm.force_qspr})",
        mock_files=[("cosmotherm.mock.out", out)],
        message="relative-solubility screen written (mock)",
    )


def stage_sensitivity(cfg: Config, stage_dir: Path, *, wd, mock: bool, dry_run: bool) -> StageResult:
    """Sensitivity report — parse per-phase weights -> decision gate. Real: P3."""
    verdict = {
        "is_mock": True, "single_conformer_sufficient": None, "dominant_flips": None,
        "note": "MOCK — real verdict computed from COSMOtherm weights in P3",
        "rule": "flag single-conformer if one conformer >0.95 weight in every phase",
    }
    return _result(
        "sensitivity", stage_dir, dry_run=dry_run,
        cmd="parse per-phase conformer weights; apply >95% / dominant-flip decision gate",
        mock_files=[("sensitivity.mock.json", verdict)],
        message="sensitivity verdict written (mock)",
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
    ("dft", stage_dft),               # mock  (P4)
    ("cosmotherm", stage_cosmotherm), # mock  (P3)
    ("sensitivity", stage_sensitivity),  # mock (P3)
]

STAGES = dict(PIPELINE)
