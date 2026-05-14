#!/usr/bin/env python3
"""
cosmotherm_postprocess.py — aggregate COSMOtherm solubility-screen results
into clean output files matching the COSMOtherm GUI's "Solubility Solvent
Screening" Excel layout.

Inputs (in molecules/<mol>/<dft-protocol>/cosmotherm/):
    pure-screen.tab         — pure-solvent screening (RS-flavor columns)
    mix-<label>.tab         — binary mixture solubility (regular Solubility)

Outputs (same dir):
    <mol>-pure-screening.xlsx   — GUI-matching layout (metadata header rows +
                                  table sorted ascending by log10(x_RS))
    <mol>-mixtures.xlsx         — one row per (mixture, component), all parsed
                                  columns, diverged-iteration flag
    results.csv                 — combined long-form CSV for downstream use

Parsing details:
    - Header-position-aware fixed-width slicing. The COSMOtherm .tab files
      have right-aligned numeric columns with blank cells where a value is
      missing (e.g. water's w_fract in self-row). Naive whitespace.split()
      collapses those blanks and shifts every following column left by one.
      We slice each data line by the column-start positions of the header,
      so empty cells stay empty.

    - Handles both pure ("Nr Solvent ...") and mix ("Nr Compound ...") header
      schemas. Mix files include the solute self-row (compound 1 = molecule
      itself); we tag those with role="solute" rather than dropping, so the
      audit trail is preserved.

    - Bracketed values like [0.99999] flag a diverged iterative-solver result.
      Brackets are stripped from the value and a per-row _diverged flag is set
      to True. Both diverged and converged rows are kept (the same compound
      may appear twice in a mix block — the diverged attempt and the reset).

    - Mixture composition is read from the Settings line (e.g. "x(3)= 0.5000
      x(4)= 0.5000") and attached to each component row as _x_in_mix, so the
      output records what concentration each compound was assigned.

Usage:
    scripts/cosmotherm_postprocess.py <molecule> <dft-protocol>

Example:
    scripts/cosmotherm_postprocess.py vancomycin BP-TZVPD-FINE
"""
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

try:
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment, PatternFill
    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False


HEADER_RE = re.compile(r'^\s*Nr\s+(Solvent|Compound)\b', re.IGNORECASE)
METADATA_KEYS = ('Property', 'Settings', 'Units', 'General')
COMMENT_PREFIXES = ('#', '!')


# ---------------------------------------------------------------------------
# Low-level parsing helpers
# ---------------------------------------------------------------------------

def find_header_positions(header_line: str) -> list[tuple[str, int, int]]:
    """Return [(column_name, start, end), ...] from a .tab header line.

    Each header word is a non-space run; start is the index of its first
    char, end is one past the last char (Python-slice convention).
    """
    positions: list[tuple[str, int, int]] = []
    i = 0
    n = len(header_line)
    while i < n:
        if header_line[i] != ' ':
            j = i
            while j < n and header_line[j] != ' ':
                j += 1
            positions.append((header_line[i:j], i, j))
            i = j
        else:
            i += 1
    return positions


