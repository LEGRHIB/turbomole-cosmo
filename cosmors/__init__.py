"""cosmors — conformer-resolved COSMO-RS pipeline.

Independent, additive package layered on the existing turbomole-cosmo repo. It does
not modify or call the existing scripts/*.sh; the SCF backend is self-contained.

Stages: 0 input -> 4 MD front-end -> 1 conformer gen/ingest -> RMSD gate -> 2 DFT/COSMO
(COSMOconf-orchestrated) -> 3 COSMOtherm (relative solubility) -> sensitivity report.

In this sandbox every stage runs in --dry-run/--mock; the commercial binaries
(TURBOMOLE, COSMOconf, COSMOtherm) run only on the workstation/HPC.
"""

__version__ = "0.1.0"
