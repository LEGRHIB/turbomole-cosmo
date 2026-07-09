"""RMSD clustering gate — MANDATORY before any DFT.

Re-optimising near-identical geometries is the dominant cost sink, so this gate
collapses conformers within an RMSD cutoff (RDKit Butina) and keeps one
representative per cluster BEFORE anything expensive runs. Enforced in code: the
DFT stage consumes only the kept set.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .config import Config
from .models import StageResult
from . import rdkit_utils as ru


def rmsd_cluster(
    mols: List,
    cutoff: float,
    energies: Optional[List[float]] = None,
    energy_window: Optional[float] = None,
    max_conformers: Optional[int] = None,
) -> Tuple[List[int], dict]:
    """Cluster conformers by pairwise best-RMS; return (kept_indices, report).

    * optional energy-window pre-filter (kcal/mol above the minimum),
    * Butina clustering at `cutoff` (Angstrom),
    * one representative per cluster (lowest energy, else the Butina centroid),
    * optional hard cap `max_conformers` (keep the lowest-energy / largest clusters).
    """
    from rdkit.ML.Cluster import Butina

    if cutoff <= 0:
        raise ValueError("rmsd cutoff must be > 0 — the clustering gate is mandatory")

    n_in = len(mols)
    idx = list(range(n_in))

    # 1) energy-window pre-filter
    if energies is not None and energy_window is not None and n_in:
        emin = min(energies)
        idx = [i for i in idx if (energies[i] - emin) <= energy_window]

    if len(idx) <= 1:
        kept = idx[:]
        return kept, {
            "n_in": n_in, "n_after_energy_window": len(idx), "n_clusters": len(kept),
            "n_kept": len(kept), "n_dropped": n_in - len(kept), "rmsd_cutoff": cutoff,
        }

    # 2) pairwise best-RMS distance matrix (lower triangle, Butina format)
    dists: List[float] = []
    for a in range(1, len(idx)):
        for b in range(a):
            dists.append(ru.best_rms(mols[idx[a]], mols[idx[b]]))

    clusters = Butina.ClusterData(dists, len(idx), cutoff, isDistData=True)

    # 3) one representative per cluster
    kept: List[int] = []
    cluster_sizes: List[int] = []
    for cluster in clusters:
        members = [idx[c] for c in cluster]
        cluster_sizes.append(len(members))
        if energies is not None:
            rep = min(members, key=lambda i: energies[i])
        else:
            rep = members[0]           # Butina centroid
        kept.append(rep)

    # 4) optional hard cap
    if max_conformers is not None and len(kept) > max_conformers:
        if energies is not None:
            kept = sorted(kept, key=lambda i: energies[i])[:max_conformers]
        else:
            kept = kept[:max_conformers]

    kept.sort()
    report = {
        "n_in": n_in,
        "n_after_energy_window": len(idx),
        "n_clusters": len(clusters),
        "n_kept": len(kept),
        "n_dropped": n_in - len(kept),
        "rmsd_cutoff": cutoff,
        "cluster_sizes": cluster_sizes,
    }
    return kept, report


def _read_energies(mols) -> Optional[List[float]]:
    """Pull a per-conformer energy from an SDF 'energy' property if present."""
    out = []
    for m in mols:
        if m.HasProp("energy"):
            try:
                out.append(float(m.GetProp("energy")))
                continue
            except ValueError:
                pass
        return None
    return out


def run(cfg: Config, stage_dir: Path, *, wd, mock: bool, dry_run: bool) -> StageResult:
    """Stage wrapper: read confgen/ensemble.sdf -> cluster -> kept.sdf + clusters.json."""
    stage = "cluster"
    ens_sdf = wd.path("confgen") / "ensemble.sdf"
    if dry_run:
        return StageResult(stage, "dry-run", str(stage_dir),
                           message=f"Butina RMSD clustering of {ens_sdf} "
                                   f"(cutoff={cfg.conformers.rmsd_cutoff} A) BEFORE DFT")

    if not ens_sdf.exists():
        return StageResult(stage, "error", str(stage_dir),
                           message=f"missing ensemble: {ens_sdf} (run confgen first)")

    mols = ru.read_conformers(str(ens_sdf))
    energies = _read_energies(mols)
    kept_idx, report = rmsd_cluster(
        mols, cutoff=cfg.conformers.rmsd_cutoff,
        energies=energies, energy_window=cfg.conformers.energy_window,
        max_conformers=cfg.conformers.max_conformers,
    )
    kept_mols = [mols[i] for i in kept_idx]
    kept_path = Path(stage_dir) / "kept.sdf"
    ru.write_sdf(str(kept_path), kept_mols)
    (Path(stage_dir) / "clusters.json").write_text(json.dumps(report, indent=2) + "\n")

    return StageResult(
        stage, "done", str(stage_dir), artifacts=["kept.sdf", "clusters.json"],
        message=f"RMSD gate: {report['n_in']} in -> {report['n_kept']} kept "
                f"({report['n_dropped']} near-identical dropped)",
    )
