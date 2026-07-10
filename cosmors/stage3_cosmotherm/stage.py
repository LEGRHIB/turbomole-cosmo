"""Stage 3 driver: build COSMOtherm inputs, run (HPC) or mock (sandbox)."""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import List

from ..config import Config
from ..models import StageResult
from ..solvent import load_panel
from . import input_builder


def _gather_cosmo(dft_dir: Path) -> List[Path]:
    return sorted(dft_dir.glob("*.cosmo"))


def _mock_weights(n: int, phases: List[str]) -> dict:
    """Transparently synthetic per-phase weights (labelled MOCK by the caller)."""
    if n <= 1:
        w = {"1": 1.0}
    else:
        rest = round(0.4 / (n - 1), 4)
        w = {"1": 0.6, **{str(i): rest for i in range(2, n + 1)}}
    return {p: dict(w) for p in phases}


def _runme(cfg: Config, inputs: List[str]) -> str:
    env = cfg.paths.cosmotherm_env or "cosmotherm-env.sh"
    lines = ["#!/bin/bash", "# Run the COSMOtherm screen on the HPC.", f"source {env}"]
    for inp in inputs:
        if inp.endswith(".inp"):
            lines.append(f"{cfg.paths.cosmotherm_bin} {inp}")
    return "\n".join(lines) + "\n"


def run(cfg: Config, stage_dir: Path, *, wd, mock: bool, dry_run: bool) -> StageResult:
    stage = "cosmotherm"
    dft_dir = wd.path("dft")
    cosmo = _gather_cosmo(dft_dir)
    panel_path = cfg.cosmotherm.solvent_panel

    if dry_run:
        try:
            panel = load_panel(panel_path)
            summary = f"{len(panel.pures)} pure + {len(panel.mixtures)} mixtures"
        except Exception as exc:
            summary = f"(panel load failed: {exc})"
        return StageResult(stage, "dry-run", str(stage_dir),
                           message=f"build AUTOC conformer inputs ({len(cosmo)} .cosmo, {summary}) "
                                   f"then {cfg.paths.cosmotherm_bin} <inp> per solvent set")

    if not cosmo:
        return StageResult(stage, "error", str(stage_dir),
                           message=f"no .cosmo files in {dft_dir} (run DFT first)")
    if not Path(panel_path).exists():
        return StageResult(stage, "error", str(stage_dir),
                           message=f"solvent panel not found: {panel_path}")

    panel = load_panel(panel_path)

    # self-contained run dir: copy conformer .cosmo/.energy in
    for f in cosmo + list(dft_dir.glob("*.energy")):
        shutil.copy(f, Path(stage_dir) / f.name)

    written = input_builder.build_inputs(cfg, [c.name for c in cosmo], panel, Path(stage_dir))
    (Path(stage_dir) / "runme.sh").write_text(_runme(cfg, written))
    written.append("runme.sh")

    dropped = ""
    if panel.dropped:
        (Path(stage_dir) / "panel-dropped.txt").write_text(
            "\n".join(f"{n}: {r}" for n, r in panel.dropped) + "\n")
        written.append("panel-dropped.txt")
        dropped = f", {len(panel.dropped)} not in COSMObase"

    if mock:
        phases = ["gas", panel.reference] + [p.cosmobase for p in panel.pures[:2]]
        weights = _mock_weights(len(cosmo), phases)
        (Path(stage_dir) / "weights.mock.json").write_text(json.dumps(weights, indent=2) + "\n")
        written.append("weights.mock.json")
        note = f"{len(cosmo)} conformers, {len(panel.pures)} pure + {len(panel.mixtures)} mix (mock weights)"
    else:
        note = f"inputs built for HPC ({len(cosmo)} conformers) — run runme.sh on the cluster"

    return StageResult(stage, "done", str(stage_dir), artifacts=written,
                       message=note + dropped)
