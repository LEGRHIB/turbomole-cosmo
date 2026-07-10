"""Command-line interface.

    cosmors validate-config [--config F]
    cosmors run            [--mock | --dry-run] [--config F] [--compound C] ...
    cosmors <stage>        [--mock | --dry-run] ...     # one stage only

Stages: input, md, confgen, cluster, dft, cosmotherm, sensitivity.

In P1 only --mock and --dry-run are supported (no commercial binaries in the
sandbox); a plain run without either flag is refused with a clear message.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional

from . import __version__
from .config import load_config, validate, require_runtime, ConfigError
from .stages import PIPELINE, STAGES
from .workdir import WorkDir

_DEFAULT_CONFIGS = ["config/config.yaml", "config/config.template.yaml"]


def _find_config(explicit: Optional[str]) -> Optional[str]:
    if explicit:
        return explicit
    for cand in _DEFAULT_CONFIGS:
        if Path(cand).is_file():
            return cand
    return None


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cosmors", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--version", action="version", version=f"cosmors {__version__}")
    p.add_argument("--config", help="YAML config (default: config/config.yaml or template)")
    p.add_argument("--compound", help="override compound.name")
    p.add_argument("--workdir", help="override run.workdir root")
    p.add_argument("--mock", action="store_true", help="run transparent mock stages")
    p.add_argument("--dry-run", action="store_true", help="print intended HPC commands; write nothing")
    p.add_argument("--force", action="store_true", help="ignore .done stamps and rerun")
    p.add_argument("--no-resume", action="store_true", help="do not skip completed stages")

    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("validate-config", help="load + validate the config, then exit")
    sub.add_parser("run", help="run the full pipeline")
    for key, _ in PIPELINE:
        sub.add_parser(key, help=f"run only the '{key}' stage")
    return p


def _load(args) -> "Config":  # type: ignore[name-defined]
    cfg = load_config(_find_config(args.config))
    if args.compound:
        cfg.compound.name = args.compound
    if args.workdir:
        cfg.run.workdir = args.workdir
    return cfg


def _print_config_status(cfg) -> int:
    errors, warnings = validate(cfg)
    for w in warnings:
        print(f"  warning: {w}")
    for e in errors:
        print(f"  ERROR:   {e}")
    runtime_missing = require_runtime(cfg)
    if runtime_missing:
        print("  (real-run prerequisites, fine to ignore for --mock/--dry-run:)")
        for m in runtime_missing:
            print(f"    - {m}")
    if errors:
        print("config INVALID")
        return 2
    print("config OK"
          + (f" ({len(warnings)} warning(s))" if warnings else ""))
    return 0


def _run_stages(cfg, args, keys: List[str]) -> int:
    errors, _ = validate(cfg)
    if errors:
        print("Config invalid — run `cosmors validate-config`:", file=sys.stderr)
        for e in errors:
            print(f"  ERROR: {e}", file=sys.stderr)
        return 2

    wd = WorkDir(cfg.run.workdir, cfg.compound.name)
    mode = "dry-run" if args.dry_run else ("mock" if args.mock else "real")
    print(f"cosmors {__version__}  compound={cfg.compound.name}  "
          f"mode={mode}  workdir={wd.base}")

    rc = 0
    if args.dry_run:
        for key in keys:
            result = STAGES[key](cfg, wd.path(key), wd=wd, mock=False, dry_run=True)
            print(result)
            if not result.ok:
                rc = 1
                break
        return rc

    resume = not args.no_resume
    for key in keys:
        fn = STAGES[key]
        result = wd.run_stage(
            key,
            lambda d, fn=fn: fn(cfg, d, wd=wd, mock=args.mock, dry_run=False),
            resume=resume, force=args.force,
        )
        print(result)
        if not result.ok:
            rc = 1
            break
    return rc


def main(argv: Optional[List[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        cfg = _load(args)
    except (ConfigError, FileNotFoundError) as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2

    if args.command == "validate-config":
        return _print_config_status(cfg)
    if args.command == "run":
        return _run_stages(cfg, args, [k for k, _ in PIPELINE])
    if args.command in STAGES:
        return _run_stages(cfg, args, [args.command])

    print(f"unknown command: {args.command}", file=sys.stderr)
    return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
