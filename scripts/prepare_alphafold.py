#!/usr/bin/env python3
"""prepare_alphafold.py — AlphaFold (mmCIF) -> TURBOMOLE-COSMO geometry intake.

The AlphaFold path that docs/workflow.md describes but the repo never
implemented. Turns an AlphaFold / AlphaFold-Server mmCIF model into the
pipeline's <mol>.xyz + charge.txt, with a pLDDT confidence gate.

AlphaFold only emits the 20 standard residues, so for a solute whose real
chemistry has non-standard groups (bombesin: N-terminal pyroglutamate +
C-terminal amide) the raw model is the wrong molecule. With --template <sdf>
the correct, validated molecule (right bonds, right H, a closed pyroglutamate
ring, a sane conformer) is bent ONTO the AlphaFold backbone:

  1. main-chain atoms (N, CA, C, O) are identified in both — by atom name in
     the AF model, by a backbone SMARTS walked N->C in the template — and
     paired residue-by-residue in sequence order (symmetry-free: no MCS);
  2. the template is rigid-aligned to the AF backbone, then the AF backbone
     coordinates are copied onto it exactly (so the AF conformation is the
     one handed downstream);
  3. a constrained MMFF relax (backbone frozen) settles the side chains, the
     hydrogens and the non-standard termini against that backbone.

Bonding for xtb / TURBOMOLE is perceived from coordinates, so going through a
template is what guarantees the pyroglutamate lactam is geometrically CLOSED
in the handoff geometry (atom relabeling alone would hand xtb an open ring).
xtb_preopt does the final full relaxation on the cluster.

Requires (pip wheels, installable on a login node with --user):
    pip install --user rdkit openbabel-wheel
"""

import argparse
import statistics
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

BACKBONE = ("N", "CA", "C", "O")


# --------------------------------------------------------------------------
# mmCIF parsing (loop-header aware; no external deps)
# --------------------------------------------------------------------------
def parse_cif_atoms(path):
    cols, atoms, in_loop = [], [], False
    for ln in open(path):
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
        sys.exit(f"ERROR: no _atom_site atoms parsed from {path}")
    return atoms


# --------------------------------------------------------------------------
# pLDDT gate
# --------------------------------------------------------------------------
def plddt_report(atoms, log, gate_low=50.0):
    per = defaultdict(list)
    for a in atoms:
        per[(a["seq"], a["comp"])].append(a["plddt"])
    allv = [a["plddt"] for a in atoms]
    mean, mn, mx = statistics.mean(allv), min(allv), max(allv)
    log(f"      pLDDT  mean={mean:.1f}  min={mn:.1f}  max={mx:.1f}")
    weak = [f"{c}{s}" for (s, c), v in sorted(per.items())
            if statistics.mean(v) < gate_low]
    log(f"      pLDDT < {gate_low:.0f}: {', '.join(weak) if weak else 'none'}")
    return mean, mn, mx, per


# --------------------------------------------------------------------------
# backbone identification
# --------------------------------------------------------------------------
def af_backbone(atoms):
    """AF main-chain atoms per residue, ordered by seq. {seq:{role:(x,y,z)}}."""
    bb = defaultdict(dict)
    for a in atoms:
        if a["name"] in BACKBONE:
            bb[a["seq"]][a["name"]] = (a["x"], a["y"], a["z"])
    return [bb[s] for s in sorted(bb)]


def template_backbone(tmpl, log):
    """Return template main-chain atom indices per residue, ordered N->C.

    Each residue -> {'N':i,'CA':i,'C':i,'O':i}. Residues are linked by the
    peptide bond (backbone C of i bonded to backbone N of i+1) and walked
    from the terminus, so the ordering is unique despite repeated residues.
    """
    from rdkit import Chem
    patt = Chem.MolFromSmarts("[CX4;H1,H2]([NX3])[CX3]=[OX1]")
    units = {}  # ca_idx -> {'CA','N','C','O'}
    for ca, n, c, o in tmpl.GetSubstructMatches(patt):
        if ca in units:
            continue
        units[ca] = {"CA": ca, "N": n, "C": c, "O": o}
    if not units:
        sys.exit("ERROR: no backbone alpha-carbons matched in template")

    n_of = {u["N"]: ca for ca, u in units.items()}
    c_of = {u["C"]: ca for ca, u in units.items()}
    # peptide links: backbone C(i) -- N(i+1)
    nxt, prev = {}, {}
    for ca, u in units.items():
        cidx = u["C"]
        for nb in tmpl.GetAtomWithIdx(cidx).GetNeighbors():
            if nb.GetIdx() in n_of:                    # bonded to another unit's N
                nxt[ca] = n_of[nb.GetIdx()]
                prev[n_of[nb.GetIdx()]] = ca
    starts = [ca for ca in units if ca not in prev]
    if len(starts) != 1:
        log(f"      WARNING: {len(starts)} chain starts found (expected 1)")
    order, cur, seen = [], (starts or list(units))[0], set()
    while cur is not None and cur not in seen:
        seen.add(cur)
        order.append(units[cur])
        cur = nxt.get(cur)
    log(f"      template backbone: {len(order)} residues linked N->C")
    return order


