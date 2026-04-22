#!/usr/bin/env python3
"""Universal PDB → XYZ preparation with pH-dependent protonation.

Automates the full molecule preparation pipeline:
  1. Clean PDB (select chains, remove waters/ions, resolve alt conformers)
  2. Protonate at user-specified pH using OpenBabel
  3. Determine total molecular charge
  4. Write XYZ file + charge.txt for TURBOMOLE

Requires: obabel (OpenBabel ≥ 3.0) on PATH.

Usage:
    python3 prepare_molecule.py <input.pdb> <molecule_name> <pH> [--chains A,C]

Example:
    python3 prepare_molecule.py molecules/vancomycin/1SHO.pdb vancomycin 2.6 --chains A,C

Outputs (in molecules/<molecule_name>/):
    <molecule_name>_clean.pdb    — cleaned PDB (no waters/ions, one conformer)
    <molecule_name>_pH<pH>.pdb   — protonated PDB
    <molecule_name>.xyz          — final XYZ for TURBOMOLE
    charge.txt                   — integer total charge
    prep.log                     — preparation log with atom counts
"""

import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

# ---------------------------------------------------------------------------
# Import clean_pdb from sibling module
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from clean_pdb import clean_pdb


def check_obabel():
    """Verify OpenBabel is installed and return version string."""
    try:
        result = subprocess.run(
            ["obabel", "-V"], capture_output=True, text=True, timeout=10
        )
        version = result.stdout.strip() or result.stderr.strip()
        return version
    except FileNotFoundError:
        print("ERROR: 'obabel' not found on PATH.", file=sys.stderr)
        print("       Install OpenBabel:  brew install open-babel  (macOS)", file=sys.stderr)
        print("                           apt install openbabel    (Linux)", file=sys.stderr)
        sys.exit(1)


