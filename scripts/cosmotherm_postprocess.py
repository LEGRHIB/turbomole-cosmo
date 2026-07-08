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

# Thermodynamic constant for the DG_fus correction that brings pure-screen
# log10(x_RS) and mixture log10(x_solub) onto the same scale.
# RT * ln(10) at 298.15 K, in kcal/mol:
#   R = 1.987e-3 kcal/(mol·K), T = 298.15 K, ln(10) = 2.302585
#   => 0.001987 * 298.15 * 2.302585 = 1.36418 kcal/mol
RT_LN10_KCAL_AT_298K = 1.987204e-3 * 298.15 * 2.302585093


def _to_float(v):
    if v is None or v == '':
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


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


def _find_col(row_keys, *patterns) -> str | None:
    """Return the first key in row_keys whose lowercased name contains all patterns."""
    for k in row_keys:
        kl = k.lower()
        if all(p.lower() in kl for p in patterns):
            return k
    return None


def _is_ni(col_name: str) -> bool:
    """True if a column name represents a pr_ni (non-iterative) variant.

    COSMOtherm names these with the prefix 'NI-' (e.g. 'NI-log10(x_solub)',
    'NI-w_solub', 'NI-mu(solv)'). We accept several spellings defensively.
    """
    nl = col_name.lower()
    return nl.startswith('ni-') or nl.startswith('ni_') or '_ni' in nl or nl.endswith('-ni')


def _harvest_dg_fus(mixtures: dict) -> float | None:
    """Pull DG_fus (kcal/mol) from any mixture's solute self-row.

    DG_fus is a property of the solute, not the solvent, so it should be the same
    across every mixture. We grab the first usable value and verify others agree
    within a tolerance.
    """
    candidates = []
    for label, (_, _, rows) in mixtures.items():
        for r in rows:
            if r.get('_role') == 'solute':
                dg = _to_float(r.get('DG_fus'))
                if dg is not None:
                    candidates.append((label, dg))
                break
    if not candidates:
        return None
    base = candidates[0][1]
    for lbl, dg in candidates[1:]:
        if abs(dg - base) > 1e-2:
            print(f"WARN: DG_fus varies across mixtures ({candidates[0][0]}={base:.4f}, "
                  f"{lbl}={dg:.4f}) — using first.", file=sys.stderr)
    return base


