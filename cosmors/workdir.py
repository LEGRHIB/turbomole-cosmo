"""Idempotent, resumable working directories.

Each stage gets `<root>/<compound>/<stage>/` and drops a `.done` stamp on success.
A resumable run skips any stage whose stamp already exists (unless forced), so a
restart never redoes completed work.
"""
from __future__ import annotations

import datetime as _dt
from pathlib import Path
from typing import Callable

from .models import StageResult


class WorkDir:
    def __init__(self, root: str, compound: str):
        self.base = Path(root) / compound

    def path(self, stage: str) -> Path:
        """Stage path WITHOUT creating it (used by --dry-run to stay write-free)."""
        return self.base / stage

    def stage_dir(self, stage: str) -> Path:
        d = self.base / stage
        d.mkdir(parents=True, exist_ok=True)
        return d

    def stamp(self, stage: str) -> Path:
        return self.stage_dir(stage) / ".done"

    def is_done(self, stage: str) -> bool:
        return self.stamp(stage).exists()

    def mark_done(self, stage: str, info: str = "") -> None:
        ts = _dt.datetime.now().isoformat(timespec="seconds")
        self.stamp(stage).write_text(f"{ts}\n{info}\n")

    def reset(self, stage: str) -> None:
        s = self.stamp(stage)
        if s.exists():
            s.unlink()

    def run_stage(
        self,
        stage: str,
        fn: Callable[[Path], StageResult],
        *,
        resume: bool = True,
        force: bool = False,
    ) -> StageResult:
        """Run `fn(stage_dir)` unless already done (resume) and not forced."""
        if force:
            self.reset(stage)
        if resume and self.is_done(stage):
            return StageResult(
                stage=stage, status="skipped", workdir=str(self.stage_dir(stage)),
                message="already done (.done stamp present)",
            )
        result = fn(self.stage_dir(stage))
        if result.status == "done":
            self.mark_done(stage, result.message)
        return result