def protonate_pdb(input_pdb, output_pdb, pH):
    """Run OpenBabel to add hydrogens at a given pH.

    Uses obabel -ipdb -opdb -h -p <pH>.  The -p flag adds hydrogens
    considering pH-dependent protonation states of common functional groups.
    """
    cmd = [
        "obabel",
        "-ipdb", str(input_pdb),
        "-opdb", str(output_pdb),
        "-p", str(pH),
    ]
    print(f"  Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

    if result.returncode != 0:
        print(f"ERROR: obabel failed (exit {result.returncode})", file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        sys.exit(1)

    # obabel prints "1 molecule converted" to stderr on success
    if "1 molecule converted" not in result.stderr:
        print(f"WARNING: obabel output unexpected: {result.stderr.strip()}", file=sys.stderr)

    return output_pdb


def determine_charge_from_sdf(pdb_path):
    """Determine total formal charge by converting to SDF and parsing M  CHG lines.

    SDF format explicitly lists charged atoms in M  CHG records:
        M  CHG  2   1   1   5  -1
    means atom 1 has +1, atom 5 has -1.
    """
    cmd = ["obabel", "-ipdb", str(pdb_path), "-osdf"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

    total_charge = 0
    for line in result.stdout.splitlines():
        if line.startswith("M  CHG"):
            # Format: M  CHG  n  atom1 charge1  atom2 charge2 ...
            tokens = line.split()
            # tokens[2] = count of charge pairs
            try:
                n_pairs = int(tokens[2])
                for i in range(n_pairs):
                    charge = int(tokens[3 + 2 * i + 1])
                    total_charge += charge
            except (IndexError, ValueError) as e:
                print(f"WARNING: could not parse M CHG line: {line!r} ({e})",
                      file=sys.stderr)
    return total_charge


def count_formula(pdb_path):
    """Count molecular formula from a PDB file."""
    element_count = Counter()
    with open(pdb_path) as f:
        for line in f:
            if not line.startswith(("ATOM", "HETATM")):
                continue
            # Element symbol: columns 77-78 (PDB standard)
            element = line[76:78].strip() if len(line) >= 78 else ""
            if not element:
                # Fallback: parse from atom name (columns 13-16)
                raw = line[12:16].strip()
                element = re.sub(r"^[0-9]+", "", raw)[:2]
                if len(element) == 2 and element[1].isupper():
                    element = element[0]
                element = element.capitalize()
            element_count[element.capitalize()] += 1
    return element_count


def formula_string(counts):
    """Format element counts as a molecular formula string (Hill order)."""
    # Hill system: C first, H second, then alphabetical
    parts = []
    for el in ["C", "H"]:
        if el in counts:
            parts.append(f"{el}{counts[el]}" if counts[el] > 1 else el)
    for el in sorted(counts.keys()):
        if el not in ("C", "H"):
            parts.append(f"{el}{counts[el]}" if counts[el] > 1 else el)
    return "".join(parts)


def pdb_to_xyz(pdb_path, xyz_path, comment=""):
    """Convert PDB to XYZ format."""
    atoms = []
    with open(pdb_path) as f:
        for line in f:
            if not line.startswith(("ATOM", "HETATM")):
                continue
            x = float(line[30:38])
            y = float(line[38:46])
            z = float(line[46:54])
            element = line[76:78].strip() if len(line) >= 78 else ""
            if not element:
                raw = line[12:16].strip()
                element = re.sub(r"^[0-9]+", "", raw)[:2]
                if len(element) == 2 and element[1].isupper():
                    element = element[0]
                element = element.capitalize()
            atoms.append((element.capitalize(), x, y, z))

    with open(xyz_path, "w") as f:
        f.write(f"{len(atoms)}\n")
        f.write(f"{comment}\n")
        for el, x, y, z in atoms:
            f.write(f"{el:<2s}  {x:14.8f}  {y:14.8f}  {z:14.8f}\n")

    return len(atoms)


# ===========================================================================
# Main
# ===========================================================================
def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Universal PDB -> XYZ preparation with pH-dependent protonation."
    )
    parser.add_argument("input_pdb", help="Input PDB file (e.g. 1SHO.pdb)")
    parser.add_argument("molecule", help="Molecule name (used for output directory & filenames)")
    parser.add_argument("pH", type=float, help="Target pH for protonation (e.g. 2.6, 7.4)")
    parser.add_argument(
        "--chains", default=None,
        help="Comma-separated chain IDs to keep (e.g. A,C). Default: keep all."
    )
    parser.add_argument(
        "--outdir", default=None,
        help="Output directory. Default: molecules/<molecule>/ relative to repo root."
    )
    args = parser.parse_args()

    # --- Resolve paths --------------------------------------------------------
    repo_root = SCRIPT_DIR.parent
    if args.outdir:
        out_dir = Path(args.outdir)
    else:
        out_dir = repo_root / "molecules" / args.molecule
    out_dir.mkdir(parents=True, exist_ok=True)

    input_pdb = Path(args.input_pdb)
    if not input_pdb.exists():
        print(f"ERROR: input PDB not found: {input_pdb}", file=sys.stderr)
        sys.exit(1)

    keep_chains = set(args.chains.split(",")) if args.chains else None
    mol = args.molecule
    pH = args.pH

    clean_path = out_dir / f"{mol}_clean.pdb"
    prot_path = out_dir / f"{mol}_pH{pH}.pdb"
    xyz_path = out_dir / f"{mol}.xyz"
    charge_path = out_dir / "charge.txt"
    log_path = out_dir / "prep.log"

    log_lines = []

    def log(msg):
        print(msg)
        log_lines.append(msg)

    # --- Step 0: Check OpenBabel ----------------------------------------------
    log("=" * 60)
    log(f"prepare_molecule: {mol}  pH={pH}")
    log("=" * 60)
    version = check_obabel()
    log(f"[0/4] OpenBabel: {version}")

    # --- Step 1: Clean PDB ----------------------------------------------------
    log(f"\n[1/4] Cleaning PDB: {input_pdb}")
    if keep_chains:
        log(f"      Keeping chains: {','.join(sorted(keep_chains))}")
    else:
        log("      Keeping all chains")

    # Redirect clean_pdb stdout to capture its report
    from io import StringIO
    old_stdout = sys.stdout
    sys.stdout = StringIO()
    clean_pdb(str(input_pdb), str(clean_path), keep_chains)
    clean_report = sys.stdout.getvalue()
    sys.stdout = old_stdout
    for line in clean_report.strip().split("\n"):
        log(f"      {line}")

    # Count heavy atoms after cleaning
    formula_clean = count_formula(str(clean_path))
    n_heavy = sum(v for k, v in formula_clean.items() if k != "H")
    n_total_clean = sum(formula_clean.values())
    log(f"      Formula (cleaned): {formula_string(formula_clean)}")
    log(f"      Heavy atoms: {n_heavy}, Total: {n_total_clean}")

    # --- Step 2: Protonate at target pH ---------------------------------------
    log(f"\n[2/4] Protonating at pH {pH} with OpenBabel")
    protonate_pdb(str(clean_path), str(prot_path), pH)

    formula_prot = count_formula(str(prot_path))
    n_total_prot = sum(formula_prot.values())
    n_H_added = formula_prot.get("H", 0) - formula_clean.get("H", 0)
    log(f"      Formula (protonated): {formula_string(formula_prot)}")
    log(f"      Total atoms: {n_total_prot}  (added {n_H_added} hydrogens)")

    # --- Step 3: Determine charge ---------------------------------------------
    log(f"\n[3/4] Determining molecular charge")
    charge = determine_charge_from_sdf(str(prot_path))
    log(f"      Total formal charge: {charge:+d}")

    # Write charge file
    with open(charge_path, "w") as f:
        f.write(f"{charge}\n")
    log(f"      Written: {charge_path}")

    # --- Step 4: Convert to XYZ -----------------------------------------------
    log(f"\n[4/4] Writing XYZ")
    comment = f"{mol} pH={pH} charge={charge:+d} formula={formula_string(formula_prot)}"
    n_atoms = pdb_to_xyz(str(prot_path), str(xyz_path), comment=comment)
    log(f"      {n_atoms} atoms -> {xyz_path}")

    # --- Summary --------------------------------------------------------------
    log(f"\n{'=' * 60}")
    log(f"DONE: {mol}")
    log(f"  Formula:  {formula_string(formula_prot)}")
    log(f"  Atoms:    {n_atoms}")
    log(f"  Charge:   {charge:+d}")
    log(f"  pH:       {pH}")
    log(f"  XYZ:      {xyz_path}")
    log(f"  Charge:   {charge_path}")
    log(f"{'=' * 60}")
    log(f"\nNext step:")
    log(f"  scripts/prep_cosmo.sh {mol} BP-TZVPD-FINE")
    log(f"  (charge will be read automatically from {charge_path})")

    # Write log
    with open(log_path, "w") as f:
        f.write("\n".join(log_lines) + "\n")


if __name__ == "__main__":
    main()