def _build_mix_summary(label: str, rows: list[dict]) -> dict:
    """Collapse the per-compound rows of one mixture into a single summary dict.

    Picks out the solute self-row (role='solute') and the two real solvent rows
    (role='solvent' with non-None _x_in_mix), skipping the QSPR-aux water row
    (x_in_mix is None).
    """
    solute = next((r for r in rows if r.get('_role') == 'solute'), None)
    solvent_rows = [
        r for r in rows
        if r.get('_role') == 'solvent' and r.get('_x_in_mix') is not None
    ]
    sol1 = solvent_rows[0] if solvent_rows else {}
    sol2 = solvent_rows[1] if len(solvent_rows) > 1 else {}

    summary: dict = {
        'mixture': label,
        'sol1': sol1.get('_compound', ''),
        'x1': sol1.get('_x_in_mix'),
        'sol2': sol2.get('_compound', ''),
        'x2': sol2.get('_x_in_mix'),
        'T_K': 298.15,
        'iter_diverged': any(r.get('_diverged') for r in rows),
    }

    # Human-readable composition column
    parts = []
    if summary['sol1']:
        parts.append(f"{summary['sol1']} ({summary['x1']:.2f})")
    if summary['sol2']:
        parts.append(f"{summary['sol2']} ({summary['x2']:.2f})")
    summary['composition'] = ' / '.join(parts)

    if not solute:
        return summary

    # Detect column names dynamically — pr_ni-enabled .tab files have parallel
    # NI-*  columns alongside the iterative ones (per COSMOtherm 2026 output:
    # 'NI-log10(x_solub)', 'NI-w_solub', 'NI-log10(S)', 'NI-mu(solv)'). Fall
    # back gracefully when pr_ni wasn't requested (older runs without _ni cols).
    keys = list(solute.keys())
    col_x_iter = next((k for k in keys if 'log10(x' in k.lower() and not _is_ni(k)), None)
    col_x_ni = next((k for k in keys if 'log10(x' in k.lower() and _is_ni(k)), None)
    col_w_iter = next(
        (k for k in keys if ('w_solub' in k.lower() or 'w_fract' in k.lower()) and not _is_ni(k)),
        None,
    )
    col_w_ni = next((k for k in keys if 'w_solub' in k.lower() and _is_ni(k)), None)
    col_logS_iter = next((k for k in keys if 'log10(s' in k.lower() and not _is_ni(k)), None)
    col_logS_ni = next((k for k in keys if 'log10(s' in k.lower() and _is_ni(k)), None)

    summary['log10(x_solub)_iter'] = _to_float(solute.get(col_x_iter)) if col_x_iter else None
    summary['log10(x_solub)_ni'] = _to_float(solute.get(col_x_ni)) if col_x_ni else None
    summary['w_solub_iter'] = _to_float(solute.get(col_w_iter)) if col_w_iter else None
    summary['w_solub_ni'] = _to_float(solute.get(col_w_ni)) if col_w_ni else None
    summary['log10(S)_iter'] = _to_float(solute.get(col_logS_iter)) if col_logS_iter else None
    summary['log10(S)_ni'] = _to_float(solute.get(col_logS_ni)) if col_logS_ni else None
    summary['mu_solute_in_mix'] = _to_float(solute.get('mu(solv)'))
    summary['mu_water'] = _to_float(solute.get('mu(water)'))
    summary['DG_fus'] = _to_float(solute.get('DG_fus'))

    # PRIMARY column selection:
    # The COSMOtherm iterative solver collapses to log10(x_solub) = 0.0
    # ("miscibility floor") for poorly-soluble solutes in mixtures even when
    # the physical solubility is many orders of magnitude smaller. That floor
    # is a numerical artifact, not a real prediction. So we prefer pr_ni (the
    # non-iterative zero-order estimate) whenever iterative either diverged
    # (bracketed values flag set _diverged) OR collapsed to exactly 0.
    def _prefer_ni(iter_val, ni_val) -> tuple:
        if ni_val is None:
            return iter_val, 'iterative' if iter_val is not None else 'missing'
        if iter_val is None:
            return ni_val, 'pr_ni'
        # iter=0 with no brackets = miscibility-floor artifact
        if summary['iter_diverged'] or abs(iter_val) < 1e-9:
            return ni_val, 'pr_ni'
        return iter_val, 'iterative'

    p_x, p_x_src = _prefer_ni(summary['log10(x_solub)_iter'], summary['log10(x_solub)_ni'])
    summary['log10(x_solub)_primary'] = p_x
    summary['primary_source'] = p_x_src

    p_w, _ = _prefer_ni(summary['w_solub_iter'], summary['w_solub_ni'])
    summary['w_solub_primary'] = p_w

    p_s, _ = _prefer_ni(summary['log10(S)_iter'], summary['log10(S)_ni'])
    summary['log10(S)_primary'] = p_s

    return summary


