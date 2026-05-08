#!/usr/bin/env python3
"""
cosmotherm_postprocess.py — aggregate COSMO-RS solubility-screen results into
a single CSV.

Reads the .tab files produced by COSMOtherm in
    molecules/<molecule>/<dft-protocol>/cosmotherm/
and writes:
    molecules/<molecule>/<dft-protocol>/cosmotherm/results.csv

Each row corresponds to one (solute, solvent_or_mixture) pair and includes
all columns COSMOtherm wrote to its .tab file (typically: log10(x_solub),
mass-fraction solubility, molar solubility, mu^p, mu^S, dG_fus, etc.).

Usage:
    scripts/cosmotherm_postprocess.py <molecule> <dft-protocol>
"""
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path


# COSMOtherm .tab format (observed):
#   Top of file: leading comment lines starting with '#' or '!'.
#   First non-comment line: column headers (whitespace-separated).
#   Subsequent non-comment lines: data rows.
# The exact header set varies by calculation (solub vs solub-screening, with
# or without iterative, etc.), so we don't hardcode column names.

_COMMENT_RE = re.compile(r'^[#!]')


def parse_tab(tab_path: Path) -> tuple[list[str], list[list[str]]]:
    """Return (headers, rows) for a COSMOtherm .tab file.
    Empty result if the file is unparseable or has no data rows."""
    if not tab_path.is_file():
        return [], []

    headers: list[str] = []
    rows: list[list[str]] = []
    with tab_path.open() as f:
        for raw in f:
            line = raw.rstrip('\n')
            stripped = line.strip()
            if not stripped:
                continue
            if _COMMENT_RE.match(stripped):
                continue
            fields = stripped.split()
            if not headers:
                # First non-comment, non-blank line — treat as header.
                headers = fields
                continue
            # Pad/trim to header width.
            if len(fields) < len(headers):
                fields = fields + [''] * (len(headers) - len(fields))
            elif len(fields) > len(headers):
                # Joined trailing tokens into the last column.
                fields = fields[:len(headers) - 1] + [' '.join(fields[len(headers) - 1:])]
            rows.append(fields)
    return headers, rows


def collect(work_dir: Path) -> list[dict[str, str]]:
    """Walk the cosmotherm/ working directory, collect rows from every .tab."""
    out: list[dict[str, str]] = []

    pure_tab = work_dir / 'pure-screen.tab'
    if pure_tab.is_file():
        hdr, rows = parse_tab(pure_tab)
        for row in rows:
            rec = dict(zip(hdr, row))
            rec['_kind'] = 'pure'
            rec['_label'] = rec.get('Compound', rec.get('comp', '?'))
            rec['_source'] = pure_tab.name
            out.append(rec)
    else:
        print(f"WARN: {pure_tab} not found", file=sys.stderr)

    for mix_tab in sorted(work_dir.glob('mix-*.tab')):
        label = mix_tab.stem.replace('mix-', '', 1)
        hdr, rows = parse_tab(mix_tab)
        for row in rows:
            rec = dict(zip(hdr, row))
            rec['_kind'] = 'mixture'
            rec['_label'] = label
            rec['_source'] = mix_tab.name
            out.append(rec)

    return out


def main() -> int:
    if len(sys.argv) < 3:
        print(f"Usage: {Path(sys.argv[0]).name} <molecule> <dft-protocol>", file=sys.stderr)
        return 2

    molecule = sys.argv[1]
    dft_protocol = sys.argv[2]

    repo_root = Path(__file__).resolve().parent.parent
    work_dir = repo_root / 'molecules' / molecule / dft_protocol / 'cosmotherm'

    if not work_dir.is_dir():
        print(f"ERROR: cosmotherm output directory not found: {work_dir}", file=sys.stderr)
        return 2

    rows = collect(work_dir)
    if not rows:
        print(f"ERROR: no parseable .tab files in {work_dir}", file=sys.stderr)
        return 1

    # Determine union of column keys (preserve _kind, _label, _source first).
    fixed_cols = ['_kind', '_label', '_source']
    other_cols: list[str] = []
    seen = set(fixed_cols)
    for rec in rows:
        for k in rec:
            if k not in seen:
                other_cols.append(k)
                seen.add(k)

    fieldnames = fixed_cols + other_cols
    out_csv = work_dir / 'results.csv'
    with out_csv.open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} rows ({len([r for r in rows if r['_kind'] == 'pure'])} pure, "
          f"{len([r for r in rows if r['_kind'] == 'mixture'])} mixture) → {out_csv}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
