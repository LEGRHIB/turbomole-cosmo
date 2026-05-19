#!/usr/bin/env python3
"""propka_prep.py — PROPKA-corrected protonation for biomolecule inputs.

Runs pdb2pqr30 with PROPKA titration-state assignment at a user-specified pH,
writes a clean XYZ (with hydrogens placed in the right places) and a
charge.txt with the integer total charge computed from the protonation
assignment. Replaces ad-hoc charge hardcoding for proteins and peptides.

This is the upstream preprocessing step that Schmitz et al. (JPCB 2020,
124, 3636) use via Schrödinger Maestro + EPIK + PROPKA before xtb runs.
Both DFT SCF oscillation and GFN2-xTB SCC segfaults on charged proteins
commonly trace to wrong protonation; this script is the canonical fix.

Usage:
    scripts/propka_prep.py <pdb_path> [options]

Options:
    --molecule NAME      Molecule name (default: PDB basename). Output
                         goes to molecules/<NAME>/. Created if missing.
    --ph FLOAT           Target pH (default: 7.0).
    --ff NAME            Force field for partial charges in the PQR
                         (AMBER, CHARMM, PARSE, TYL06). Affects the
                         per-atom partial-charge values printed in the
                         PQR but not the integer total charge or the H
                         placement. Default: AMBER.
    --keep-water         Keep crystal water molecules. Default: drop
                         them. Override only when waters are
                         catalytically important (e.g. coordinated to
                         a metal center).
    --output-name NAME   Basename for output files (default: same as
                         --molecule).
    --dry-run            Run PROPKA, report the pKa assignment and what
                         would change, but do not overwrite the
                         molecule's .xyz or charge.txt.

Dependencies (install once):
    pip install --user pdb2pqr           # provides pdb2pqr30 + propka3

Example — fix the lysozyme +8 protonation problem:
    scripts/propka_prep.py molecules/lysozyme/lysozyme_clean.pdb --ph 7.0
"""

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

# Two-letter element symbols that can appear in PQR atom names (metals +
# common ligand elements). First-letter fallback handles the rest.
TWO_LETTER_ELEMENTS = {
    "FE", "ZN", "MG", "MN", "CU", "NI", "CO", "CD", "HG", "CA",
    "NA", "CL", "BR", "SI", "SE", "AS", "AG", "AU", "PT", "PB",
}

# Three-letter PROPKA group codes that are titratable; used to decode the
# .propka summary table.
TITRATABLE_GROUPS = {
    "ASP", "GLU", "HIS", "CYS", "TYR", "LYS", "ARG", "N+", "C-",
}


def find_tool(name):
    """Locate an executable on PATH or in the user-local pip bin dir."""
    path = shutil.which(name)
    if path:
        return path
    fallback = Path.home() / ".local" / "bin" / name
    if fallback.is_file():
        return str(fallback)
    return None


def require_pdb2pqr():
    p = find_tool("pdb2pqr30") or find_tool("pdb2pqr")
    if not p:
        sys.exit(
            "ERROR: pdb2pqr30 not found. Install with:\n"
            "  pip install --user pdb2pqr\n"
            "and ensure ~/.local/bin is on PATH."
        )
    return p


def run_pdb2pqr(pdb_in, pqr_out, protonated_pdb_out, ph, ff, drop_water, workdir):
    """Invoke pdb2pqr30. Returns its stdout+stderr log path."""
    cmd = [
        require_pdb2pqr(),
        "--ff", ff,
        "--with-ph", str(ph),
        "--titration-state-method", "propka",
        "--keep-chain",
        "--pdb-output", str(protonated_pdb_out),
    ]
    if drop_water:
        cmd.append("--drop-water")
    cmd += [str(pdb_in), str(pqr_out)]

    log = workdir / "pdb2pqr.log"
    with log.open("w") as fh:
        fh.write("$ " + " ".join(cmd) + "\n\n")
        result = subprocess.run(
            cmd, stdout=fh, stderr=subprocess.STDOUT, cwd=workdir
        )
    if result.returncode != 0:
        sys.stderr.write(
            f"ERROR: pdb2pqr30 exited with status {result.returncode}.\n"
            f"       See {log} for details.\n"
        )
        sys.exit(result.returncode)
    return log


