from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional

from .config import Config, ConfigError, Machine, config_path, load_config


def print_machines(cfg: Config, machines: List[Machine]) -> None:
    print(f"config: {cfg.path}{'' if cfg.path and cfg.path.exists() else ' (not found)'}")
    name_w = max(len(m.name) for m in machines)
    for m in machines:
        print(f"  {m.name:<{name_w}}  {m.transport:<5}  {m.address:<24}")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="mmtop", description="Monitor GPUs, disks and network across machines.")
    ap.add_argument("-c", "--config", type=Path, help=f"config file (default: {config_path()})")
    ap.add_argument("-i", "--interval", type=float, help="seconds between samples")
    ap.add_argument("--list", action="store_true", help="list configured machines and exit")
    args = ap.parse_args(argv)

    try:
        cfg = load_config(args.config)
        if not cfg.machines:
            raise ConfigError(f"no machines configured in {cfg.path}")
        if args.interval is not None:
            if not 0.2 <= args.interval <= 60:
                raise ConfigError("--interval must be between 0.2 and 60")
            cfg.interval = args.interval
        machines = list(cfg.machines)

        if args.list:
            print_machines(cfg, machines)
            return 0
    except ConfigError as e:
        print(f"mmtop: {e}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130

    from .app import MmtopApp

    MmtopApp(cfg, machines).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