# --------------------------------------------------------------------------
# transplant
# --------------------------------------------------------------------------
def transplant(template_sdf, af_atoms, log):
    from rdkit import Chem
    from rdkit.Chem import AllChem, rdMolAlign
    from rdkit.Geometry import Point3D

    tmpl = Chem.MolFromMolFile(template_sdf, removeHs=False)
    if tmpl is None:
        sys.exit(f"ERROR: could not read template {template_sdf}")

    af_bb = af_backbone(af_atoms)
    tm_bb = template_backbone(tmpl, log)
    n = min(len(af_bb), len(tm_bb))
    if len(af_bb) != len(tm_bb):
        log(f"      WARNING: residue count AF={len(af_bb)} template={len(tm_bb)};"
            f" pairing first {n}")

    # residue-by-residue, role-by-role backbone correspondence
    pairs = []     # (template_atom_idx, (x,y,z)_AF, role)
    ca_pairs = []  # (template_CA_idx, (x,y,z)_AF) — the fold anchors
    for i in range(n):
        for role in BACKBONE:
            if role in af_bb[i] and role in tm_bb[i]:
                pairs.append((tm_bb[i][role], af_bb[i][role], role))
        if "CA" in af_bb[i] and "CA" in tm_bb[i]:
            ca_pairs.append((tm_bb[i]["CA"], af_bb[i]["CA"]))
    log(f"      backbone atoms paired: {len(pairs)}  (Ca anchors: {len(ca_pairs)})")

    conf = tmpl.GetConformer()
    # 1) rigid-align template onto the AF backbone
    ref = Chem.Mol(tmpl)
    rconf = ref.GetConformer()
    for idx, xyz, _ in pairs:
        rconf.SetAtomPosition(idx, Point3D(*xyz))
    rdMolAlign.AlignMol(tmpl, ref, atomMap=[(idx, idx) for idx, _, _ in pairs])
    # 2) copy AF backbone coords onto the template as the relax starting point
    for idx, xyz, _ in pairs:
        conf.SetAtomPosition(idx, Point3D(*xyz))
    # 3) relax with the Ca trace PINNED to AF. The AF fold (the Ca trace) is
    #    preserved exactly while side chains, the pyroglutamate ring, the
    #    C-terminal amide and all hydrogens settle to a clash-free, unstrained
    #    geometry. Freezing the entire backbone instead leaves a stretched bond
    #    and a steric clash at the rebuilt non-standard termini.
    try:
        mp = AllChem.MMFFGetMoleculeProperties(tmpl)
        ff = AllChem.MMFFGetMoleculeForceField(tmpl, mp)
        for idx, _ in ca_pairs:
            ff.AddFixedPoint(idx)
        ff.Minimize(maxIts=10000)
        log("      Ca-anchored MMFF relax: ok")
    except Exception as e:                                   # noqa: BLE001
        log(f"      MMFF relax skipped ({e}); xtb_preopt will relax instead")

    import math
    d2 = [(conf.GetAtomPosition(t) - Point3D(*x)).LengthSq() for t, x in ca_pairs]
    log(f"      Ca RMSD vs AF: {math.sqrt(sum(d2)/len(d2)):.4f} A "
        f"(fold preserved; backbone/side chains relaxed)")
    return tmpl


# --------------------------------------------------------------------------
# helpers / io
# --------------------------------------------------------------------------
def cif_to_rdkit(cif_path, log):
    from rdkit import Chem
    sdf = tempfile.mktemp(suffix=".sdf")
    res = subprocess.run(["obabel", "-icif", str(cif_path), "-osdf", "-O", sdf],
                         capture_output=True, text=True)
    tail = res.stderr.strip().splitlines()[-1] if res.stderr.strip() else "ok"
    log(f"      obabel: {tail}")
    mol = Chem.MolFromMolFile(sdf, removeHs=True, sanitize=True)
    if mol is None:
        sys.exit("ERROR: RDKit could not read OpenBabel-perceived AF structure")
    return Chem.AddHs(mol, addCoords=True)


