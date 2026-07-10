# cosmors — conformer-resolved COSMO-RS pipeline

From a single solute to **conformer-resolved COSMO-RS relative solubility**, with a
data-driven decision on whether conformational averaging matters. Independent of and
additive to the legacy single-geometry workflow (repo-root `README.md` /
`docs/workflow.md`); nothing there is modified or called. Scientific/operational
detail: [`docs/conformer-workflow.md`](../docs/conformer-workflow.md).

## Install

```bash
# core (config, CLI, Stages 0/1/3, RMSD gate, sensitivity, sigma-profile plots)
pip install -r requirements.txt          # or: conda env create -f environment.yml
pip install -e .                          # exposes the `cosmors` command

# optional, only where used:
#   openmm        Stage 4 MD front-end (or conda-forge openmm)
#   turbomoleio   HPC TURBOMOLE `define` automation (heavy: pulls pymatgen)
```

RDKit does the 3D/clustering/SDF/AlphaFold work; the core needs only pyyaml + rdkit +
numpy (matplotlib for σ-profile plots).

## Quickstart (sandbox)

```bash
cosmors validate-config --config config/config.template.yaml
cosmors --config config/bombesin.yaml --mock    run     # full pipeline, synthetic binaries
cosmors --config config/bombesin.yaml --dry-run run     # print the real HPC commands, write nothing
cosmors --config config/bombesin.yaml --mock    dft     # a single stage
```

Stages: `input · md · confgen · cluster · dft · cosmotherm · sensitivity`.

## Sandbox vs HPC

The commercial binaries (TURBOMOLE, COSMOconf, COSMOtherm) are license-locked and run
only on the cluster/workstation. Everything else is open-source and runs anywhere.

| runs anywhere (real) | cluster-only (mock/dry-run here) |
|---|---|
| Stage 0 input (incl. AlphaFold intake) | Stage 2 SCF: `define` / `cosmoprep` / `ridft` |
| Stage 1 ingest, RMSD gate | Stage 3 COSMOtherm execution |
| Stage 3 input builder, Stage 4 frame clustering | COSMOconf orchestration |
| sensitivity report, σ-profile plots | (Stage 4 OpenMM MD runs anywhere if installed) |

* `--mock` — cluster-only steps emit clearly-labelled synthetic artifacts (`.mock.`
  files / MOCK banners); **no scientific numbers are fabricated for real molecules**.
* `--dry-run` — every stage prints the exact command it would run and writes nothing.

## Running on the cluster

1. Copy `config/config.template.yaml` → `config/config.yaml` and fill in `paths.*`
   (TURBOMOLE root, COSMOtherm `.ctd` / license / COSMObase dirs).
2. `cosmors --config config/config.yaml --dry-run run` to preview every command.
3. `cosmors --config config/config.yaml run` (no `--mock`):
   - Stage 2 (`dft.backend: turbomole`) runs `x2t → define → cosmoprep → ridft` per
     conformer, or drives COSMOconf (`dft.backend: cosmoconf`);
   - Stage 3 writes the AUTOC inputs + `runme.sh`; run `bash work/<mol>/cosmotherm/runme.sh`;
   - `cosmors sensitivity` parses the per-phase weights into the verdict.

Every `.cosmo` is generated at **ε = ∞ (ideal conductor)** — enforced in code; a
solvent-specific `.cosmo` is refused.

## The MD decision (Stage 4)

Run the cheap conformers first, let COSMOtherm weight them, and read the sensitivity
report:

- **single-conformer sufficient** — one conformer > `single_conformer_threshold` (0.95)
  in *every* phase → MD won't change the ranking; you're done.
- **conformers matter — dominant flips / spread** → enable the MD front-end
  (`md.enabled: true`) to search more conformers; DFT re-optimises them and COSMOtherm
  reweights. MD only *proposes* geometries — it never sets the weights.

## Config knobs

`theory.cosmo_epsilon` (must be `infinity`) · `ctd.default` / `ctd.licensed` ·
`dft.backend` (`cosmoconf`|`turbomole`) · `conformers.rmsd_cutoff` / `energy_window` /
`max_conformers` · `md.*` · `cosmotherm.property` (`relative_solubility`) /
`solvent_panel` / `single_conformer_threshold`. Any scalar is overridable by
`COSMORS_<SECTION>_<KEY>` env vars.

## Tests

```bash
python -m pytest -q          # 53 tests, all sandbox-safe (no binaries)
```

## Layout

```
cosmors/
  config.py models.py workdir.py cli.py stages.py
  stage0_input.py af_intake.py          # input + AlphaFold intake
  stage1_confgen.py cluster.py          # ingest + enforced RMSD gate
  stage2_dft/                           # define/cosmoprep gen, eps=inf check, driver
  stage3_cosmotherm/                    # AUTOC input builder + runner
  parse.py sensitivity.py               # weights -> decision gate
  stage4_md/                            # OpenMM/GROMACS -> frames -> reps
  sigma_profile.py                      # .cosmo sigma-profile plotting
config/  tests/  pyproject.toml
```
