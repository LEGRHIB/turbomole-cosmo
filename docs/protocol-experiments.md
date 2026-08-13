# Protocol experiments — the def2-TZVPD convergence ladder (lysozyme)

Record of the SCF protocols built between June and July 2026 to get a
**whole-molecule `BP/def2-TZVPD + FINE` `.cosmo` for lysozyme (+11, 46 340 basis
functions)**, and why none of them succeeded. The protocol directories were
removed from `protocols/` on 2026-08-13; this file is what they were for.

Kept in the repo are the four protocols that are still in use — see
[`workflow.md`](workflow.md) for how they compose.

## The problem

`def2-TZVPD`'s diffuse functions on a folded protein make the AO overlap matrix
**near-singular**. TURBOMOLE's SCF modules (`ridft`/`dscf`) have no
linear-dependence projection — only `riper`/`lsdiag`, which are periodic-oriented
— so a cold EHT guess detonates the density: `NORM[dD]` ≈ 10¹⁰, one- and
two-electron energies in the millions, divergence on iteration 1.

This is distinct from the small-gap problem that Fermi smearing solves. Lysozyme
has both: the gap fluctuates around kT(300 K) ≈ 1 mHa, which is what the annealed
Fermi schedule was built for (jobs 66867524 / 66871359, 2026-05-22, +200k Eh
blowups at cycles 6–25). Fixing the gap problem did not fix the conditioning
problem.

## What was tried

| Date | Protocol | Intervention | Outcome |
|------|----------|--------------|---------|
| 06-10 | `BP-TZVPD-FINE-ANNEAL` | annealed Fermi 2000 K → 300 K, 0.95/cycle, on a cold EHT guess | **kept** — solves small-gap divergence, not the singular overlap |
| 06-11 | `BP-TZVP-FINE-ANNEAL` | drop the diffuse functions entirely (def2-TZVP), well-conditioned overlap | **kept** — converges; source of the delivered lysozyme `.cosmo` |
| 06-14 | `BP-TZVPD-FINE-ANNEAL-BOOT` | Stage B: project Stage A's converged MOs into TZVPD via `define`'s `use` | **kept** — the escalation path for future systems; did not converge lysozyme |
| 06-16 | `BP-TZVPD-MIX-FINE-ANNEAL-BOOT` | mixed basis: def2-TZVPD on C/N/O/S, def2-TZVP on H — remove the diffuse-H linear dependence | removed — did not converge |
| 06-17 | `BP-TZVPD-MIXHC-FINE-ANNEAL-BOOT` | diffuse only on N/O/S (TZVP on H **and** C) — strip the dense carbon-framework diffuse functions still driving the oscillation | removed — did not converge |
| 06-22 | `BP-TZVPD-FINE-ANNEAL-HARD-BOOT` | force it through: `$scfiterlimit 999`, `$scfdamp start=5.000 step=0.050 min=0.500`, `$scforbitalshift automatic=1.0` | removed — did not converge |
| 07-06 | `BP-TZVPD-FINE-ANNEAL-SCFTOL` / `-SCFTOL-BOOT` | `$scftol 1d-15` (BIOVIA's recommendation for diffuse-function SCF divergence): keep the small long-range two-electron integrals default screening discards. Cold and projected flavours | removed — did not converge |
| 07-07 | `BP-TZVPD-FINE-PLAIN` | control experiment: plain TURBOMOLE defaults, no Fermi / shift / `$scftol`, only `$scfiterlimit 300` — test whether our own tuning caused the divergence | removed — did not converge |

Outcomes are recorded as "did not converge" on two grounds: each rung was
superseded by the next within days, and no TZVPD `.cosmo` for lysozyme exists on
the cluster. Per-rung job IDs and the cycle at which each died are in the Wice
job logs and have not been transcribed here.

## What was delivered instead

`BP-TZVP-FINE-ANNEAL` — the Stage A level, no diffuse functions. Because
`scripts/cosmotherm_screen.sh` selects the COSMOtherm parameterization from the
protocol prefix (`BP-TZVP-*` → `BP_TZVP_25.ctd` + BP-TZVP-COSMO database), the
lysozyme screen is internally consistent: TZVP `.cosmo` against the TZVP
parameterization.

It is **not** on the same footing as the other solutes. Vancomycin and bombesin
were computed at `BP-TZVPD-FINE` and screened against `BP_TZVPD_FINE_25.ctd`.
Lysozyme's `log10(x_RS)` therefore comes from a different parameterization and a
different solvent database, and should not be tabulated next to theirs without
that stated.

## Recovering a removed protocol

All files are preserved in git:

```bash
git show protocol-ladder-2026-07:protocols/BP-TZVPD-FINE-ANNEAL-HARD-BOOT/define.in
git checkout protocol-ladder-2026-07 -- protocols/BP-TZVPD-FINE-ANNEAL-HARD-BOOT
```

The `*HARD*`, `*SCFTOL*` and `*PLAIN*` branches of `scripts/_tune_scf.sh` were
removed in the same commit and are recoverable the same way. Note that restoring
a directory alone is not enough — the SCF behaviour lived in those name-matched
branches, not in the protocol files, which were byte-identical to their siblings.

## If you pick this up again

Untried, roughly in order of expected value:

1. **Cheaper geometry, same question** — reproduce the divergence on a smaller
   diffuse-heavy system (a 300–500 atom peptide) so a rung costs minutes, not a
   72 h bigmem job.
2. **Basis-set linear dependence handling** — TURBOMOLE has no projection in
   `ridft`; a code with canonical-orthogonalisation thresholds (ORCA
   `CanOrthNorm`, Psi4) would say whether the overlap's smallest eigenvalue is
   the whole story.
3. **`def2-TZVPPD` / minimally augmented sets** — the augmentation on H is the
   suspected trigger; a set with fewer diffuse primitives on H is closer to the
   COSMOtherm parameterization than dropping diffuse functions altogether.
4. **Accept TZVP and quantify the error** — compute both levels on vancomycin and
   bombesin, and report the TZVP→TZVPD shift in log₁₀(x_RS) as a systematic
   correction with an uncertainty. This is the option that needs no new SCF
   breakthrough.