def write_mixtures_xlsx(
    out_path: Path,
    mixtures: dict[str, tuple[dict, dict, list[dict]]],
    molecule: str,
) -> bool:
    """Emit an xlsx with TWO sheets:

    - Sheet 1 "Mixture summary": one row per mixture, columns optimized for
      the user-facing question "how soluble is the solute in this mixture?".
      Sorted descending by log10(x_solub)_primary.
    - Sheet 2 "Raw audit": flat dump of per-compound rows, QSPR-aux water row
      hidden, noise columns dropped. For verification only.
    """
    if not HAS_OPENPYXL:
        return False

    wb = Workbook()
    bold = Font(bold=True)
    italic = Font(italic=True)
    grey = PatternFill("solid", fgColor="EEEEEE")

    # ----- Sheet 1: Mixture summary -----
    ws1 = wb.active
    ws1.title = "Mixture summary"

    # Build per-mixture summary rows
    summaries = [_build_mix_summary(label, rows) for label, (_, _, rows) in mixtures.items()]

    # Sort descending by log10(x_solub)_primary, None last
    def sort_key(s):
        v = s.get('log10(x_solub)_primary')
        return v if v is not None else float('-inf')
    summaries.sort(key=sort_key, reverse=True)

    # Note row explaining the primary-source logic
    note = (
        f"One row per mixture. Sorted descending by log10(x_solub) (primary). "
        f"PRIMARY = non-iterative (pr_ni) when iterative diverged, else iterative. "
        f"See 'primary_source' column."
    )
    ws1.cell(row=1, column=1, value=note).font = italic
    ws1.merge_cells(start_row=1, start_column=1, end_row=1, end_column=16)

    summary_cols = [
        'mixture', 'composition', 'sol1', 'x1', 'sol2', 'x2', 'T_K',
        'log10(x_solub)_primary', 'primary_source', 'iter_diverged',
        'log10(x_solub)_iter', 'log10(x_solub)_ni',
        'w_solub_primary', 'log10(S)_primary',
        'mu_solute_in_mix', 'DG_fus',
    ]
    header_row = 3
    for ci, col in enumerate(summary_cols, 1):
        c = ws1.cell(row=header_row, column=ci, value=col)
        c.font = bold
        c.fill = grey
    for ri, s in enumerate(summaries, header_row + 1):
        for ci, col in enumerate(summary_cols, 1):
            v = s.get(col)
            ws1.cell(row=ri, column=ci, value=v)
    for ci, col in enumerate(summary_cols, 1):
        ws1.column_dimensions[chr(ord('A') + ci - 1)].width = max(len(col) + 2, 14)

    # ----- Sheet 2: Raw audit -----
    ws2 = wb.create_sheet("Raw audit")

    # Hide QSPR-aux water row (Nr=2 with x_in_mix=None) and drop noise columns.
    AUDIT_DROP_COLS = {
        'mu(water)', 'N_Ring', 'N_Amino', 'MolWeight', 'Volume',
        'Exp-State', 'Tmelt', 'DH_fus',
    }

    all_rows: list[dict] = []
    seen_cols: list[str] = []
    seen_set: set[str] = set()
    for label, (_, _, rows) in mixtures.items():
        for r in rows:
            # Hide QSPR aux: the water reference compound has x_in_mix=None and Nr==2
            if r.get('_role') == 'solvent' and r.get('_x_in_mix') is None:
                continue
            r2 = dict(r)
            r2['mixture'] = label
            all_rows.append(r2)
            for k in r:
                if k.startswith('_'):
                    continue
                if k in AUDIT_DROP_COLS:
                    continue
                if k not in seen_set:
                    seen_cols.append(k)
                    seen_set.add(k)

    if all_rows:
        meta_cols = ['mixture', 'role', 'compound_nr', 'x_in_mix', 'diverged']
        cols_out = meta_cols + seen_cols
        for ci, col in enumerate(cols_out, 1):
            c = ws2.cell(row=1, column=ci, value=col)
            c.font = bold
            c.fill = grey
        for ri, r in enumerate(all_rows, 2):
            ws2.cell(row=ri, column=1, value=r.get('mixture'))
            ws2.cell(row=ri, column=2, value=r.get('_role'))
            ws2.cell(row=ri, column=3, value=r.get('_nr'))
            ws2.cell(row=ri, column=4, value=r.get('_x_in_mix'))
            ws2.cell(row=ri, column=5, value=bool(r.get('_diverged')))
            for ci, col in enumerate(seen_cols, len(meta_cols) + 1):
                ws2.cell(row=ri, column=ci, value=_to_number_or_text(r.get(col, '')))
        for ci, col in enumerate(cols_out, 1):
            ws2.column_dimensions[chr(ord('A') + ci - 1)].width = max(len(col) + 2, 14)

    wb.save(out_path)
    return True


