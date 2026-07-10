"""AlphaFold mmCIF intake — self-contained port of scripts/prepare_alphafold.py.

Parses an AlphaFold model, applies a per-residue pLDDT confidence gate, and returns
a 3D geometry + charge to seed the pipeline. Two paths:

  * no template  — write the AF heavy atoms straight out (AF emits no H); protonation
    / bond perception happens downstream (xtb pre-opt). Pure Python, no deps.
  * --template SDF — bend the correct (validated) chemistry onto the AF Cα trace so
    non-standard groups (bombesin pyroglutamate + C-terminal amide) come through with
    a closed ring. Backbone paired residue-by-residue (SMARTS walk N->C, symmetry-free),
    Cα pinned to AF, side chains + termini relaxed (constrained MMFF). Needs RDKit.

The CIF parser and pLDDT gate are dependency-free; only the template transplant uses
RDKit (lazy import).
"""
from __future__ import annotations

import statistics
from collections import defaultdict
from typing import List, Optional

BACKBONE = ("N", "CA", "C", "O")


# --------------------------------------------------------------------------- #
# mmCIF parsing (loop-header aware; no external deps)
# --------------------------------------------------------------------------- #
def parse_cif_atoms(path: str) -> List[dict]:
    cols, atoms, in_loop = [], [], False
    with open(path) as fh:
        for ln in fh:
            s = ln.strip()
            if s == "loop_":
                cols, in_loop = [], True
                continue
            if in_loop and s.startswith("_atom_site."):
                cols.append(s.split(".", 1)[1])
                continue
            if cols and (s.startswith("ATOM") or s.startswith("HETATM")):
                p = s.split()
                r = {c: p[i] for i, c in enumerate(cols)}
                atoms.append({
                    "element": r["type_symbol"].capitalize(),
                    "name": r["label_atom_id"],
                    "comp": r["label_comp_id"],
                    "seq": int(r["label_seq_id"]),
                    "x": float(r["Cartn_x"]), "y": float(r["Cartn_y"]),
                    "z": float(r["Cartn_z"]),
                    "plddt": float(r["B_iso_or_equiv"]),
                })
            elif cols and atoms and not s.startswith(("ATOM", "HETATM")):
                break
    if not atoms:
        raise ValueError(f"no _atom_site atoms parsed from {path}")
    return atoms


# --------------------------------------------------------------------------- #
# pLDDT confidence gate
# --------------------------------------------------------------------------- #
def plddt_summary(atoms: List[dict], gate_low: float = 50.0) -> dict:
    per = defaultdict(list)
    for a in atoms:
        per[(a["seq"], a["comp"])].append(a["plddt"])
    allv = [a["plddt"] for a in atoms]
    weak = [f"{c}{s}" for (s, c), v in sorted(per.items())
            if statistics.mean(v) < gate_low]
    return {
        "mean": statistics.mean(allv), "min": min(allv), "max": max(allv),
        "gate": gate_low, "n_residues": len(per),
        "weak_residues": weak,
        "per_residue": {f"{c}{s}": round(statistics.mean(v), 2)
                        for (s, c), v in sorted(per.items())},
    }


# --------------------------------------------------------------------------- #
# heavy-atom xyz (no-template path)
# --------------------------------------------------------------------------- #
def heavy_atom_xyz(atoms: List[dict], comment: str = "") -> str:
    lines = [str(len(atoms)), comment]
    for a in atoms:
        lines.append(f"{a['element']:<2s} {a['x']:14.8f} {a['y']:14.8f} {a['z']:14.8f}")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# template transplant (RDKit)
# --------------------------------------------------------------------------- #
def _af_backbone(atoms):
    bb = defaultdict(dict)
    for a in atoms:
        if a["name"] in BACKBONE:
            bb[a["seq"]][a["name"]] = (a["x"], a["y"], a["z"])
    return [bb[s] for s in sorted(bb)]


def _template_backbone(tmpl):
    from rdkit import Chem
    patt = Chem.MolFromSmarts("[CX4;H1,H2]([NX3])[CX3]=[OX1]")
    units = {}
    for ca, n, c, o in tmpl.GetSubstructMatches(patt):
        units.setdefault(ca, {"CA": ca, "N": n, "C": c, "O": o})
    if not units:
        raise ValueError("no backbone alpha-carbons matched in template")
    n_of = {u["N"]: ca for ca, u in units.items()}
    nxt, prev = {}, {}
    for ca, u in units.items():
        for nb in tmpl.GetAtomWithIdx(u["C"]).GetNeighbors():
            if nb.GetIdx() in n_of:
                nxt[ca] = n_of[nb.GetIdx()]
                prev[n_of[nb.GetIdx()]] = ca
    starts = [ca for ca in units if ca not in prev]
    order, cur, seen = [], (starts or list(units))[0], set()
    while cur is not None and cur not in seen:
        seen.add(cur)
        order.append(units[cur])
        cur = nxt.get(cur)
    return order


def transplant(template_sdf: str, atoms: List[dict]):
    """Bend the template chemistry onto the AF backbone; return an RDKit mol."""
    from rdkit import Chem
    from rdkit.Chem import AllChem, rdMolAlign
    from rdkit.Geometry import Point3D

    tmpl = Chem.MolFromMolFile(template_sdf, removeHs=False)
    if tmpl is None:
        raise ValueError(f"could not read template {template_sdf}")
    af_bb, tm_bb = _af_backbone(atoms), _template_backbone(tmpl)
    n = min(len(af_bb), len(tm_bb))

    pairs, ca_pairs = [], []
    for i in range(n):
        for role in BACKBONE:
            if role in af_bb[i] and role in tm_bb[i]:
                pairs.append((tm_bb[i][role], af_bb[i][role]))
        if "CA" in af_bb[i] and "CA" in tm_bb[i]:
            ca_pairs.append((tm_bb[i]["CA"], af_bb[i]["CA"]))

    conf = tmpl.GetConformer()
    ref = Chem.Mol(tmpl)
    rconf = ref.GetConformer()
    for idx, xyz in pairs:
        rconf.SetAtomPosition(idx, Point3D(*xyz))
    rdMolAlign.AlignMol(tmpl, ref, atomMap=[(idx, idx) for idx, _ in pairs])
    for idx, xyz in pairs:
        conf.SetAtomPosition(idx, Point3D(*xyz))
    try:
        mp = AllChem.MMFFGetMoleculeProperties(tmpl)
        ff = AllChem.MMFFGetMoleculeForceField(tmpl, mp)
        for idx, _ in ca_pairs:
            ff.AddFixedPoint(idx)
        ff.Minimize(maxIts=10000)
    except Exception:
        pass  # xtb pre-opt relaxes downstream
    return tmpl


def intake(cif: str, template: Optional[str] = None, charge: Optional[int] = None,
           plddt_gate: float = 50.0) -> dict:
    """Parse an AF mmCIF -> {mode, plddt, charge, and (mol | xyz)}."""
    atoms = parse_cif_atoms(cif)
    summary = plddt_summary(atoms, plddt_gate)
    if template:
        mol = transplant(template, atoms)
        from rdkit import Chem
        ch = charge if charge is not None else Chem.GetFormalCharge(mol)
        return {"mode": "template", "plddt": summary, "charge": ch, "mol": mol}
    return {"mode": "heavy_atoms", "plddt": summary,
            "charge": charge if charge is not None else 0,
            "xyz": heavy_atom_xyz(atoms, f"AF {cif} pLDDT mean={summary['mean']:.1f}"),
            "n_atoms": len(atoms)}