def slice_by_positions(line: str, positions: list[tuple[str, int, int]]) -> dict[str, str]:
    """Map data tokens to header columns by right-edge alignment.

    COSMOtherm formats values either right-aligned (numeric) ending at the
    header word's right edge, or left-aligned (text) starting at the
    header word's left edge. Cleanest unified rule: tokenize the data row
    into non-whitespace runs, then assign each token to the column whose
    header word's right edge is closest to the token's right edge.

    This handles:
    - Long solvent names that exceed the header word's width (matched by
      proximity, not by static slicing).
    - Bracketed values like [0.99999] that are wider than the column slot
      (the brackets push the left edge into the previous slot, but the
      right edge still aligns).
    - Missing values (no token's right-edge near the column's right-edge,
      so the column stays empty).

    Edge case: text values may not be right-aligned with the header. For
    those (Solvent, Compound, Exp-State), the LEFT edge of the token is
    typically at the LEFT edge of the header word. The right-edge rule
    still picks the right column in practice because the next column's
    header is far enough away that the text token isn't closer to it.
    """
    out: dict[str, str] = {name: '' for name, _, _ in positions}

    # Tokenize: find non-whitespace runs as (text, start, end)
    tokens: list[tuple[str, int, int]] = []
    n = len(line)
    i = 0
    while i < n:
        if not line[i].isspace():
            j = i
            while j < n and not line[j].isspace():
                j += 1
            tokens.append((line[i:j], i, j))
            i = j
        else:
            i += 1

    # For each token, find the column with the closest header word right-edge.
    for tok, tstart, tend in tokens:
        best_k = None
        best_dist = float('inf')
        for k, (_, cstart, cend) in enumerate(positions):
            # Match by right-edge for right-aligned values; for left-aligned
            # text (Solvent/Compound), the token's LEFT edge is at the column
            # header's left edge — so also consider |tstart - cstart|. Take
            # the smaller of the two distances.
            d_right = abs(tend - cend)
            d_left = abs(tstart - cstart)
            d = min(d_right, d_left)
            if d < best_dist:
                best_dist = d
                best_k = k
        if best_k is not None:
            name = positions[best_k][0]
            existing = out[name]
            # Concatenate if multiple tokens map to the same column (rare;
            # would only happen if a single column's value has whitespace,
            # which COSMOtherm doesn't produce).
            out[name] = (existing + ' ' + tok).strip() if existing else tok

    return out


def parse_value(v: str) -> tuple[str, bool]:
    """Strip [brackets] and return (clean_value, is_diverged)."""
    if not v:
        return '', False
    s = v.strip()
    if s.startswith('[') and s.endswith(']'):
        return s[1:-1].strip(), True
    return s, False


def parse_metadata(lines: list[str], start: int = 0) -> tuple[dict[str, str], int]:
    """Read Property/Settings/Units/General lines until the header line.

    Returns (metadata_dict, header_line_index). If no header is found,
    header_line_index == len(lines).
    """
    meta: dict[str, str] = {}
    i = start
    while i < len(lines):
        line = lines[i]
        if HEADER_RE.match(line):
            return meta, i
        s = line.strip()
        for key in METADATA_KEYS:
            if s.startswith(key):
                # Drop the leading "Key job N :" prefix to keep just the body.
                if ':' in s:
                    body = s.split(':', 1)[1].strip()
                    body = body.rstrip(';').strip()
                    meta[key.lower()] = body
                break
        i += 1
    return meta, i


def is_data_row(line: str) -> bool:
    """True if line looks like a Nr<num> data row (not metadata/header/comment)."""
    s = line.strip()
    if not s:
        return False
    if s.startswith(COMMENT_PREFIXES):
        return False
    if any(s.startswith(k) for k in METADATA_KEYS):
        return False
    if HEADER_RE.match(line):
        return False
    # First token must be a number (the Nr)
    first = s.split(None, 1)[0]
    return first.isdigit()


# ---------------------------------------------------------------------------
# Tab-file parsers
# ---------------------------------------------------------------------------

def parse_pure_tab(tab_path: Path) -> tuple[dict[str, str], list[dict]]:
    """Parse pure-screen.tab. Returns (metadata_of_first_block, rows).

    pure-screen.tab from `solub screening` mode has one block per solvent
    (each block has its own metadata + header + single data row), OR one
    block with all solvents (depending on COSMOtherm version). We handle
    both: every header we see is re-parsed and every data row is collected.
    """
    with tab_path.open() as f:
        lines = [l.rstrip('\n') for l in f]

    first_meta: dict[str, str] = {}
    rows: list[dict] = []

    i = 0
    while i < len(lines):
        # Look for the next metadata/header section
        meta, hdr_idx = parse_metadata(lines, i)
        if hdr_idx >= len(lines):
            break
        if not first_meta and meta:
            first_meta = meta
        header_line = lines[hdr_idx]
        positions = find_header_positions(header_line)

        # Read data rows until next header or EOF
        j = hdr_idx + 1
        while j < len(lines):
            line = lines[j]
            if HEADER_RE.match(line):
                break
            # If we hit a Property/Settings line, it's a new block — stop here
            # so the outer loop re-enters parse_metadata.
            s = line.strip()
            if any(s.startswith(k) for k in METADATA_KEYS):
                break
            if is_data_row(line):
                sliced = slice_by_positions(line, positions)
                row: dict[str, str | bool] = {}
                diverged = False
                for col, raw in sliced.items():
                    val, d = parse_value(raw)
                    row[col] = val
                    diverged = diverged or d
                row['_diverged'] = diverged
                rows.append(row)
            j += 1
        i = j

    return first_meta, rows


