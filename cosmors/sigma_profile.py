"""Plot COSMO sigma-profiles from .cosmo files, comparable across molecule sizes.

A sigma-profile p(sigma) is the surface area of a molecule binned by screening
charge density sigma. Its integral equals the total molecular surface area, so a
big solute (lysozyme, ~100x the surface of a solvent) dwarfs small solvents on a
raw plot. To compare *shapes*, normalise each profile.

Modes:
  normalized  (default) each profile scaled so its bins sum to 1 -> compare shapes
  raw                   area-weighted p(sigma) [A^2] (what COSMOtherm plots)
  peratom               p(sigma) divided by atom count -> size-intensive
  dual                  raw, but the largest-surface molecule on a second y-axis

Reads the TURBOMOLE `$segment_information` block:
  n  atom  X Y Z  charge  area[A^2]  charge/area[e/A^2]  potential
i.e. area = column 7, sigma = column 8 (1-indexed). Adjust _AREA_COL/_SIGMA_COL
if your .cosmo differs (the header comment in the file shows the columns).

Usage:
  python -m cosmors.sigma_profile lysozyme.cosmo h2o_c0.cosmo ethanol_c0.cosmo \
      --mode normalized -o sigma.png
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np

_AREA_COL = 6    # 0-indexed: area  (A^2)
_SIGMA_COL = 7   # 0-indexed: charge/area (e/A^2)


def parse_cosmo(path: str) -> Tuple[np.ndarray, np.ndarray, int]:
    """Return (sigma[e/A^2], area[A^2], n_atoms) from a .cosmo segment block."""
    sig: List[float] = []
    area: List[float] = []
    atoms = set()
    in_seg = False
    with open(path) as fh:
        for line in fh:
            s = line.strip()
            if s.startswith("$segment_information"):
                in_seg = True
                continue
            if in_seg:
                if s.startswith("$"):
                    break
                if not s or s.startswith("#"):
                    continue
                p = s.split()
                if len(p) <= _SIGMA_COL:
                    continue
                try:
                    atoms.add(int(float(p[1])))
                    area.append(float(p[_AREA_COL]))
                    sig.append(float(p[_SIGMA_COL]))
                except ValueError:
                    continue
    if not sig:
        raise ValueError(f"no $segment_information parsed from {path}")
    return np.asarray(sig), np.asarray(area), len(atoms)


def sigma_profile(sigma, area, bins=61, srange=(-0.03, 0.03)):
    hist, edges = np.histogram(sigma, bins=bins, range=srange, weights=area)
    centers = 0.5 * (edges[:-1] + edges[1:])
    return centers, hist


def _load(files, bins, srange):
    out = []
    for f in files:
        sg, ar, nat = parse_cosmo(f)
        c, h = sigma_profile(sg, ar, bins, srange)
        out.append({"centers": c, "hist": h, "area": float(ar.sum()), "natoms": nat})
        print(f"  {Path(f).name}: {len(sg)} segments, "
              f"surface {ar.sum():.1f} A^2, {nat} atoms, "
              f"sigma [{sg.min():+.3f},{sg.max():+.3f}]", file=sys.stderr)
    return out


def _parse_scale(items):
    d = {}
    for it in items or []:
        if "=" in it:
            k, v = it.split("=", 1)
            try:
                d[k.strip().lower()] = float(v)
            except ValueError:
                pass
    return d


def _factor_for(label, scale):
    ll = label.lower()
    for k, f in (scale or {}).items():
        if k in ll:
            return f
    return None


def _smooth(y, sigma_bins):
    """Gaussian-smooth a binned profile; sigma_bins is the kernel width in bins."""
    if not sigma_bins or sigma_bins <= 0:
        return y
    r = int(max(1, round(3 * sigma_bins)))
    x = np.arange(-r, r + 1)
    k = np.exp(-0.5 * (x / sigma_bins) ** 2)
    k /= k.sum()
    return np.convolve(y, k, mode="same")


def make_plot(files: List[str], labels: Optional[List[str]] = None,
              mode: str = "normalized", ymax: Optional[float] = None,
              bins: int = 61, srange=(-0.03, 0.03), out: str = "sigma_profiles.png",
              scale: Optional[dict] = None, smooth: Optional[float] = None):
    scale = scale or {}
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    labels = labels or [Path(f).stem for f in files]
    data = _load(files, bins, srange)

    fig, ax = plt.subplots(figsize=(8, 5))
    ylabel = {"normalized": r"normalized $p(\sigma)$  ($\int=1$)",
              "raw": r"$p(\sigma)$  [$\mathrm{\AA}^2$]",
              "peratom": r"$p(\sigma)$ per atom  [$\mathrm{\AA}^2$]"}.get(mode, "p(sigma)")

    if mode == "dual":
        big = max(range(len(data)), key=lambda i: data[i]["area"])
        ax2 = ax.twinx()
        for i, (d, lab) in enumerate(zip(data, labels)):
            target = ax2 if i == big else ax
            y = d["hist"]
            f = _factor_for(lab, scale)
            if f:
                y = y / f
                lab = f"{lab} /{f:g}"
            y = _smooth(y, smooth)
            target.plot(d["centers"], y, label=lab, lw=2 if i == big else 1.2)
        ax.set_ylabel(r"$p(\sigma)$ solvents [$\mathrm{\AA}^2$]")
        ax2.set_ylabel(f"$p(\\sigma)$ {labels[big]} [$\\mathrm{{\\AA}}^2$]")
        h1, l1 = ax.get_legend_handles_labels()
        h2, l2 = ax2.get_legend_handles_labels()
        ax.legend(h1 + h2, l1 + l2, fontsize=8, loc="upper right")
    else:
        for d, lab in zip(data, labels):
            if mode == "normalized":
                y = d["hist"] / d["hist"].sum()
            elif mode == "peratom":
                y = d["hist"] / max(d["natoms"], 1)
            else:
                y = d["hist"]
            f = _factor_for(lab, scale)
            if f:
                y = y / f
                lab = f"{lab} /{f:g}"
            y = _smooth(y, smooth)
            ax.plot(d["centers"], y, label=lab, lw=1.4)
        ax.set_ylabel(ylabel)
        if ymax is not None:
            ax.set_ylim(0, ymax)
        ax.legend(fontsize=8, loc="upper right")

    ax.set_xlabel(r"$\sigma$  [$e/\mathrm{\AA}^2$]")
    ax.set_title(f"COSMO $\\sigma$-profiles ({mode})")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    print(f"wrote {out}")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Plot COSMO sigma-profiles from .cosmo files")
    ap.add_argument("files", nargs="+", help=".cosmo files")
    ap.add_argument("--mode", choices=["normalized", "raw", "peratom", "dual"],
                    default="normalized")
    ap.add_argument("--ymax", type=float, help="cap the y-axis (raw/peratom modes)")
    ap.add_argument("--bins", type=int, default=61)
    ap.add_argument("--smin", type=float, default=-0.03)
    ap.add_argument("--smax", type=float, default=0.03)
    ap.add_argument("--labels", nargs="+", help="legend labels (default: filenames)")
    ap.add_argument("--scale", nargs="*", metavar="NAME=FACTOR",
                    help="divide matching profiles by a factor, e.g. --scale lysozyme=3")
    ap.add_argument("--smooth", nargs="?", type=float, const=1.5, default=None,
                    metavar="WIDTH",
                    help="Gaussian-smooth the profiles (kernel width in bins; bare flag = 1.5)")
    ap.add_argument("-o", "--out", default="sigma_profiles.png")
    a = ap.parse_args(argv)
    make_plot(a.files, a.labels, a.mode, a.ymax, a.bins, (a.smin, a.smax), a.out,
              scale=_parse_scale(a.scale), smooth=a.smooth)
    return 0


if __name__ == "__main__":
    sys.exit(main())
