"""Sensitivity report — the decision gate for the MD front-end.

Consumes per-phase conformer weights and answers: does a single conformer
suffice, or do conformers matter (so the MD front-end is worth running)?

Rules (from the project brief):
  * if ONE conformer exceeds the threshold (~0.95) in EVERY phase
        -> "single-conformer sufficient"
  * if weights are spread, OR the dominant conformer changes between phases
    (gas / water / target solvent)
        -> "conformers matter — consider the MD front-end"
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

from .config import Config
from .models import SensitivityVerdict, StageResult, WeightTable
from . import parse


def evaluate(wt: WeightTable, threshold: float = 0.95,
             phases: Optional[List[str]] = None) -> SensitivityVerdict:
    phases = phases or list(wt.phases)
    dom = {p: wt.dominant(p) for p in phases}          # phase -> (conf_id, weight)
    max_w = {p: dom[p][1] for p in phases}
    dom_id = {p: dom[p][0] for p in phases}

    distinct = {cid for cid in dom_id.values() if cid is not None}
    all_above = bool(phases) and all(w > threshold for w in max_w.values())
    same_conf = len(distinct) == 1
    single_ok = all_above and same_conf
    flips = len(distinct) > 1

    pct = f"{threshold * 100:.0f}%"
    if single_ok:
        rec = (f"single-conformer sufficient — conformer {next(iter(distinct))} dominates "
               f"every phase (>{pct}); the MD front-end is unlikely to change the ranking.")
    elif flips:
        order = ", ".join(f"{p}:{dom_id[p]}" for p in phases)
        rec = (f"conformers matter — the dominant conformer changes between phases "
               f"({order}); consider running the MD front-end (Stage 4).")
    else:
        worst = min(max_w.values()) if max_w else 0.0
        rec = (f"conformers matter — weight is spread (max {worst:.2f} < {threshold:.2f} "
               f"in at least one phase); consider running the MD front-end (Stage 4).")

    return SensitivityVerdict(
        single_conformer_sufficient=single_ok,
        dominant_flips=flips,
        max_weight_per_phase=max_w,
        dominant_per_phase=dom_id,
        recommendation=rec,
    )


def format_report(verdict: SensitivityVerdict) -> str:
    lines = ["COSMO-RS conformer sensitivity report",
             "=" * 38]
    if verdict.is_mock:
        lines.append("** MOCK weights — illustrative only, not a real result **")
    lines.append("")
    lines.append(f"{'phase':<16}{'dominant conf':<16}{'max weight':>12}")
    for phase in verdict.max_weight_per_phase:
        cid = verdict.dominant_per_phase.get(phase)
        w = verdict.max_weight_per_phase[phase]
        lines.append(f"{phase:<16}{str(cid):<16}{w:>12.3f}")
    lines.append("")
    lines.append(f"single-conformer sufficient : {verdict.single_conformer_sufficient}")
    lines.append(f"dominant conformer flips    : {verdict.dominant_flips}")
    lines.append("")
    lines.append("VERDICT: " + verdict.recommendation)
    return "\n".join(lines) + "\n"


def run(cfg: Config, stage_dir: Path, *, wd, mock: bool, dry_run: bool) -> StageResult:
    stage = "sensitivity"
    ct_dir = wd.path("cosmotherm")
    real = ct_dir / "weights.json"
    mocked = ct_dir / "weights.mock.json"

    if dry_run:
        return StageResult(stage, "dry-run", str(stage_dir),
                           message="parse per-phase conformer weights -> "
                                   ">95% / dominant-flip decision gate")

    src = real if real.exists() else mocked
    if not src.exists():
        # fall back to a text .out if present
        out = ct_dir / "cosmotherm.out"
        if out.exists():
            wt = parse.parse_weights_text(out.read_text())
        else:
            return StageResult(stage, "error", str(stage_dir),
                               message=f"no conformer weights found in {ct_dir}")
    else:
        wt = parse.load_weights_json(str(src))

    verdict = evaluate(wt, threshold=cfg.cosmotherm.single_conformer_threshold)
    verdict.is_mock = (src == mocked)

    (Path(stage_dir) / "sensitivity.json").write_text(
        json.dumps(verdict.to_dict(), indent=2) + "\n")
    (Path(stage_dir) / "sensitivity.txt").write_text(format_report(verdict))

    tag = "MOCK " if verdict.is_mock else ""
    verd = ("single-conformer sufficient" if verdict.single_conformer_sufficient
            else "conformers matter")
    return StageResult(stage, "done", str(stage_dir),
                       artifacts=["sensitivity.json", "sensitivity.txt"],
                       message=f"{tag}verdict: {verd}")