def parse_mix_tab(
    tab_path: Path, mix_label: str, molecule: str
) -> tuple[dict[str, str], dict[int, float], list[dict]]:
    """Parse mix-<label>.tab. Returns (metadata, composition, rows).

    composition: {compound_nr: mole_fraction} from "x(i)= V" in Settings.
    rows: every compound row in the mix block. The solute self-row
          (Compound == molecule) is tagged _role='solute' but kept.
    """
    with tab_path.open() as f:
        lines = [l.rstrip('\n') for l in f]

    metadata, hdr_idx = parse_metadata(lines, 0)

    # Pull x(i)= V pairs from the Settings line
    composition: dict[int, float] = {}
    settings = metadata.get('settings', '')
    for m in re.finditer(r'x\((\d+)\)\s*=\s*([\d.eE+-]+)', settings):
        try:
            composition[int(m.group(1))] = float(m.group(2))
        except ValueError:
            pass

    rows: list[dict] = []
    if hdr_idx >= len(lines):
        return metadata, composition, rows

    header_line = lines[hdr_idx]
    positions = find_header_positions(header_line)
    # has_compound_col is informational only; we resolve the role per-row by
    # comparing the Compound column to the molecule name below.
    _ = any(name == 'Compound' for name, _, _ in positions)

    j = hdr_idx + 1
    while j < len(lines):
        line = lines[j]
        if HEADER_RE.match(line):
            j += 1
            continue
        s = line.strip()
        if not s:
            j += 1
            continue
        if any(s.startswith(k) for k in METADATA_KEYS):
            j += 1
            continue
        if not is_data_row(line):
            j += 1
            continue

        sliced = slice_by_positions(line, positions)
        row: dict = {}
        diverged = False
        for col, raw in sliced.items():
            val, d = parse_value(raw)
            row[col] = val
            diverged = diverged or d
        row['_diverged'] = diverged

        nr_str = row.get('Nr', '').strip()
        nr = int(nr_str) if nr_str.isdigit() else None
        row['_nr'] = nr
        row['_x_in_mix'] = composition.get(nr) if nr is not None else None

        # Tag solute self-row vs solvent rows by the Compound column
        compound_name = (row.get('Compound') or row.get('Solvent') or '').strip()
        if compound_name == molecule:
            row['_role'] = 'solute'
        else:
            row['_role'] = 'solvent'
        row['_compound'] = compound_name

        rows.append(row)
        j += 1

    return metadata, composition, rows


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------

def _to_number_or_text(v):
    """Best-effort: return float if v looks numeric, else string."""
    if v is None or v == '':
        return None
    if isinstance(v, (int, float, bool)):
        return v
    try:
        return float(v)
    except (ValueError, TypeError):
        return v


