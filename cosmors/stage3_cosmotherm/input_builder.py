"""Build conformer-resolved COSMOtherm inputs.

The solute is loaded as ONE compound whose conformers are the full set of
Stage-2 `.cosmo` files (AUTOC conformer treatment); gas-phase energies come from
the matching `.energy` files via the EHfile convention. Property is relative
solubility (log x_RS), matching protocols/cosmotherm-screen/*.tmpl.

  * pure-screen.inp  — all pure solvents in one `solub screening` job
  * mix-<label>.inp  — one binary-mixture job each (mole fractions from v/v)
  * solvents.list    — pure-solvent COSMObase names for f_batch
"""
from __future__ import annotations

from pathlib import Path
from typing import List

from ..config import Config
from ..solvent import ResolvedPanel


def _global_head(cfg: Config) -> List[str]:
    cdir = cfg.paths.ct_param_path or "SET_ct_param_path"
    ldir = cfg.paths.ct_license_dir or "SET_ct_license_dir"
    fdir = cfg.paths.ct_cosmo_db_path or "SET_ct_cosmo_db_path"
    return [
        f"ctd={cfg.ctd.default} CDIR={cdir} LDIR={ldir}",
        f"FDIR={fdir} nocompw wtln",
    ]


def _solute_conformer_line(conformer_cosmo: List[str], ehfile: bool = True) -> str:
    """One compound, N conformers: f="c1.cosmo" f="c2.cosmo" ... autoc [EHfile]."""
    fs = " ".join(f'f="{Path(c).name}"' for c in conformer_cosmo)
    tail = "autoc" + (" EHfile" if ehfile else "")
    return f"{fs} {tail}          # Solute (compound 1): {len(conformer_cosmo)} conformers"


def build_pure_input(cfg: Config, conformer_cosmo: List[str], panel: ResolvedPanel) -> str:
    ref = panel.reference
    tc = cfg.cosmotherm.temperature_C
    qspr = "force_qspr " if cfg.cosmotherm.force_qspr else ""
    lines = _global_head(cfg)
    lines.append(f"!! Conformer-resolved relative-solubility screen for "
                 f"{cfg.compound.name} ({len(conformer_cosmo)} conformers, pure solvents)")
    lines.append(_solute_conformer_line(conformer_cosmo))
    lines.append(f'f="{ref}_c0.cosmo" autoc       # Reference (compound 2)')
    lines.append("f_batch=solvents.list                 # Pure solvents (compounds 3+)")
    lines.append(f"tc={tc} solub screening solute=1 pure=3 {qspr}relative "
                 f"xsolout_x_log10 wsolout_gg lsolout_moll_log10")
    return "\n".join(lines) + "\n"


def build_mixture_input(cfg: Config, conformer_cosmo: List[str], mix) -> str:
    tc = cfg.cosmotherm.temperature_C
    lines = _global_head(cfg)
    lines.append(f"!! Relative solubility of {cfg.compound.name} in mixture {mix.label}")
    lines.append(_solute_conformer_line(conformer_cosmo))
    lines.append(f'f="{mix.comp1}_c0.cosmo" autoc       # Mixture component 1 (compound 2)')
    lines.append(f'f="{mix.comp2}_c0.cosmo" autoc       # Mixture component 2 (compound 3)')
    lines.append(f"tc={tc} solub xs={{0.0 {mix.x1:.5f} {mix.x2:.5f}}} relative "
                 f"xsolout_x_log10 wsolout_gg lsolout_moll_log10")
    return "\n".join(lines) + "\n"


def build_inputs(cfg: Config, conformer_cosmo: List[str], panel: ResolvedPanel,
                 out_dir: Path) -> List[str]:
    """Write all .inp files + solvents.list into out_dir; return filenames written."""
    if not conformer_cosmo:
        raise ValueError("no conformer .cosmo files — run the DFT stage first")
    out_dir = Path(out_dir)
    written: List[str] = []

    (out_dir / "solvents.list").write_text(
        "\n".join(p.cosmobase for p in panel.pures) + "\n")
    written.append("solvents.list")

    (out_dir / "pure-screen.inp").write_text(build_pure_input(cfg, conformer_cosmo, panel))
    written.append("pure-screen.inp")

    for mix in panel.mixtures:
        safe = mix.label.replace(" ", "_").replace(":", "").replace("/", "-")
        fname = f"mix-{safe}.inp"
        (out_dir / fname).write_text(build_mixture_input(cfg, conformer_cosmo, mix))
        written.append(fname)

    return written