def _lookup_pure_xrs(pure_rows: list[dict], solvent_name: str) -> float | None:
    """Find log10(x_RS) for a given solvent name in the pure-screen rows."""
    if not solvent_name:
        return None
    for r in pure_rows:
        if r.get('Solvent', '').strip() == solvent_name.strip():
            return _to_float(r.get('log10(x_RS)'))
    return None


def write_combined_ranking_xlsx(
    out_path: Path,
    pure_rows: list[dict],
    mixtures: dict[str, tuple[dict, dict, list[dict]]],
    molecule: str,
) -> bool:
    """Unified pure+mix ranking, single sheet, one row per system.

    Brings pure-screen 'log10(x_RS)' values onto the same scale as the
    mixture-screen 'log10(x_solub)' values by subtracting DG_fus/(RT·ln 10).
    DG_fus is harvested from any mixture's solute self-row.

    For each MIXTURE row, four extra columns make the chemistry instantly
    readable:
      - pure_baseline_max : DG_fus-corrected log10(x_solub) of the more
                            soluble pure component.
      - pure_baseline_min : same for the less soluble pure component.
      - mix_within_range  : True iff the mix value lies between the two
                            pure-component baselines (the "classical"
                            interpolation behavior).
      - delta_vs_best_pure: mix − pure_baseline_max. Negative = mixture is
                            LESS soluble than either pure (anti-solvent
                            effect, useful for crystallization). Positive =
                            mixture is MORE soluble than the best pure
                            (co-solvent synergy, useful for dissolution).
    Pure rows leave these four columns blank.
    """
    if not HAS_OPENPYXL:
        return False

    wb = Workbook()
    ws = wb.active
    ws.title = "Screening ranking"

    bold = Font(bold=True)
    italic = Font(italic=True)
    grey = PatternFill("solid", fgColor="EEEEEE")

    dg_fus = _harvest_dg_fus(mixtures) if mixtures else None
    shift = dg_fus / RT_LN10_KCAL_AT_298K if dg_fus is not None else 0.0

    combined: list[dict] = []

    # Pure solvents — pull log10(x_RS), w_RS, log10(S_RS) and DG_fus-correct.
    for r in pure_rows:
        x_rs = _to_float(r.get('log10(x_RS)'))
        w_rs = _to_float(r.get('w_RS'))
        s_rs = _to_float(r.get('log10(S_RS)'))
        x_solub_est = x_rs - shift if (dg_fus is not None and x_rs is not None) else x_rs
        s_est = s_rs - shift if (dg_fus is not None and s_rs is not None) else s_rs

        combined.append({
            'system': r.get('Solvent', ''),
            'type': 'pure',
            'composition': r.get('Solvent', ''),
            'log10(x_solub)': x_solub_est,
            'w_solub': w_rs,
            'log10(S)': s_est,
            'diverged': bool(r.get('_diverged')),
            'source': 'pure-screen x_RS (DG_fus-corrected)' if dg_fus is not None else 'pure-screen x_RS (raw)',
            'pure_baseline_max': None,
            'pure_baseline_min': None,
            'mix_within_range': None,
            'delta_vs_best_pure': None,
        })

    # Mixtures — pick the primary solubility number per mixture
    for label, (_, _, rows) in mixtures.items():
        s = _build_mix_summary(label, rows)
        mix_val = s.get('log10(x_solub)_primary')

        # Look up each component's DG_fus-corrected pure-solvent solubility
        sol1_xrs = _lookup_pure_xrs(pure_rows, s.get('sol1', ''))
        sol2_xrs = _lookup_pure_xrs(pure_rows, s.get('sol2', ''))
        sol1_est = sol1_xrs - shift if (sol1_xrs is not None and dg_fus is not None) else sol1_xrs
        sol2_est = sol2_xrs - shift if (sol2_xrs is not None and dg_fus is not None) else sol2_xrs

        if sol1_est is not None and sol2_est is not None:
            pure_max = max(sol1_est, sol2_est)
            pure_min = min(sol1_est, sol2_est)
        else:
            pure_max = sol1_est if sol1_est is not None else sol2_est
            pure_min = pure_max

        within_range = None
        delta = None
        if mix_val is not None and pure_max is not None and pure_min is not None:
            within_range = (pure_min - 1e-9) <= mix_val <= (pure_max + 1e-9)
            delta = mix_val - pure_max

        combined.append({
            'system': s['mixture'],
            'type': 'mixture',
            'composition': s['composition'],
            'log10(x_solub)': mix_val,
            'w_solub': s.get('w_solub_primary'),
            'log10(S)': s.get('log10(S)_primary'),
            'diverged': s.get('iter_diverged', False),
            'source': f"mixture {s.get('primary_source', 'iterative')}",
            'pure_baseline_max': pure_max,
            'pure_baseline_min': pure_min,
            'mix_within_range': within_range,
            'delta_vs_best_pure': delta,
        })

    # Sort descending by log10(x_solub) — None goes last
    def keyfn(c):
        v = c.get('log10(x_solub)')
        return v if v is not None else float('-inf')
    combined.sort(key=keyfn, reverse=True)

    # Header note
    if dg_fus is not None:
        note = (
            f"Pure and mixture solubilities on same log10(x_solub) scale via DG_fus "
            f"correction.  DG_fus = {dg_fus:.4f} kcal/mol;  RT·ln10 (298.15 K) = "
            f"{RT_LN10_KCAL_AT_298K:.4f} kcal/mol;  shift = {shift:.3f} log units.  "
            f"Pure x_RS minus this shift; mixture values direct from screen.  "
            f"delta_vs_best_pure < 0 → anti-solvent effect; > 0 → co-solvent synergy."
        )
    else:
        note = (
            "No DG_fus available (no mixtures parsed) — pure rows show log10(x_RS) "
            "as-is; not on the same scale as mixture values."
        )
    ws.cell(row=1, column=1, value=note).font = italic
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=13)

    headers = [
        'rank', 'system', 'type', 'composition',
        'log10(x_solub)', 'w_solub', 'log10(S)',
        'pure_baseline_max', 'pure_baseline_min',
        'mix_within_range', 'delta_vs_best_pure',
        'diverged', 'source',
    ]
    header_row = 3
    for ci, h in enumerate(headers, 1):
        c = ws.cell(row=header_row, column=ci, value=h)
        c.font = bold
        c.fill = grey

    for i, row in enumerate(combined, 1):
        ws.cell(row=header_row + i, column=1, value=i)
        ws.cell(row=header_row + i, column=2, value=row['system'])
        ws.cell(row=header_row + i, column=3, value=row['type'])
        ws.cell(row=header_row + i, column=4, value=row['composition'])
        ws.cell(row=header_row + i, column=5, value=row['log10(x_solub)'])
        ws.cell(row=header_row + i, column=6, value=row['w_solub'])
        ws.cell(row=header_row + i, column=7, value=row['log10(S)'])
        ws.cell(row=header_row + i, column=8, value=row['pure_baseline_max'])
        ws.cell(row=header_row + i, column=9, value=row['pure_baseline_min'])
        ws.cell(row=header_row + i, column=10, value=row['mix_within_range'])
        ws.cell(row=header_row + i, column=11, value=row['delta_vs_best_pure'])
        ws.cell(row=header_row + i, column=12, value=row['diverged'])
        ws.cell(row=header_row + i, column=13, value=row['source'])

    for ci, h in enumerate(headers, 1):
        ws.column_dimensions[chr(ord('A') + ci - 1)].width = max(len(h) + 2, 14)

    wb.save(out_path)
    return True


