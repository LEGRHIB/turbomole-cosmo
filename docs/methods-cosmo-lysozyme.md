# Computational details — COSMO / COSMO-RS screening charges (draft methods note)

> Draft for the Methods / Computational Details section. Numbers for the protein-scale
> solute reflect the diagnosed problem and the adopted protocol; insert the final
> converged energy / σ-profile once the mixed-basis run completes.

## Structure preparation and protonation

Solute structures were taken from experimental coordinates where available (hen egg-white
lysozyme from PDB entry 2LYZ; 129 residues, C₆₁₃H₉₆₂N₁₉₃O₁₈₅S₁₀, 1963 atoms) or built from
2D/connectivity data. Protonation states were assigned at the relevant pH with PROPKA,
giving a net molecular charge of +11 for lysozyme at pH 4.6 (7620 electrons). Because
all-electron DFT geometry optimization is intractable at the protein scale, large solutes
were pre-optimized with the GFN-FF force field (as implemented in xtb), preserving the
experimental fold; smaller solutes were optimized at the BP86/def2-TZVP level with COSMO,
following the standard COSMO-RS preparation recipe.

## COSMO single-point calculations

Screening charges were obtained from single-point COSMO calculations in TURBOMOLE 7.8 using
the BP86 exchange–correlation functional, the resolution-of-the-identity approximation for
the Coulomb term (RI-J), an m4 integration grid, and the conductor-like screening model
(COSMO) in the infinite-dielectric (ideal-conductor) limit with the refined ("FINE") cavity
construction, consistent with the BP-TZVPD-FINE parameterization used for the subsequent
COSMO-RS analysis (COSMOtherm). The target level employed the def2-TZVPD basis set, i.e.
def2-TZVP augmented with property-optimized diffuse functions. The SCF was converged to
10⁻⁷ Hartree (`scfconv 7`); for the highly charged protein the orbital occupations were
treated with Fermi smearing on an annealed electronic-temperature schedule (2000 K → 300 K,
scaled by 0.95 per SCF cycle) to stabilize the near-degenerate frontier manifold.

## SCF convergence for the protein-scale solute

For lysozyme (1963 atoms, charge +11; 46 340 def2-TZVPD basis functions) the SCF diverged
catastrophically — density-change norms of order 10¹⁰ and total-energy excursions of order
10⁵ Hartree — under both constant-temperature (300 K) and annealed Fermi-smearing schedules.
The instability was traced to near-linear-dependence of the diffuse-augmented def2-TZVPD
basis on the densely packed folded protein, i.e. a near-singular atomic-orbital overlap
matrix, which the SCF module used (ridft) does not project out. A controlled test isolated
the cause: starting from one and the same converged density, the SCF converged smoothly in
the non-augmented def2-TZVP basis but diverged on the first step once the diffuse functions
were added.

Two measures were therefore adopted. (i) A staged-basis bootstrap: BP86/def2-TZVP COSMO
orbitals were first converged and then projected onto the larger basis (via the `use`
facility of TURBOMOLE's `define`) to furnish the SCF start vectors. (ii) A mixed basis in
which the diffuse functions were removed from hydrogen (def2-TZVP on H, def2-TZVPD on
C/N/O/S), which eliminates the dominant contribution to the linear dependence — the strongly
overlapping diffuse H functions of a hydrogen-dense protein — while retaining the diffuse
augmentation on the electronegative atoms that dominate the COSMO screening surface. These
measures target the identified cause directly (basis conditioning rather than the SCF
initial guess), and provide a route to a def2-TZVPD-quality screening-charge file for a
solute well beyond the ~1000-atom range over which whole-structure COSMO-RS is commonly
applied. The SCF was made robust to walltime limits by checkpointing the orbitals and
restarting from the last saved set.

## Key references (verify formatting for the target journal)

- COSMO: A. Klamt, G. Schüürmann, *J. Chem. Soc., Perkin Trans. 2* **1993**, 799.
- COSMO-RS: A. Klamt, *J. Phys. Chem.* **1995**, *99*, 2224; F. Eckert, A. Klamt, *AIChE J.* **2002**, *48*, 369.
- def2 basis sets: F. Weigend, R. Ahlrichs, *Phys. Chem. Chem. Phys.* **2005**, *7*, 3297.
- Property-optimized diffuse (def2-TZVPD): D. Rappoport, F. Furche, *J. Chem. Phys.* **2010**, *133*, 134105.
- GFN-FF: S. Spicher, S. Grimme, *Angew. Chem. Int. Ed.* **2020**, *59*, 15665.
- PROPKA: M. H. M. Olsson et al., *J. Chem. Theory Comput.* **2011**, *7*, 525.
- TURBOMOLE: S. G. Balasubramani et al., *J. Chem. Phys.* **2020**, *152*, 184107.