def write_pure_xlsx(out_path: Path, metadata: dict, rows: list[dict], molecule: str) -> bool:
    """Emit an xlsx mirroring the GUI Solvent Screening Excel layout."""
    if not HAS_OPENPYXL:
        return False

    wb = Workbook()
    ws = wb.active
    ws.title = "Pure screening"

    bold = Font(bold=True)
    grey = PatternFill("solid", fgColor="EEEEEE")

    # Header metadata block (rows 1-4)
    job_lines = [
        f"Property job 1 : {metadata.get('property', '')} ;",
        f"Settings job 1 : {metadata.get('settings', '')} ;",
        f"Units    job 1 : {metadata.get('units', '')} ;",
        f"General  job 1 : {metadata.get('general', '')} ;",
    ]
    for r, txt in enumerate(job_lines, 1):
        c = ws.cell(row=r, column=1, value=txt)
        c.font = bold if r == 1 else Font(italic=True)
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=8)

    if not rows:
        wb.save(out_path)
        return True

    # Column order: take the header columns in their original order, drop
    # internal underscore-prefixed cols.
    cols = [c for c in rows[0].keys() if not c.startswith('_')]

    # Sort by log10(x_RS) ascending (least soluble first), as GUI does.
    sort_col = next((c for c in cols if 'log10(x_RS)' in c or ('x_RS' in c and 'log10' in c)), None)
    if sort_col is None:
        # Fallback: any column starting with log10(x
        sort_col = next((c for c in cols if c.startswith('log10(x')), None)
    if sort_col:
        def keyfn(r):
            try:
                return float(r.get(sort_col, ''))
            except (ValueError, TypeError):
                return float('inf')
        rows_sorted = sorted(rows, key=keyfn)
    else:
        rows_sorted = rows

    # Append a "diverged?" column for transparency
    cols_out = cols + (['diverged'] if any(r.get('_diverged') for r in rows_sorted) else [])

    # Table header at row 6
    header_row = 6
    for ci, col in enumerate(cols_out, 1):
        c = ws.cell(row=header_row, column=ci, value=col)
        c.font = bold
        c.fill = grey

    # Data rows
    for ri, row in enumerate(rows_sorted, header_row + 1):
        for ci, col in enumerate(cols_out, 1):
            if col == 'diverged':
                v = bool(row.get('_diverged'))
                ws.cell(row=ri, column=ci, value=v)
            else:
                ws.cell(row=ri, column=ci, value=_to_number_or_text(row.get(col, '')))

    # Column widths
    for ci, col in enumerate(cols_out, 1):
        ws.column_dimensions[chr(ord('A') + ci - 1)].width = max(len(col) + 2, 14)

    wb.save(out_path)
    return True


def write_mixtures_xlsx(
    out_path: Path,
    mixtures: dict[str, tuple[dict, dict, list[dict]]],
    molecule: str,
) -> bool:
    """Emit an xlsx with all mixture data, one sheet for all mixtures."""
    if not HAS_OPENPYXL:
        return False

    wb = Workbook()
    ws = wb.active
    ws.title = "Mixtures"

    bold = Font(bold=True)
    grey = PatternFill("solid", fgColor="EEEEEE")

    # Aggregate rows across all mix-*.tab files
    all_rows: list[dict] = []
    all_tab_cols: list[str] = []
    seen_cols: set[str] = set()
    for label, (_, _, rows) in mixtures.items():
        for r in rows:
            r2 = dict(r)
            r2['mixture'] = label
            all_rows.append(r2)
            for k in r:
                if not k.startswith('_') and k not in seen_cols:
                    all_tab_cols.append(k)
                    seen_cols.add(k)

    if not all_rows:
        wb.save(out_path)
        return True

    meta_cols = ['mixture', 'role', 'compound_nr', 'x_in_mix', 'diverged']
    cols_out = meta_cols + all_tab_cols

    for ci, col in enumerate(cols_out, 1):
        c = ws.cell(row=1, column=ci, value=col)
        c.font = bold
        c.fill = grey

    for ri, row in enumerate(all_rows, 2):
        ws.cell(row=ri, column=1, value=row.get('mixture'))
        ws.cell(row=ri, column=2, value=row.get('_role'))
        ws.cell(row=ri, column=3, value=row.get('_nr'))
        ws.cell(row=ri, column=4, value=row.get('_x_in_mix'))
        ws.cell(row=ri, column=5, value=bool(row.get('_diverged')))
        for ci, col in enumerate(all_tab_cols, len(meta_cols) + 1):
            ws.cell(row=ri, column=ci, value=_to_number_or_text(row.get(col, '')))

    for ci, col in enumerate(cols_out, 1):
        ws.column_dimensions[chr(ord('A') + ci - 1)].width = max(len(col) + 2, 14)

    wb.save(out_path)
    return True


