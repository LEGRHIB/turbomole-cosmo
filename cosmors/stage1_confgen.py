"""Stage 1 — conformer ingest / generation hand-off.

For the peptide/MD path, COSMOconf's own generation is skipped: this stage ingests
a multi-conformer SDF (from the MD front-end, or a supplied one) and packages the
geometries as conformers of one compound. If none is available it falls back to the
single Stage-0 geometry as a 1-conformer ensemble.

Produces:
  ensemble.sdf    all conformers (consistent atom order — interchange format)
  ensemble.json   metadata (source, n_conformers)
"""
from __future__ import annotations

import json
from pathlib import Path

from .config import Config
from .models import StageResult
from . import rdkit_utils as ru


def _resolve_source(cfg: Config, wd):
    """(label, path) of the conformer source, by precedence."""
    if cfg.conformers.multi_sdf:
        return "supplied multi_sdf", Path(cfg.conformers.multi_sdf)
    md_reps = wd.path("md") / "cluster_reps.sdf"
    if cfg.md.enabled and md_reps.exists():
        return "MD cluster representatives (generation skipped)", md_reps
    single = wd.path("input") / "input.sdf"
    if single.exists():
        return "single Stage-0 geometry (1-conformer ensemble)", single
    return None, None


def run(cfg: Config, stage_dir: Path, *, wd, mock: bool, dry_run: bool) -> StageResult:
    stage = "confgen"
    label, src = _resolve_source(cfg, wd)

    if dry_run:
        where = f"{label}: {src}" if src else "NO conformer source"
        return StageResult(stage, "dry-run", str(stage_dir),
                           message=f"ingest conformers from {where} -> ensemble.sdf")

    if src is None or not Path(src).exists():
        return StageResult(stage, "error", str(stage_dir),
                           message="no conformer source (need input.sdf, an MD reps SDF, "
                                   "or conformers.multi_sdf)")

    mols = ru.read_conformers(str(src))
    ens_path = Path(stage_dir) / "ensemble.sdf"
    ru.write_sdf(str(ens_path), mols)
    meta = {"compound": cfg.compound.name, "source": label,
            "source_path": str(src), "n_conformers": len(mols)}
    (Path(stage_dir) / "ensemble.json").write_text(json.dumps(meta, indent=2) + "\n")

    return StageResult(
        stage, "done", str(stage_dir), artifacts=["ensemble.sdf", "ensemble.json"],
        message=f"{len(mols)} conformer(s) via {label}",
    )
