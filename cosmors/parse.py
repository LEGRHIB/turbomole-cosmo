"""Parse per-phase conformer weights from COSMOtherm output.

With AUTOC conformer treatment, COSMOtherm reports the Boltzmann weight of each
conformer in each phase (gas + every solvent). Those weights are the input to the
sensitivity report. Two readers:

  * parse_weights_text() — reads the conformer-weight blocks from a COSMOtherm
    .out/.tab. The expected block shape is documented below; VALIDATE it against
    your COSMOtherm version and adjust the regex if the layout differs.
  * load_weights_json()  — reads a {phase: {conf_id: weight}} JSON (the format an
    HPC-side extractor / the mock runner writes), decoupling the sensitivity
    logic from COSMOtherm's exact text layout.

Expected text block:

    Conformer weights (phase = gas):
      1   0.8234
      2   0.1766
    Conformer weights (phase = h2o):
      1   0.4012
      2   0.5988
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .models import WeightTable

_PHASE_RE = re.compile(r"Conformer weights\s*\(phase\s*=\s*([^)]+)\)\s*:", re.IGNORECASE)
_ROW_RE = re.compile(r"^\s+(\S+)\s+([-+0-9.eE]+)\s*$")


def parse_weights_text(text: str) -> WeightTable:
    wt = WeightTable()
    phase = None
    for line in text.splitlines():
        m = _PHASE_RE.search(line)
        if m:
            phase = m.group(1).strip()
            wt.phases[phase] = {}
            continue
        if phase is not None:
            r = _ROW_RE.match(line)
            if r:
                try:
                    wt.phases[phase][r.group(1)] = float(r.group(2))
                except ValueError:
                    pass
            elif line.strip() == "":
                phase = None
    # drop empty phases
    wt.phases = {p: w for p, w in wt.phases.items() if w}
    return wt


def load_weights_json(path: str) -> WeightTable:
    data = json.loads(Path(path).read_text())
    wt = WeightTable()
    for phase, weights in data.items():
        if isinstance(weights, dict):
            wt.phases[phase] = {str(k): float(v) for k, v in weights.items()}
    return wt
