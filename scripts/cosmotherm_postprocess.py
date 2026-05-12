#!/usr/bin/env python3
"""
cosmotherm_postprocess.py — aggregate COSMOtherm solubility-screen results
into a clean CSV (one row per solute × solvent/mixture combination).

COSMOtherm .tab files have a multi-block structure, with one "Property job N"
block per solvent in screening mode. Each block:

    Property job N : Solubility Solvent Screening for solute X ;
    Settings job N : T= 298.15 K ;
    Units job N    : Energies in kJ/mol ; ...
    General job N  : DG_fus(solute) = ... ;
    Nr  Solvent  log10(x_solub)  mu(self)  mu(solv)  w_fract  log10(S)  Solvent_density  Solvent_MolWeight
    1   h2o      0.00000000      -331.465... ...

This parser scans for the "Nr  Solvent  ..." header line, then reads the
next non-metadata line as the data row. Result: one tidy row per solvent
(or per mixture, for mix-*.tab files).

Usage:
    scripts/cosmotherm_postprocess.py <molecule> <dft-protocol>

Output:
    molecules/<molecule>/<dft-protocol>/cosmotherm/results.csv
"""
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path


# COSMOtherm block markers
HEADER_PATTERN = re.compile(r'^\s*Nr\s+Solvent\b', re.IGNORECASE)
METADATA_PREFIXES = ('Property', 'Settings', 'Units', 'General', 'Nr', '!', '#')


def parse_tab(tab_path: Path) -> list[dict]:
    """Return list of {column: value} dicts, one per Nr/data block in the tab."""
    if not tab_path.is_file():
        return []

    with tab_path.open() as f:
        lines = [l.rstrip('\n') for l in f]

    rows: list[dict] = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if HEADER_PATTERN.match(line):
            headers = line.split()
            # Find next non-blank, non-metadata line — that's the data row.
            j = i + 1
            while j < len(lines):
                cand = lines[j].strip()
                if not cand:
                    j += 1
                    continue
                if cand.startswith(METADATA_PREFIXES):
                    j += 1
                    continue
                # Found the data row.
                fields = cand.split()
                if len(fields) >= 2:
                    record: dict[str, str] = {}
                    for k, v in zip(headers, fields):
                        record[k] = v
                    rows.append(record)
                break
            i = j + 1
        else:
            i += 1

    return rows


def collect(work_dir: Path) -> list[dict]:
    """Walk cosmotherm/ dir, parse pure-screen.tab and all mix-*.tab files."""
    out: list[dict] = []

    pure_tab = work_dir / 'pure-screen.tab'
    if pure_tab.is_file():
        for r in parse_tab(pure_tab):
            r['_kind'] = 'pure'
            r['_label'] = r.get('Solvent', '?')
            r['_source'] = pure_tab.name
            out.append(r)
    else:
        print(f"WARN: {pure_tab} not found", file=sys.stderr)

    for mix_tab in sorted(work_dir.glob('mix-*.tab')):
        label = mix_tab.stem.replace('mix-', '', 1)
        rows = parse_tab(mix_tab)
        if not rows:
            print(f"WARN: no data parsed from {mix_tab.name}", file=sys.stderr)
            continue
        for r in rows:
            r['_kind'] = 'mixture'
            r['_label'] = label
            r['_source'] = mix_tab.name
            out.append(r)

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
        print(f"ERROR: cosmotherm output dir not found: {work_dir}", file=sys.stderr)
        return 2

    rows = collect(work_dir)
    if not rows:
        print(f"ERROR: no data rows extracted from any .tab file in {work_dir}", file=sys.stderr)
        return 1

    # Preserve column order: meta cols first, then column-headers in order seen
    fixed_cols = ['_kind', '_label', '_source']
    other_cols: list[str] = []
    seen = set(fixed_cols)
    for r in rows:
        for k in r:
            if k not in seen:
                other_cols.append(k)
                seen.add(k)

    fieldnames = fixed_cols + other_cols
    out_csv = work_dir / 'results.csv'
    with out_csv.open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)

    n_pure = sum(1 for r in rows if r['_kind'] == 'pure')
    n_mix = sum(1 for r in rows if r['_kind'] == 'mixture')
    print(f"Wrote {len(rows)} rows ({n_pure} pure, {n_mix} mixture) -> {out_csv}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