def write_combined_csv(
    out_path: Path,
    pure_rows: list[dict],
    mixtures: dict[str, tuple[dict, dict, list[dict]]],
) -> bool:
    """Long-form CSV combining pure + mixture data with provenance columns."""
    rows: list[dict] = []
    for r in pure_rows:
        r2 = dict(r)
        r2['_source'] = 'pure'
        r2['_mixture'] = ''
        rows.append(r2)
    for label, (_, _, mrows) in mixtures.items():
        for r in mrows:
            r2 = dict(r)
            r2['_source'] = 'mix'
            r2['_mixture'] = label
            rows.append(r2)

    if not rows:
        return False

    all_keys: list[str] = []
    seen: set[str] = set()
    preferred = ['_source', '_mixture', '_role', '_nr', '_x_in_mix', '_diverged', '_compound']
    for k in preferred:
        all_keys.append(k)
        seen.add(k)
    for r in rows:
        for k in r:
            if k not in seen:
                all_keys.append(k)
                seen.add(k)

    with out_path.open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=all_keys, extrasaction='ignore')
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, '') for k in all_keys})
    return True


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def main() -> int:
    if len(sys.argv) < 3:
        print(
            f"Usage: {Path(sys.argv[0]).name} <molecule> <dft-protocol>",
            file=sys.stderr,
        )
        return 2

    molecule = sys.argv[1]
    dft_protocol = sys.argv[2]

    repo_root = Path(__file__).resolve().parent.parent
    work_dir = repo_root / 'molecules' / molecule / dft_protocol / 'cosmotherm'

    if not work_dir.is_dir():
        print(f"ERROR: cosmotherm output dir not found: {work_dir}", file=sys.stderr)
        return 2

    # Parse pure
    pure_tab = work_dir / 'pure-screen.tab'
    pure_metadata: dict[str, str] = {}
    pure_rows: list[dict] = []
    if pure_tab.is_file():
        pure_metadata, pure_rows = parse_pure_tab(pure_tab)
        print(f"[pure] {pure_tab.name}: {len(pure_rows)} rows parsed")
    else:
        print(f"WARN: {pure_tab} not found", file=sys.stderr)

    # Parse mixtures
    mixtures: dict[str, tuple[dict, dict, list[dict]]] = {}
    for mix_tab in sorted(work_dir.glob('mix-*.tab')):
        label = mix_tab.stem.replace('mix-', '', 1)
        meta, comp, rows = parse_mix_tab(mix_tab, label, molecule)
        if not rows:
            print(f"WARN: no data parsed from {mix_tab.name}", file=sys.stderr)
            continue
        mixtures[label] = (meta, comp, rows)
        print(f"[mix ] {mix_tab.name}: {len(rows)} rows parsed "
              f"(composition: {comp or '—'})")

    # Write outputs
    out_pure_xlsx = work_dir / f"{molecule}-pure-screening.xlsx"
    out_mix_xlsx = work_dir / f"{molecule}-mixtures.xlsx"
    out_csv = work_dir / "results.csv"

    wrote_xlsx = False
    if HAS_OPENPYXL:
        if pure_rows:
            write_pure_xlsx(out_pure_xlsx, pure_metadata, pure_rows, molecule)
            print(f"wrote {out_pure_xlsx}")
            wrote_xlsx = True
        if mixtures:
            write_mixtures_xlsx(out_mix_xlsx, mixtures, molecule)
            print(f"wrote {out_mix_xlsx}")
            wrote_xlsx = True
    else:
        print(
            "NOTE: openpyxl not installed — xlsx outputs skipped.\n"
            "      Install with: pip install --user openpyxl\n"
            "      Or on the cluster: pip install --user --break-system-packages openpyxl",
            file=sys.stderr,
        )

    if pure_rows or mixtures:
        write_combined_csv(out_csv, pure_rows, mixtures)
        print(f"wrote {out_csv}")

    if not (pure_rows or mixtures):
        print("ERROR: no data parsed from any .tab file", file=sys.stderr)
        return 1

    return 0


if __name__ == '__main__':
    sys.exit(main())