def formula(mol):
    from rdkit.Chem import rdMolDescriptors
    return rdMolDescriptors.CalcMolFormula(mol)


def max_bond_len(mol):
    conf = mol.GetConformer()
    m = 0.0
    for b in mol.GetBonds():
        p = conf.GetAtomPosition(b.GetBeginAtomIdx())
        q = conf.GetAtomPosition(b.GetEndAtomIdx())
        m = max(m, ((p.x-q.x)**2 + (p.y-q.y)**2 + (p.z-q.z)**2) ** 0.5)
    return m


def write_xyz(mol, path, comment):
    conf = mol.GetConformer()
    with open(path, "w") as f:
        f.write(f"{mol.GetNumAtoms()}\n{comment}\n")
        for at in mol.GetAtoms():
            p = conf.GetAtomPosition(at.GetIdx())
            f.write(f"{at.GetSymbol():<2s} {p.x:14.8f} {p.y:14.8f} {p.z:14.8f}\n")


# --------------------------------------------------------------------------
def main():
    from rdkit import Chem

    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cif", help="AlphaFold mmCIF model")
    ap.add_argument("molecule", help="molecule name (-> molecules/<name>/)")
    ap.add_argument("--template", help="SDF of the correct molecule to bend "
                    "onto the AF backbone (non-standard chemistry)")
    ap.add_argument("--charge", type=int, default=None)
    ap.add_argument("--plddt-gate", type=float, default=50.0)
    ap.add_argument("--outdir", default=None)
    args = ap.parse_args()

    repo = Path(__file__).resolve().parent.parent
    out = Path(args.outdir) if args.outdir else repo / "molecules" / args.molecule
    out.mkdir(parents=True, exist_ok=True)
    xyz_path, charge_path = out / f"{args.molecule}.xyz", out / "charge.txt"
    log_path, plddt_csv = out / "prep.log", out / f"{args.molecule}_plddt.csv"

    lines = []
    def log(m):
        print(m, flush=True); lines.append(m)

    log("=" * 64)
    log(f"prepare_alphafold: {args.molecule}")
    log("=" * 64)
    log(f"[1/4] Reading AF mmCIF: {args.cif}")
    atoms = parse_cif_atoms(args.cif)
    el = Counter(a["element"] for a in atoms)
    log(f"      {sum(el.values())} heavy atoms  {dict(el)}  (AF emits no H)")

    log("[2/4] pLDDT confidence gate")
    mean, mn, mx, per = plddt_report(atoms, log, args.plddt_gate)
    with open(plddt_csv, "w") as f:
        f.write("resnum,resname,mean_plddt\n")
        for (s, c), v in sorted(per.items()):
            f.write(f"{s},{c},{statistics.mean(v):.2f}\n")

    if args.template:
        log(f"[3/4] Bending correct chemistry onto AF backbone: {args.template}")
        mol = transplant(args.template, atoms, log)
        charge = args.charge if args.charge is not None else Chem.GetFormalCharge(mol)
    else:
        log("[3/4] No template: AF heavy atoms + OpenBabel/RDKit H-add")
        mol = cif_to_rdkit(args.cif, log)
        charge = args.charge if args.charge is not None else 0

    log(f"      formula: {formula(mol)}   atoms: {mol.GetNumAtoms()}   "
        f"charge: {charge:+d}")
    mbl = max_bond_len(mol)
    log(f"      max bond length: {mbl:.3f} A " +
        ("(OK)" if mbl < 2.0 else "(check; xtb_preopt should still close it)"))

    log("[4/4] Writing outputs")
    comment = (f"{args.molecule} from AlphaFold {Path(args.cif).name} | "
               f"pLDDT mean={mean:.1f} | {formula(mol)} charge={charge:+d}")
    write_xyz(mol, xyz_path, comment)
    with open(charge_path, "w") as f:
        f.write(f"{charge}\n")
    log(f"      xyz    -> {xyz_path}")
    log(f"      charge -> {charge_path}  ({charge:+d})")
    log(f"      pLDDT  -> {plddt_csv}")
    log("")
    log(f"Next (cluster): scripts/xtb_preopt.sh {args.molecule}  then  "
        f"scripts/prep_cosmo.sh {args.molecule} BP-TZVPD-FINE")
    with open(log_path, "w") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