def run_propka_standalone(pdb_in, workdir):
    """Run propka3 to produce a human-readable .pka file with the per-residue
    pKa table. Returns the .pka path, or None if propka3 isn't available."""
    propka = find_tool("propka3")
    if not propka:
        return None
    log = workdir / "propka.log"
    # propka3 writes its output beside the input PDB; copy the input into
    # workdir first so artifacts stay grouped.
    local_pdb = workdir / Path(pdb_in).name
    if not local_pdb.exists():
        shutil.copy(pdb_in, local_pdb)
    with log.open("w") as fh:
        fh.write(f"$ {propka} {local_pdb.name}\n\n")
        subprocess.run(
            [propka, local_pdb.name],
            stdout=fh, stderr=subprocess.STDOUT, cwd=workdir, check=False,
        )
    pka_files = sorted(workdir.glob("*.pka"))
    return pka_files[-1] if pka_files else None


def guess_element(atom_name):
    """Map a PDB atom name (e.g. 'CA', 'NZ', 'HD12', 'FE') to an element
    symbol. PDB convention: element symbol is in the first 2 chars,
    right-padded; first letter is uppercase, second (if present) lowercase
    for two-letter elements. Heuristic suffices for proteins + common
    ligand elements."""
    stripped = atom_name.strip().upper()
    if not stripped:
        return "X"
    # Strip leading digits ("1HH1" → "HH1") — common in older PDBs
    stripped = re.sub(r"^\d+", "", stripped)
    if not stripped:
        return "X"
    # Hydrogens always start with H
    if stripped[0] == "H":
        return "H"
    # Two-letter elements (metals + halogens + Si/Se/As/etc.)
    if len(stripped) >= 2 and stripped[:2] in TWO_LETTER_ELEMENTS:
        return stripped[0] + stripped[1].lower()
    return stripped[0]


def parse_pqr(pqr_path):
    """Read a PQR file. Returns (list of (element, x, y, z), float total_q)."""
    atoms = []
    total_q = 0.0
    with open(pqr_path) as fh:
        for line in fh:
            if not (line.startswith("ATOM") or line.startswith("HETATM")):
                continue
            # PQR is whitespace-separated past the residue columns. We
            # rely on negative indexing because radius is always the last
            # column and charge is the second-to-last.
            parts = line.split()
            if len(parts) < 8:
                continue
            try:
                radius = float(parts[-1])  # noqa: F841 — read for validation
                q = float(parts[-2])
                z = float(parts[-3])
                y = float(parts[-4])
                x = float(parts[-5])
            except ValueError:
                continue
            atom_name = parts[2]
            elem = guess_element(atom_name)
            atoms.append((elem, x, y, z))
            total_q += q
    return atoms, total_q


def write_xyz(atoms, path, comment):
    with open(path, "w") as fh:
        fh.write(f"{len(atoms)}\n")
        fh.write(f"{comment}\n")
        for elem, x, y, z in atoms:
            fh.write(f"{elem:<2s} {x:14.8f} {y:14.8f} {z:14.8f}\n")