def write_relative_ranking_xlsx(
    out_path: Path,
    pure_rows: list[dict],
    mixtures: dict[str, tuple[dict, dict, list[dict]]],
    molecule: str,
) -> bool:
    """Unified pure + mixture ranking on ONE axis: relative solubility vs water.

    Everything is log10(x_solvent / x_water) — the DG_fus-free relative
    solubility (water = 0, positive = more soluble than pure water):
      - Pures:    log10(x_RS,i) - log10(x_RS,water)   (from pure-screen.tab)
      - Mixtures: (mu(water) - mu(solv)) / (RT*ln10)   (from each mix-*.tab)
    Both equal (mu_water - mu_solv,i)/(RT*ln10): the solute-reference constant
    in x_RS cancels when water is subtracted, and the pure screen's water x_RS
    and a mixture's mu(water) are the same quantity (solute in pure water).

    Ranks COSMO-RS surface affinity, not absolute solubility (which floors to
    log10(x_solub)=0 for a protein). Magnitudes scale with solute surface area
    -> comparable within one solute, not between solutes.
    """
    if not HAS_OPENPYXL:
        return False

    wb = Workbook()
    ws = wb.active
    ws.title = "Relative ranking"
    bold = Font(bold=True)
    italic = Font(italic=True)
    grey = PatternFill("solid", fgColor="EEEEEE")

    # Water reference: log10(x_RS) of h2o in the pure screen.
    water_ref = None
    for r in pure_rows:
        if r.get('Solvent', '').strip() == 'h2o':
            water_ref = _to_float(r.get('log10(x_RS)'))
            break

    combined: list[dict] = []
    for r in pure_rows:
        x_rs = _to_float(r.get('log10(x_RS)'))
        rel = (x_rs - water_ref) if (x_rs is not None and water_ref is not None) else None
        combined.append({'system': r.get('Solvent', ''), 'type': 'pure',
                         'composition': r.get('Solvent', ''), 'rel': rel,
                         'raw': x_rs, 'raw_kind': 'log10(x_RS)', 'source': 'pure-screen'})
    for label, (_, _, rows) in mixtures.items():
        s = _build_mix_summary(label, rows)
        mu_solv = s.get('mu_solute_in_mix')
        mu_w = s.get('mu_water')
        rel = ((mu_w - mu_solv) / RT_LN10_KCAL_AT_298K
               if (mu_solv is not None and mu_w is not None) else None)
        combined.append({'system': label, 'type': 'mixture',
                         'composition': s.get('composition', label), 'rel': rel,
                         'raw': mu_solv, 'raw_kind': 'mu(solv) kcal/mol',
                         'source': 'mix mu(water)-mu(solv)'})

    combined.sort(key=lambda c: c['rel'] if c['rel'] is not None else float('-inf'),
                  reverse=True)

    note = (
        "Relative solubility vs pure water (water = 0): log10(x_solvent/x_water), "
        "DG_fus-free.  Pures = log10(x_RS) - log10(x_RS,water);  mixtures = "
        f"(mu(water) - mu(solv)) / (RT*ln10 = {RT_LN10_KCAL_AT_298K:.4f} kcal/mol).  "
        "Positive = more soluble than water.  COSMO-RS surface affinity, not "
        "absolute solubility; magnitudes comparable within this solute only."
    )
    ws.cell(row=1, column=1, value=note).font = italic
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=8)

    headers = ['rank', 'system', 'type', 'composition',
               'rel_log10_solub_vs_water', 'raw_value', 'raw_kind', 'source']
    hr = 3
    for ci, h in enumerate(headers, 1):
        c = ws.cell(row=hr, column=ci, value=h)
        c.font = bold
        c.fill = grey
    for i, row in enumerate(combined, 1):
        ws.cell(row=hr + i, column=1, value=i)
        ws.cell(row=hr + i, column=2, value=row['system'])
        ws.cell(row=hr + i, column=3, value=row['type'])
        ws.cell(row=hr + i, column=4, value=row['composition'])
        ws.cell(row=hr + i, column=5, value=row['rel'])
        ws.cell(row=hr + i, column=6, value=row['raw'])
        ws.cell(row=hr + i, column=7, value=row['raw_kind'])
        ws.cell(row=hr + i, column=8, value=row['source'])
    for ci, h in enumerate(headers, 1):
        ws.column_dimensions[chr(ord('A') + ci - 1)].width = max(len(h) + 2, 16)

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
    out_rank_xlsx = work_dir / f"{molecule}-screening-ranking.xlsx"
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
        if pure_rows or mixtures:
            write_relative_ranking_xlsx(out_rank_xlsx, pure_rows, mixtures, molecule)
            print(f"wrote {out_rank_xlsx}")
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
