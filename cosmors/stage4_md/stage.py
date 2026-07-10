"""Stage 4 driver — MD front-end: seed geometry -> frames -> RMSD reps -> SDF.

Enabled by config `md.enabled`; produces cluster_reps.sdf, which Stage 1 ingests
(COSMOconf generation skipped). The AlphaFold model from Stage 0 is the seed.

Sandbox: --dry-run documents the MD commands; without an MD engine it falls back to
synthetic frames so the frames->cluster->SDF pipeline is exercised. Real MD (OpenMM
in-process, or GROMACS on the HPC) runs when available.
"""
from __future__ import annotations

import json
from pathlib import Path

from ..config import Config
from ..models import StageResult
from .. import rdkit_utils as ru
from . import frames as _frames
from . import openmm_runner, gromacs_runner


def run(cfg: Config, stage_dir: Path, *, wd, mock: bool, dry_run: bool) -> StageResult:
    stage = "md"
    d = Path(stage_dir)
    if not cfg.md.enabled:
        return StageResult(stage, "skipped", str(d),
                           message="md.enabled=false — COSMOconf generation used instead")

    seed_sdf = wd.path("input") / "input.sdf"

    if dry_run:
        if cfg.md.engine == "gromacs":
            cmd = "; ".join(gromacs_runner.commands(cfg))
        else:
            cmd = f"openmm {cfg.md.method} @ {cfg.md.temperature_K} K, {cfg.md.n_frames} frames"
        return StageResult(stage, "dry-run", str(d),
                           message=f"[{cfg.md.engine}] {cmd} -> Butina(rmsd={cfg.md.cluster_rmsd}) "
                                   f"-> cluster_reps.sdf")

    if not seed_sdf.exists():
        return StageResult(stage, "error", str(d),
                           message=f"no seed geometry ({seed_sdf}); an AF heavy-atom intake "
                                   f"needs xtb pre-opt to an SDF first")

    seed = ru.read_conformers(str(seed_sdf))[0]
    real = (not mock) and cfg.md.engine == "openmm" and openmm_runner.available()

    if real:
        from rdkit import Chem
        seed_pdb = d / "seed.pdb"
        Chem.MolToPDBFile(seed, str(seed_pdb))
        frames = openmm_runner.run_md(str(seed_pdb), cfg, str(d))
        engine = "openmm"
    else:
        n = min(cfg.md.n_frames, 40)          # cap synthetic frames for speed
        frames = _frames.synthetic_frames(seed, n, scale=0.5, seed=0)
        engine = "mock(synthetic frames)"

    reps, report = _frames.cluster_frames(frames, cfg.md.cluster_rmsd, cfg.conformers.max_conformers)
    _frames.write_reps(reps, str(d / "cluster_reps.sdf"))
    report.update({"engine": engine, "method": cfg.md.method,
                   "temperature_K": cfg.md.temperature_K, "n_frames": len(frames)})
    (d / "md_report.json").write_text(json.dumps(report, indent=2) + "\n")

    tag = "" if real else " (mock)"
    return StageResult(stage, "done", str(d), artifacts=["cluster_reps.sdf", "md_report.json"],
                       message=f"{engine}: {len(frames)} frames -> {len(reps)} reps "
                               f"(rmsd {cfg.md.cluster_rmsd}){tag}")