def extract_pka_summary(pka_path):
    """Parse the SUMMARY OF THIS PREDICTION block of a .pka file.
    Returns a list of dicts with keys: group, resnum, chain, pKa, model_pKa."""
    if pka_path is None or not Path(pka_path).exists():
        return []
    rows = []
    in_block = False
    with open(pka_path) as fh:
        for line in fh:
            if "SUMMARY OF THIS PREDICTION" in line:
                in_block = True
                continue
            if not in_block:
                continue
            if line.startswith("---") or "Free energy" in line:
                break
            parts = line.split()
            if len(parts) >= 5 and parts[0] in TITRATABLE_GROUPS:
                try:
                    rows.append({
                        "group": parts[0],
                        "resnum": parts[1],
                        "chain": parts[2],
                        "pKa": float(parts[3]),
                        "model_pKa": float(parts[4]),
                    })
                except (ValueError, IndexError):
                    pass
    return rows


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("pdb", type=Path, help="Input PDB file")
    ap.add_argument("--molecule", help="Molecule name (default: PDB stem)")
    ap.add_argument("--ph", type=float, default=7.0)
    ap.add_argument("--ff", default="AMBER",
                    choices=["AMBER", "CHARMM", "PARSE", "TYL06"])
    ap.add_argument("--keep-water", action="store_true")
    ap.add_argument("--output-name", help="Output basename (default: --molecule)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not args.pdb.exists():
        sys.exit(f"ERROR: {args.pdb} not found")
    # Resolve to an absolute path now so that the subprocess cwd= we set
    # later (the propka subdir) doesn't re-interpret a relative path. If
    # pdb2pqr can't find the file locally, it falls back to treating the
    # argument as a 4-letter PDB ID and tries to download it from RCSB —
    # which produces a 404 and a confusing error message.
    args.pdb = args.pdb.resolve()

    mol_name = args.molecule or args.pdb.stem.replace("_clean", "").replace("_pH4.5", "")
    out_name = args.output_name or mol_name

    repo_root = Path(__file__).resolve().parent.parent
    mol_dir = repo_root / "molecules" / mol_name
    mol_dir.mkdir(parents=True, exist_ok=True)
    workdir = mol_dir / "propka"
    workdir.mkdir(exist_ok=True)

    drop_water = not args.keep_water
    pqr_out = workdir / f"{out_name}_ph{args.ph:.1f}.pqr"
    protonated_pdb = workdir / f"{out_name}_ph{args.ph:.1f}_protonated.pdb"

    print(f"=== propka_prep: {mol_name} @ pH {args.ph} ===")
    print(f"  Input PDB: {args.pdb}")
    print(f"  Force field: {args.ff}")
    print(f"  Water: {'kept' if args.keep_water else 'dropped'}")
    print(f"  Workdir: {workdir}")
    print()

    print(f"[1/4] Running pdb2pqr30 + PROPKA")
    log = run_pdb2pqr(args.pdb, pqr_out, protonated_pdb,
                     args.ph, args.ff, drop_water, workdir)
    print(f"      pqr -> {pqr_out.name}")
    print(f"      pdb -> {protonated_pdb.name}")
    print(f"      log -> {log.name}")

    print(f"[2/4] Generating pKa table (propka3)")
    pka_path = run_propka_standalone(args.pdb, workdir)
    if pka_path:
        print(f"      pka -> {pka_path.name}")
    else:
        print(f"      (propka3 not on PATH — skipping standalone pKa table;"
              f" pdb2pqr ran PROPKA internally regardless)")

    print(f"[3/4] Parsing PQR")
    atoms, total_q = parse_pqr(pqr_out)
    int_charge = int(round(total_q))
    n_h = sum(1 for a in atoms if a[0] == "H")
    print(f"      {len(atoms)} atoms ({n_h} H), charge sum = {total_q:.4f} → {int_charge:+d}")

    rows = extract_pka_summary(pka_path)
    if rows:
        n_titratable = len(rows)
        n_shifted = sum(1 for r in rows if abs(r["pKa"] - r["model_pKa"]) > 1.0)
        print(f"      titratable residues: {n_titratable}; "
              f"|pKa - model| > 1.0: {n_shifted}")

    xyz_out = mol_dir / f"{out_name}.xyz"
    charge_out = mol_dir / "charge.txt"

    print(f"[4/4] Writing outputs (dry-run={args.dry_run})")
    if args.dry_run:
        print(f"      [DRY RUN] would write {xyz_out} and {charge_out}")
        prev_xyz_atoms = None
        if xyz_out.exists():
            with xyz_out.open() as fh:
                try:
                    prev_xyz_atoms = int(fh.readline().strip())
                except ValueError:
                    pass
        if prev_xyz_atoms is not None:
            delta = len(atoms) - prev_xyz_atoms
            print(f"      existing {xyz_out.name} has {prev_xyz_atoms} atoms; "
                  f"PROPKA output has {len(atoms)} ({delta:+d})")
        return

    # Back up existing files
    for path in (xyz_out, charge_out):
        if path.exists():
            backup = path.with_suffix(path.suffix + ".pre-propka")
            # If a previous backup already exists, suffix the new one with a counter
            i = 1
            while backup.exists():
                backup = path.with_suffix(f"{path.suffix}.pre-propka.{i}")
                i += 1
            shutil.move(str(path), str(backup))
            print(f"      backed up existing {path.name} -> {backup.name}")

    comment = (
        f"PROPKA pH={args.ph} ff={args.ff} "
        f"net_charge={int_charge:+d} atoms={len(atoms)}"
    )
    write_xyz(atoms, xyz_out, comment)
    with charge_out.open("w") as fh:
        fh.write(f"{int_charge}\n")

    print()
    print(f"PROPKA preprocessing complete for {mol_name}")
    print(f"  Atoms:     {len(atoms)} ({n_h} hydrogen)")
    print(f"  Charge:    {int_charge:+d}  -> {charge_out}")
    print(f"  Structure: {xyz_out}")
    print(f"  Workdir:   {workdir}")
    print()
    print(f"Next step (recommended Schmitz GFN2 SP diagnostic on the corrected geometry):")
    print(f"  scripts/xtb_preopt.sh {mol_name} --sp --slurm \\")
    print(f"      --partition bigmem --cpus 36 --mem 0 --time 12:00:00 \\")
    print(f"      --gfn 2 --solvent h2o --threads 4")


if __name__ == "__main__":
    main()
