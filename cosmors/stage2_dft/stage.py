"""Stage 2 driver — COSMOconf-orchestrated / self-contained TURBOMOLE DFT+COSMO.

Reads the RMSD-gated conformers (cluster/kept.sdf), runs the DFT/COSMO cascade, and
emits one .cosmo/.energy per conformer at epsilon = infinity for Stage 3.

Two backends (config `dft.backend`):
  cosmoconf  — COSMOconf orchestrates the cascade + clustering (HPC; command documented,
               verify against your COSMOconf version).
  turbomole  — self-contained per-conformer x2t -> define -> cosmoprep -> ridft, using the
               generated inputs in control.py. No legacy scripts, no turbomoleio/pymatgen.

Sandbox: --dry-run documents the commands; --mock writes labelled synthetic .cosmo (still
epsilon = infinity so the ideal-conductor gate is exercised). Real binaries run on the HPC.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from ..config import Config
from ..models import StageResult
from .. import rdkit_utils as ru
from . import control
from .cosmo_check import assert_ideal_conductor

_MOCK = "# MOCK .cosmo — synthetic, not a real COSMO surface.\n"


def _read_charge(cfg: Config, wd) -> int:
    ct = wd.path("input") / "charge.txt"
    if ct.exists():
        try:
            return int(ct.read_text().split()[0])
        except (ValueError, IndexError):
            pass
    return int(cfg.compound.charge) if cfg.compound.charge is not None else 0


def _mock_cosmo(path: Path) -> None:
    path.write_text(
        "$cosmo\n  epsilon=infinity\n" + _MOCK +
        "$segment_information\n"
        "  1 1 0.0 0.0 0.0 -0.0010 0.20 -0.0050 0.001\n"
        "  2 1 0.1 0.0 0.0  0.0010 0.20  0.0050 0.001\n"
        "$end\n"
    )


def _cosmoconf_cmd(cfg: Config) -> str:
    return (f"{cfg.paths.cosmoconf_bin} <procedure for {cfg.ctd.default}> -i kept.sdf "
            f"# orchestrates opt+cluster -> {cfg.theory.functional}/{cfg.theory.basis} "
            f"{cfg.theory.cavity} single point (eps=inf); VERIFY against your COSMOconf")


def _real_conformer_turbomole(cfg: Config, d: Path, base: str, charge: int) -> Path:
    """HPC path: x2t -> define -> cosmoprep -> ridft for one conformer."""
    cosmo = f"{base}.cosmo"
    (d / "define.in").write_text(control.define_input(cfg, charge))
    (d / "cosmoprep.in").write_text(control.cosmoprep_input(cfg, cosmo))
    with open(d / "coord", "w") as fh:
        subprocess.run(["x2t", f"{base}.xyz"], cwd=d, stdout=fh, check=True)
    for tool in ("define", "cosmoprep"):
        with open(d / f"{tool}.in") as inp, open(d / f"{tool}.log", "w") as log:
            subprocess.run([tool], cwd=d, stdin=inp, stdout=log, stderr=subprocess.STDOUT, check=True)
    with open(d / "ridft.out", "w") as log:
        subprocess.run(["ridft"], cwd=d, stdout=log, stderr=subprocess.STDOUT, check=True)
    return d / cosmo


def run(cfg: Config, stage_dir: Path, *, wd, mock: bool, dry_run: bool) -> StageResult:
    stage = "dft"
    kept = wd.path("cluster") / "kept.sdf"
    backend = cfg.dft.backend
    d = Path(stage_dir)

    if dry_run:
        cmd = _cosmoconf_cmd(cfg) if backend == "cosmoconf" \
            else "; ".join(control.turbomole_commands(cfg, "conf01.xyz", "conf01.cosmo"))
        return StageResult(stage, "dry-run", str(d), message=f"[{backend}] {cmd}")

    if not kept.exists():
        return StageResult(stage, "error", str(d), message=f"missing {kept} (run cluster first)")

    mols = ru.read_conformers(str(kept))
    charge = _read_charge(cfg, wd)

    # the generated TURBOMOLE inputs — written for inspection and for the HPC run
    (d / "define.in").write_text(control.define_input(cfg, charge))
    (d / "cosmoprep.in").write_text(control.cosmoprep_input(cfg, "conf01.cosmo"))
    arts = ["define.in", "cosmoprep.in"]

    have_tm = bool(shutil.which("define") and shutil.which("cosmoprep") and shutil.which("ridft"))
    for i, m in enumerate(mols, 1):
        base = f"conf{i:02d}"
        ru.write_xyz(str(d / f"{base}.xyz"), m, comment=f"{cfg.compound.name} {base} charge={charge}")
        cosmo = d / f"{base}.cosmo"
        energy = d / f"{base}.energy"

        if mock or not have_tm:
            _mock_cosmo(cosmo)
            energy.write_text("$energy\n# MOCK gas-phase energy\n$end\n")
        elif backend == "turbomole":
            _real_conformer_turbomole(cfg, d, base, charge)
        else:
            raise RuntimeError("cosmoconf orchestration runs on the HPC — validate the "
                               "cosmoconf invocation there, or set dft.backend: turbomole")

        assert_ideal_conductor(str(cosmo))          # ε = ∞ hard gate
        arts += [f"{base}.xyz", cosmo.name, energy.name]

    tag = " (mock)" if (mock or not have_tm) else ""
    return StageResult(stage, "done", str(d), artifacts=arts,
                       message=f"{len(mols)} conformer .cosmo at eps=infinity via {backend}{tag}")
