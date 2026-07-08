"""Stage registry.

P1 ships transparent MOCK stubs so the whole pipeline runs end-to-end in the
sandbox without any commercial binary. Each stub:

  * --dry-run : prints the real command it *would* run on the HPC; writes nothing.
  * --mock    : writes a clearly-labelled synthetic artifact and a .done stamp.

Mock artifacts are deliberately fake (filenames carry `.mock.`, contents carry a
MOCK banner). No real scientific numbers are invented for real molecules. Each
real stage replaces its stub in the phase noted in its docstring.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, List, Tuple

from .config import Config
from .models import StageResult

_MOCK_BANNER = "# MOCK ARTIFACT — synthetic placeholder, NOT a real result.\n"


def _mock_write(path: Path, payload) -> None:
    if isinstance(payload, (dict, list)):
        path.write_text(_MOCK_BANNER + json.dumps(payload, indent=2) + "\n")
    else:
        path.write_text(_MOCK_BANNER + str(payload) + "\n")


def _result(stage, stage_dir, *, dry_run, cmd, mock_files, message):
    """Shared stub body: dry-run documents the HPC command; mock writes artifacts."""
    if dry_run:
        return StageResult(stage=stage, status="dry-run", workdir=str(stage_dir),
                           message=f"would run: {cmd}")
    arts = []
    for name, payload in mock_files:
        p = Path(stage_dir) / name
        _mock_write(p, payload)
        arts.append(name)
    return StageResult(stage=stage, status="done", workdir=str(stage_dir),
                       artifacts=arts, message=message)


# --------------------------------------------------------------------------- #
# Stage stubs
# --------------------------------------------------------------------------- #
def stage_input(cfg: Config, stage_dir: Path, *, mock: bool, dry_run: bool) -> StageResult:
    """Stage 0 — input prep (SMILES/SDF/xyz/PDB/CIF -> 3D + charge). Real: P2."""
    return _result(
        "input", stage_dir, dry_run=dry_run,
        cmd=f"prepare {cfg.compound.name} -> geometry.xyz + charge.txt (RDKit/OpenBabel/PROPKA)",
        mock_files=[("input.mock.xyz", f"MOCK geometry for {cfg.compound.name}"),
                    ("charge.mock.txt", cfg.compound.charge if cfg.compound.charge is not None else 0)],
        message=f"prepared {cfg.compound.name} (mock)",
    )


def stage_md(cfg: Config, stage_dir: Path, *, mock: bool, dry_run: bool) -> StageResult:
    """Stage 4 — MD front-end: frames -> RMSD cluster -> multi-conf SDF. Real: P5."""
    if not cfg.md.enabled:
        return StageResult("md", "skipped", str(stage_dir),
                           message="md.enabled=false — COSMOconf generation will be used instead")
    return _result(
        "md", stage_dir, dry_run=dry_run,
        cmd=f"{cfg.md.engine} {cfg.md.method} @ {cfg.md.temperature_K} K, "
            f"{cfg.md.n_frames} frames -> Butina(rmsd={cfg.md.cluster_rmsd}) -> reps.sdf",
        mock_files=[("cluster_reps.mock.sdf",
                     "MOCK: 3 representative conformers from MD clustering")],
        message="MD proposed 3 conformer representatives (mock)",
    )


def stage_confgen(cfg: Config, stage_dir: Path, *, mock: bool, dry_run: bool) -> StageResult:
    """Stage 1 — ingest MD reps (generation skipped) or COSMOconf generation. Real: P2."""
    src = "ingest MD reps (COSMOconf generation skipped)" if cfg.md.enabled \
        else "COSMOconf generation (RDKit + GFN2-xTB + RMSD)"
    return _result(
        "confgen", stage_dir, dry_run=dry_run,
        cmd=src,
        mock_files=[("ensemble.mock.json",
                     {"compound": cfg.compound.name, "n_conformers": 3, "source": src})],
        message=f"ensemble built via {src} (mock)",
    )


def stage_cluster(cfg: Config, stage_dir: Path, *, mock: bool, dry_run: bool) -> StageResult:
    """RMSD clustering gate — MANDATORY before any DFT. Real: P2."""
    return _result(
        "cluster", stage_dir, dry_run=dry_run,
        cmd=f"Butina RMSD clustering (cutoff={cfg.conformers.rmsd_cutoff} A, "
            f"energy_window={cfg.conformers.energy_window} kcal/mol, "
            f"max={cfg.conformers.max_conformers}) BEFORE DFT",
        mock_files=[("clusters.mock.json",
                     {"in": 3, "kept": 2, "dropped_near_identical": 1,
                      "rmsd_cutoff": cfg.conformers.rmsd_cutoff})],
        message="RMSD gate: 3 in -> 2 unique kept (mock)",
    )


def stage_dft(cfg: Config, stage_dir: Path, *, mock: bool, dry_run: bool) -> StageResult:
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


def stage_cosmotherm(cfg: Config, stage_dir: Path, *, mock: bool, dry_run: bool) -> StageResult:
    """Stage 3 — COSMOtherm relative solubility, AUTOC conformers. Real: P3."""
    out = (
        "MOCK COSMOtherm output — relative solubility (log x_RS).\n"
        "Numbers below are placeholders, not a real result.\n"
        f"ctd={cfg.ctd.default}  T={cfg.cosmotherm.temperature_C}C\n"
        "solvent        log10(x_RS)\n"
        "water          -9.99  (MOCK)\n"
        "ethanol        -9.99  (MOCK)\n"
    )
    return _result(
        "cosmotherm", stage_dir, dry_run=dry_run,
        cmd=f"{cfg.paths.cosmotherm_bin} <input>  (AUTOC folder-of-.cosmo, "
            f"relative solub, force_qspr={cfg.cosmotherm.force_qspr})",
        mock_files=[("cosmotherm.mock.out", out)],
        message="relative-solubility screen written (mock)",
    )


def stage_sensitivity(cfg: Config, stage_dir: Path, *, mock: bool, dry_run: bool) -> StageResult:
    """Sensitivity report — parse per-phase weights -> decision gate. Real: P3."""
    verdict = {
        "is_mock": True,
        "single_conformer_sufficient": None,
        "dominant_flips": None,
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
    ("input", stage_input),
    ("md", stage_md),
    ("confgen", stage_confgen),
    ("cluster", stage_cluster),
    ("dft", stage_dft),
    ("cosmotherm", stage_cosmotherm),
    ("sensitivity", stage_sensitivity),
]

STAGES = dict(PIPELINE)
