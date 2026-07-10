"""Configuration: YAML file + env overrides -> validated dataclasses.

Nothing environment-specific is hardcoded. Load order:
  dataclass defaults  ->  YAML file (if given)  ->  env overrides.

Env overrides: COSMORS_<SECTION>_<KEY> for any scalar field, plus a few legacy
names from config.sh (TURBOMOLE_ROOT, TURBOMOLE_SYSNAME, ACCOUNT).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field, fields, is_dataclass, asdict
from typing import Any, List, Optional

try:
    import yaml
except ImportError:  # pragma: no cover - pyyaml is a core dep
    yaml = None


class ConfigError(Exception):
    """Raised for unrecoverable configuration problems."""


# --------------------------------------------------------------------------- #
# Sections
# --------------------------------------------------------------------------- #
@dataclass
class Compound:
    name: str = "bombesin"
    charge: Optional[int] = None
    input_path: Optional[str] = None   # SDF / xyz / PDB (null -> molecules/<name>/<name>.sdf)
    smiles: Optional[str] = None        # SMILES string (overrides input_path)


@dataclass
class Paths:
    turbomole_root: str = ""
    turbomole_sysname: str = "em64t-unknown-linux-gnu"
    cosmoconf_bin: str = "cosmoconf"
    cosmotherm_bin: str = "cosmotherm"
    cosmotherm_env: Optional[str] = None
    ct_param_path: Optional[str] = None
    ct_license_dir: Optional[str] = None
    ct_cosmo_db_path: Optional[str] = None


@dataclass
class Theory:
    functional: str = "b-p"
    basis: str = "def2-TZVPD"
    grid: str = "m4"
    cavity: str = "fine"
    ri: bool = True
    cosmo_epsilon: str = "infinity"


@dataclass
class DFT:
    backend: str = "cosmoconf"   # cosmoconf (orchestrates cascade) | turbomole (self-contained)
    memory_mb: int = 1000
    geometry_opt: bool = False


@dataclass
class Ctd:
    default: str = "BP_TZVPD_FINE_25.ctd"
    licensed: List[str] = field(default_factory=lambda: ["BP_TZVPD_FINE_25.ctd"])


@dataclass
class Conformers:
    rmsd_cutoff: float = 1.0
    energy_window: float = 6.0
    max_conformers: int = 40
    multi_sdf: Optional[str] = None     # pre-made multi-conformer SDF to ingest (bypasses MD)


@dataclass
class MD:
    enabled: bool = True
    engine: str = "openmm"
    method: str = "high_temp"
    temperature_K: float = 500.0
    n_frames: int = 200
    cluster_rmsd: float = 1.5


@dataclass
class CosmoTherm:
    temperature_C: float = 25.0
    property: str = "relative_solubility"
    reference_compound: str = "water"
    solvent_panel: str = "config/solvent_panel.yaml"
    force_qspr: bool = True
    relative: bool = True
    single_conformer_threshold: float = 0.95   # sensitivity gate: >this in every phase


@dataclass
class Slurm:
    cluster: str = "wice"
    partition: str = "batch"
    account: str = "lp_cheme_cfd"
    fine: dict = field(default_factory=lambda: {"cpus": 16, "mem": "120000M", "time": "72:00:00"})
    bigmem: dict = field(default_factory=lambda: {"cpus": 72, "mem": "2000000M", "time": "72:00:00"})


@dataclass
class Run:
    workdir: str = "work"
    resume: bool = True


@dataclass
class Config:
    compound: Compound = field(default_factory=Compound)
    paths: Paths = field(default_factory=Paths)
    theory: Theory = field(default_factory=Theory)
    dft: DFT = field(default_factory=DFT)
    ctd: Ctd = field(default_factory=Ctd)
    conformers: Conformers = field(default_factory=Conformers)
    md: MD = field(default_factory=MD)
    cosmotherm: CosmoTherm = field(default_factory=CosmoTherm)
    slurm: Slurm = field(default_factory=Slurm)
    run: Run = field(default_factory=Run)

    def to_dict(self) -> dict:
        return asdict(self)


# Only relative solubility is supported for now (per the project plan).
SUPPORTED_PROPERTIES = {"relative_solubility"}
IDEAL_CONDUCTOR = {"infinity", "inf"}


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #
def _coerce(text: str) -> Any:
    """Coerce an env-var string into bool / int / float / None where sensible."""
    low = text.strip()
    if low.lower() in ("true", "false"):
        return low.lower() == "true"
    if low.lower() in ("none", "null", ""):
        return None
    try:
        return int(low)
    except ValueError:
        pass
    try:
        return float(low)
    except ValueError:
        return text


def _build(dc_type, data):
    """Build a dataclass from a dict, ignoring unknown keys (returned for warning)."""
    data = data or {}
    known = {f.name for f in fields(dc_type)}
    kwargs = {k: v for k, v in data.items() if k in known}
    unknown = [k for k in data if k not in known]
    return dc_type(**kwargs), unknown


def _apply_env(cfg: Config) -> None:
    """Overlay COSMORS_<SECTION>_<KEY> env vars + a few legacy config.sh names."""
    for section_name, section in vars(cfg).items():
        if not is_dataclass(section):
            continue
        for f in fields(section):
            env = f"COSMORS_{section_name.upper()}_{f.name.upper()}"
            if env in os.environ:
                setattr(section, f.name, _coerce(os.environ[env]))
    # legacy config.sh names
    if os.environ.get("TURBOMOLE_ROOT"):
        cfg.paths.turbomole_root = os.environ["TURBOMOLE_ROOT"]
    if os.environ.get("TURBOMOLE_SYSNAME"):
        cfg.paths.turbomole_sysname = os.environ["TURBOMOLE_SYSNAME"]
    if os.environ.get("ACCOUNT"):
        cfg.slurm.account = os.environ["ACCOUNT"]


def load_config(path: Optional[str] = None, apply_env: bool = True) -> Config:
    """Load config from an optional YAML path, then overlay env vars."""
    data: dict = {}
    if path:
        if yaml is None:
            raise ConfigError("pyyaml is required to read a YAML config file")
        with open(path) as fh:
            data = yaml.safe_load(fh) or {}

    warnings: List[str] = []
    cfg = Config()
    for name, dc_type in (
        ("compound", Compound), ("paths", Paths), ("theory", Theory), ("dft", DFT),
        ("ctd", Ctd),
        ("conformers", Conformers), ("md", MD), ("cosmotherm", CosmoTherm),
        ("slurm", Slurm), ("run", Run),
    ):
        obj, unknown = _build(dc_type, data.get(name))
        setattr(cfg, name, obj)
        warnings += [f"config[{name}]: unknown key '{k}' ignored" for k in unknown]

    if apply_env:
        _apply_env(cfg)
    cfg._load_warnings = warnings  # type: ignore[attr-defined]
    return cfg


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #
def validate(cfg: Config):
    """Return (errors, warnings). Errors block a real run; warnings are advisory.

    Enforces the two invariants the plan requires:
      * COSMO epsilon = infinity (ideal conductor) — never solvent-specific.
      * the default .ctd is among the licensed set.
    """
    errors: List[str] = []
    warnings: List[str] = list(getattr(cfg, "_load_warnings", []))

    if str(cfg.theory.cosmo_epsilon).lower() not in IDEAL_CONDUCTOR:
        errors.append(
            f"theory.cosmo_epsilon must be 'infinity' (ideal conductor); "
            f"got {cfg.theory.cosmo_epsilon!r}"
        )
    if cfg.ctd.default not in cfg.ctd.licensed:
        errors.append(
            f"ctd.default {cfg.ctd.default!r} is not in ctd.licensed {cfg.ctd.licensed}"
        )
    if cfg.cosmotherm.property not in SUPPORTED_PROPERTIES:
        errors.append(
            f"cosmotherm.property {cfg.cosmotherm.property!r} unsupported; "
            f"expected one of {sorted(SUPPORTED_PROPERTIES)}"
        )
    if cfg.conformers.rmsd_cutoff <= 0:
        errors.append("conformers.rmsd_cutoff must be > 0 (the RMSD gate is mandatory)")
    if cfg.md.engine not in ("openmm", "gromacs"):
        errors.append(f"md.engine {cfg.md.engine!r} must be 'openmm' or 'gromacs'")
    if cfg.dft.backend not in ("cosmoconf", "turbomole"):
        errors.append(f"dft.backend {cfg.dft.backend!r} must be 'cosmoconf' or 'turbomole'")

    return errors, warnings


def require_runtime(cfg: Config) -> List[str]:
    """Extra checks needed only for a REAL (non-mock) run: binaries/paths present."""
    missing: List[str] = []
    if not cfg.paths.turbomole_root or not os.path.isdir(cfg.paths.turbomole_root):
        missing.append(f"TURBOMOLE root not found: {cfg.paths.turbomole_root!r}")
    for label, p in (
        ("ct_param_path (CDIR)", cfg.paths.ct_param_path),
        ("ct_license_dir (LDIR)", cfg.paths.ct_license_dir),
        ("ct_cosmo_db_path (FDIR)", cfg.paths.ct_cosmo_db_path),
    ):
        if not p:
            missing.append(f"{label} is not set")
    return missing
