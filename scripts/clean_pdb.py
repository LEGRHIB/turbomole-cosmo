#!/usr/bin/env python3
"""Clean a PDB file: keep only one copy of the molecule, remove waters and ions.

Handles alternate conformers (keeps highest-occupancy or 'A' conformer),
filters CONECT records to only reference surviving atoms, and removes
crystallization artifacts.

Usage:
    python3 clean_pdb.py input.pdb output.pdb [--chains A,C]

Default: keeps chains A and C, removes HOH, ACT, CL ions, etc.
"""

import sys

# Residues to always remove (waters, common ions, crystallization artifacts)
REMOVE_RESIDUES = {
    "HOH", "WAT", "ACT", "SO4", "PO4", "GOL", "EDO", "NAG",
    "MES", "TRS", "BME", "DMS", "FMT", "IOD",
}
# Standalone ion residues (not covalently bound)
REMOVE_ION_RESIDUES = {"CL", "NA", "MG", "CA", "ZN", "K", "FE", "MN", "CU", "CO", "NI", "BR"}


def clean_pdb(input_path, output_path, keep_chains=None):
    """Clean a PDB: select chains, remove waters/ions, resolve alt conformers,
    filter CONECT records, and write a self-consistent output PDB."""

    kept_serials = set()       # atom serial numbers that survive filtering
    atom_lines = []            # surviving ATOM/HETATM lines
    conect_lines = []          # all CONECT lines (filtered later)
    header_lines = []          # HEADER, TITLE, REMARK lines to preserve

    removed_water = 0
    removed_ion = 0
    removed_chain = 0
    removed_altloc = 0

    with open(input_path) as fin:
        for line in fin:
            record = line[:6].strip()

            # Collect CONECT records for later filtering
            if record == "CONECT":
                conect_lines.append(line)
                continue

            # Pass through header metadata
            if record in ("HEADER", "TITLE", "REMARK", "LINK"):
                header_lines.append(line)
                continue

            # Only process ATOM / HETATM
            if record not in ("ATOM", "HETATM"):
                continue

            resname = line[17:20].strip()
            chain = line[21] if len(line) > 21 else " "
            altloc = line[16] if len(line) > 16 else " "
            element = line[76:78].strip() if len(line) >= 78 else ""

            # --- Filter: remove waters and crystallization artifacts ---
            if resname in REMOVE_RESIDUES:
                removed_water += 1
                continue

            # --- Filter: remove standalone ionic species ---
            # CL as its own residue = chloride ion; CL inside OMZ/OMY = covalent
            if resname in REMOVE_ION_RESIDUES:
                removed_ion += 1
                continue

            # --- Filter: chain selection ---
            if keep_chains and chain not in keep_chains:
                removed_chain += 1
                continue

            # --- Filter: alternate conformers ---
            # Keep blank altloc (no disorder) or 'A' (highest occupancy by convention)
            if altloc not in (" ", "", "A"):
                removed_altloc += 1
                continue

            # If this is altloc 'A', clear the flag so OpenBabel doesn't choke
            if altloc == "A":
                line = line[:16] + " " + line[17:]

            serial = int(line[6:11].strip())
            kept_serials.add(serial)
            atom_lines.append(line)

    # --- Filter CONECT records: only keep bonds where ALL referenced atoms survive ---
    kept_conect = []
    for line in conect_lines:
        # CONECT format: columns 7-11 = origin, then 12-16, 17-21, ... = bonded
        tokens = line[6:].split()
        try:
            serials_in_record = [int(t) for t in tokens]
        except ValueError:
            continue
        if all(s in kept_serials for s in serials_in_record):
            kept_conect.append(line)

    # --- Write output ---
    with open(output_path, "w") as fout:
        for line in header_lines:
            fout.write(line)
        for line in atom_lines:
            fout.write(line)
        for line in kept_conect:
            fout.write(line)
        fout.write("END\n")

    print(f"Kept atoms:          {len(atom_lines)}")
    print(f"Removed waters:      {removed_water}")
    print(f"Removed ions:        {removed_ion}")
    print(f"Removed other chain: {removed_chain}")
    print(f"Removed alt conformer: {removed_altloc}")
    print(f"CONECT records kept: {len(kept_conect)} / {len(conect_lines)}")
    print(f"Output: {output_path}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} input.pdb output.pdb [--chains A,C]")
        sys.exit(2)

    input_pdb = sys.argv[1]
    output_pdb = sys.argv[2]

    chains = None
    for i, arg in enumerate(sys.argv):
        if arg == "--chains" and i + 1 < len(sys.argv):
            chains = set(sys.argv[i + 1].split(","))

    clean_pdb(input_pdb, output_pdb, chains)
