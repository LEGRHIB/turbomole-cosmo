#!/usr/bin/env python3
"""Universal molecule → XYZ preparation for TURBOMOLE COSMO.

Supports two input formats:
  PDB: Clean → protonate at pH → determine charge → XYZ
  SDF: Generate 3D geometry (--gen3d) → optionally protonate → determine charge → XYZ

Requires: obabel (OpenBabel ≥ 3.0) on PATH.

Usage:
    # From PDB with pH-dependent protonation
    python3 prepare_molecule.py molecules/vancomycin/1SHO.pdb vancomycin 2.6 --chains A,C

    # From 2D SDF (3D geometry generated automatically)
    python3 prepare_molecule.py vancomycin.sdf vancomycin_2d

    # From SDF with explicit charge override
    python3 prepare_molecule.py vancomycin.sdf vancomycin_2d --charge 0

    # From SDF with pH-dependent protonation
    python3 prepare_molecule.py vancomycin.sdf vancomycin_2d --pH 7.4

Outputs (in molecules/<molecule_name>/):
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
    """Run OpenBabel to add hydrogens at a given pH."""
    cmd = [
        "obabel",
        "-ipdb", str(input_pdb),
        "-opdb",
        "-O", str(output_pdb),
        "-p", str(pH),
    ]
    print(f"  Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

    print(f"  obabel stderr: {result.stderr.strip()}")

    if result.returncode != 0:
        print(f"ERROR: obabel failed (exit {result.returncode})", file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        sys.exit(1)

    if not Path(output_pdb).exists():
        print(f"ERROR: obabel did not create {output_pdb}", file=sys.stderr)
        sys.exit(1)

    if "0 molecules converted" in result.stderr:
        print(f"ERROR: obabel converted 0 molecules", file=sys.stderr)
        sys.exit(1)

    return output_pdb


def determine_charge_from_sdf(pdb_path):
    """Determine total formal charge by converting to SDF and parsing M  CHG lines."""
    cmd = ["obabel", "-ipdb", str(pdb_path), "-osdf"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

    total_charge = 0
    for line in result.stdout.splitlines():
        if line.startswith("M  CHG"):
            tokens = line.split()
            try:
                n_pairs = int(tokens[2])
                for i in range(n_pairs):
                    charge = int(tokens[3 + 2 * i + 1])
                    total_charge += charge
            except (IndexError, ValueError) as e:
                print(f"WARNING: could not parse M CHG line: {line!r} ({e})",
                      file=sys.stderr)
    return total_charge


def determine_charge_from_sdf_file(sdf_path):
    """Read total formal charge directly from an SDF file's M CHG lines
    or PUBCHEM_TOTAL_CHARGE metadata."""
    total_charge = 0
    found_chg = False

    with open(sdf_path) as f:
        content = f.read()

    # Try M CHG lines first
    for line in content.splitlines():
        if line.startswith("M  CHG"):
            found_chg = True
            tokens = line.split()
            try:
                n_pairs = int(tokens[2])
                for i in range(n_pairs):
                    charge = int(tokens[3 + 2 * i + 1])
                    total_charge += charge
            except (IndexError, ValueError) as e:
                print(f"WARNING: could not parse M CHG line: {line!r} ({e})",
                      file=sys.stderr)

    if found_chg:
        return total_charge

    # Fallback: PubChem metadata
    match = re.search(r'>\s*<PUBCHEM_TOTAL_CHARGE>\s*\n(\S+)', content)
    if match:
        return int(match.group(1))

    return 0


def sdf_to_3d_xyz(input_sdf, output_xyz, pH=None, ff_steps=5000):
    """Convert SDF (2D or 3D) to XYZ with 3D coordinates.

    Uses OpenBabel --gen3d to generate 3D coordinates from 2D connectivity,
    then runs force-field optimization (MMFF94 or UFF) to get a reasonable
    starting geometry.

    If pH is given, also protonates at that pH.
    """
    cmd = [
        "obabel",
        "-isdf", str(input_sdf),
        "-oxyz",
        "-O", str(output_xyz),
        "--gen3d",
        "--ff", "MMFF94",
        "--steps", str(ff_steps),
    ]
    if pH is not None:
        cmd.extend(["-p", str(pH)])

    print(f"  Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

    print(f"  obabel stderr: {result.stderr.strip()}")

    if result.returncode != 0:
        # Try UFF if MMFF94 fails (some molecules not parameterized in MMFF94)
        print("  MMFF94 failed, trying UFF force field...")
        cmd_uff = [c if c != "MMFF94" else "UFF" for c in cmd]
        print(f"  Running: {' '.join(cmd_uff)}")
        result = subprocess.run(cmd_uff, capture_output=True, text=True, timeout=600)
        print(f"  obabel stderr: {result.stderr.strip()}")

        if result.returncode != 0:
            print(f"ERROR: obabel --gen3d failed with both MMFF94 and UFF", file=sys.stderr)
            print(result.stderr, file=sys.stderr)
            sys.exit(1)

    if not Path(output_xyz).exists():
        print(f"ERROR: obabel did not create {output_xyz}", file=sys.stderr)
        sys.exit(1)

    if "0 molecules converted" in result.stderr:
        print(f"ERROR: obabel converted 0 molecules", file=sys.stderr)
        sys.exit(1)

    return output_xyz


def sdf_to_3d_xyz_with_charge(input_sdf, output_xyz, pH=None, ff_steps=5000):
    """Convert SDF to 3D XYZ and determine charge.

    If pH is given, protonation is applied and charge is determined from the
    protonated structure. Otherwise, charge is read from the SDF file directly.
    """
    if pH is not None:
        # Protonate at pH → charge comes from protonated state
        # First generate 3D with protonation
        sdf_to_3d_xyz(input_sdf, output_xyz, pH=pH, ff_steps=ff_steps)

        # Determine charge from the generated XYZ by converting back to SDF
        cmd = ["obabel", "-ixyz", str(output_xyz), "-osdf"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        total_charge = 0
        for line in result.stdout.splitlines():
            if line.startswith("M  CHG"):
                tokens = line.split()
                try:
                    n_pairs = int(tokens[2])
                    for i in range(n_pairs):
                        charge = int(tokens[3 + 2 * i + 1])
                        total_charge += charge
                except (IndexError, ValueError):
                    pass
        return total_charge
    else:
        # No pH → read charge from SDF, generate 3D without protonation
        charge = determine_charge_from_sdf_file(input_sdf)
        sdf_to_3d_xyz(input_sdf, output_xyz, pH=None, ff_steps=ff_steps)
        return charge


def count_formula(pdb_path):
    """Count molecular formula from a PDB file."""
    element_count = Counter()
    with open(pdb_path) as f:
        for line in f:
            if not line.startswith(("ATOM", "HETATM")):
                continue
            element = line[76:78].strip() if len(line) >= 78 else ""
            if not element:
                raw = line[12:16].strip()
                element = re.sub(r"^[0-9]+", "", raw)[:2]
                if len(element) == 2 and element[1].isupper():
                    element = element[0]
                element = element.capitalize()
            element_count[element.capitalize()] += 1
    return element_count


def count_formula_xyz(xyz_path):
    """Count molecular formula from an XYZ file."""
    element_count = Counter()
    with open(xyz_path) as f:
        n_atoms = int(f.readline().strip())
        f.readline()  # skip comment
        for line in f:
            parts = line.split()
            if len(parts) >= 4:
                element_count[parts[0].capitalize()] += 1
    return element_count


def formula_string(counts):
    """Format element counts as a molecular formula string (Hill order)."""
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


def detect_input_format(input_path):
    """Detect whether input is PDB or SDF based on extension."""
    ext = Path(input_path).suffix.lower()
    if ext in (".pdb", ".ent"):
        return "pdb"
    elif ext in (".sdf", ".mol", ".mol2"):
        return "sdf"
    else:
        # Try to detect from content
        with open(input_path) as f:
            first_lines = f.read(500)
        if "V2000" in first_lines or "V3000" in first_lines:
            return "sdf"
        if any(kw in first_lines for kw in ("ATOM", "HETATM", "HEADER", "REMARK")):
            return "pdb"
        print(f"ERROR: cannot detect format of {input_path}. Use .pdb or .sdf extension.",
              file=sys.stderr)
        sys.exit(1)


# ===========================================================================
# Main
# ===========================================================================
def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Universal molecule -> XYZ preparation for TURBOMOLE COSMO.",
        epilog="Supports PDB (with pH protonation) and SDF (with 3D generation) inputs."
    )
    parser.add_argument("input_file", help="Input file (PDB or SDF)")
    parser.add_argument("molecule", help="Molecule name (used for output directory & filenames)")
    parser.add_argument("pH", nargs="?", type=float, default=None,
                        help="Target pH for protonation (required for PDB, optional for SDF)")
    parser.add_argument(
        "--chains", default=None,
        help="Comma-separated chain IDs to keep (PDB only, e.g. A,C). Default: keep all."
    )
    parser.add_argument(
        "--charge", type=int, default=None,
        help="Override molecular charge (skip auto-detection). Useful for SDF files."
    )
    parser.add_argument(
        "--ff-steps", type=int, default=5000,
        help="Force-field optimization steps for 3D generation (SDF only, default: 5000)"
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

    input_file = Path(args.input_file)
    if not input_file.exists():
        print(f"ERROR: input file not found: {input_file}", file=sys.stderr)
        sys.exit(1)

    mol = args.molecule
    pH = args.pH
    fmt = detect_input_format(str(input_file))

    xyz_path = out_dir / f"{mol}.xyz"
    charge_path = out_dir / "charge.txt"
    log_path = out_dir / "prep.log"

    log_lines = []

    def log(msg):
        print(msg)
        log_lines.append(msg)

    # --- Step 0: Check OpenBabel ----------------------------------------------
    log("=" * 60)
    log(f"prepare_molecule: {mol}  format={fmt}" +
        (f"  pH={pH}" if pH is not None else ""))
    log("=" * 60)
    version = check_obabel()
    log(f"[0] OpenBabel: {version}")

    # ======================================================================
    # SDF path
    # ======================================================================
    if fmt == "sdf":
        log(f"\n[1/3] Generating 3D geometry from SDF: {input_file}")
        log(f"      Force field steps: {args.ff_steps}")
        if pH is not None:
            log(f"      Protonation pH: {pH}")

        charge = sdf_to_3d_xyz_with_charge(
            str(input_file), str(xyz_path),
            pH=pH, ff_steps=args.ff_steps
        )

        # Override charge if specified
        if args.charge is not None:
            log(f"\n[2/3] Charge override: {args.charge} (auto-detected was {charge})")
            charge = args.charge
        else:
            log(f"\n[2/3] Molecular charge: {charge:+d}")

        # Count atoms from XYZ
        formula = count_formula_xyz(str(xyz_path))
        n_atoms = sum(formula.values())

        log(f"\n[3/3] XYZ written: {xyz_path}")
        log(f"      Formula: {formula_string(formula)}")
        log(f"      Atoms:   {n_atoms}")

    # ======================================================================
    # PDB path
    # ======================================================================
    elif fmt == "pdb":
        if pH is None:
            print("ERROR: pH is required for PDB input.", file=sys.stderr)
            print("Usage: prepare_molecule.py <input.pdb> <molecule> <pH>", file=sys.stderr)
            sys.exit(1)

        keep_chains = set(args.chains.split(",")) if args.chains else None

        clean_path = out_dir / f"{mol}_clean.pdb"
        prot_path = out_dir / f"{mol}_pH{pH}.pdb"

        # Step 1: Clean PDB
        log(f"\n[1/4] Cleaning PDB: {input_file}")
        if keep_chains:
            log(f"      Keeping chains: {','.join(sorted(keep_chains))}")
        else:
            log("      Keeping all chains")

        from io import StringIO
        old_stdout = sys.stdout
        sys.stdout = StringIO()
        clean_pdb(str(input_file), str(clean_path), keep_chains)
        clean_report = sys.stdout.getvalue()
        sys.stdout = old_stdout
        for line in clean_report.strip().split("\n"):
            log(f"      {line}")

        formula_clean = count_formula(str(clean_path))
        n_heavy = sum(v for k, v in formula_clean.items() if k != "H")
        n_total_clean = sum(formula_clean.values())
        log(f"      Formula (cleaned): {formula_string(formula_clean)}")
        log(f"      Heavy atoms: {n_heavy}, Total: {n_total_clean}")

        # Step 2: Protonate
        log(f"\n[2/4] Protonating at pH {pH} with OpenBabel")
        protonate_pdb(str(clean_path), str(prot_path), pH)

        formula_prot = count_formula(str(prot_path))
        n_total_prot = sum(formula_prot.values())
        n_H_added = formula_prot.get("H", 0) - formula_clean.get("H", 0)
        log(f"      Formula (protonated): {formula_string(formula_prot)}")
        log(f"      Total atoms: {n_total_prot}  (added {n_H_added} hydrogens)")

        # Step 3: Determine charge
        log(f"\n[3/4] Determining molecular charge")
        if args.charge is not None:
            charge = args.charge
            log(f"      Charge override: {charge:+d}")
        else:
            charge = determine_charge_from_sdf(str(prot_path))
            log(f"      Total formal charge: {charge:+d}")

        # Step 4: Convert to XYZ
        log(f"\n[4/4] Writing XYZ")
        comment = f"{mol} pH={pH} charge={charge:+d} formula={formula_string(formula_prot)}"
        n_atoms = pdb_to_xyz(str(prot_path), str(xyz_path), comment=comment)
        log(f"      {n_atoms} atoms -> {xyz_path}")
        formula = formula_prot

    # --- Write charge file ----------------------------------------------------
    with open(charge_path, "w") as f:
        f.write(f"{charge}\n")

    # --- Summary --------------------------------------------------------------
    log(f"\n{'=' * 60}")
    log(f"DONE: {mol}")
    log(f"  Format:   {fmt.upper()}")
    log(f"  Formula:  {formula_string(formula)}")
    log(f"  Atoms:    {n_atoms}")
    log(f"  Charge:   {charge:+d}")
    if pH is not None:
        log(f"  pH:       {pH}")
    log(f"  XYZ:      {xyz_path}")
    log(f"  Charge:   {charge_path}")
    log(f"{'=' * 60}")
    log(f"\nNext step:")
    log(f"  scripts/prep_cosmo.sh {mol}")
    log(f"  (charge will be read automatically from {charge_path})")

    # Write log
    with open(log_path, "w") as f:
        f.write("\n".join(log_lines) + "\n")


if __name__ == "__main__":
    main()
