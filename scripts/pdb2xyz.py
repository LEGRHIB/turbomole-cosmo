#!/usr/bin/env python3
"""Convert a PDB file to XYZ format. No external dependencies."""

import sys

def pdb_to_xyz(pdb_path, xyz_path):
    atoms = []
    with open(pdb_path) as f:
        for line in f:
            if line.startswith(("ATOM", "HETATM")):
                # PDB fixed-column format:
                #   31-38  x coordinate (Angstroms)
                #   39-46  y coordinate
                #   47-54  z coordinate
                #   77-78  element symbol
                x = float(line[30:38])
                y = float(line[38:46])
                z = float(line[46:54])
                # Element from columns 77-78; fallback to atom name col 12-16
                element = line[76:78].strip() if len(line) >= 78 else ""
                if not element:
                    element = line[12:16].strip().lstrip("0123456789")[:2]
                    if len(element) > 1:
                        element = element[0].upper() + element[1].lower()
                atoms.append((element, x, y, z))

    if not atoms:
        print(f"ERROR: no ATOM/HETATM records found in {pdb_path}", file=sys.stderr)
        sys.exit(1)

    with open(xyz_path, "w") as f:
        f.write(f"{len(atoms)}\n")
        f.write(f"Converted from {pdb_path}\n")
        for el, x, y, z in atoms:
            f.write(f"{el:2s}  {x:14.8f}  {y:14.8f}  {z:14.8f}\n")

    print(f"Converted {len(atoms)} atoms: {pdb_path} -> {xyz_path}")

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} input.pdb output.xyz", file=sys.stderr)
        sys.exit(2)
    pdb_to_xyz(sys.argv[1], sys.argv[2])
