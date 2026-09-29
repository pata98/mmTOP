from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

METRICS = ("gpu", "gpu_procs", "cpu_mem", "disk_usage", "disk_io", "net", "ib")
METRIC_LABELS = {
    "gpu": "GPU (util, memory, temperature, power, clocks)",
    "gpu_procs": "GPU processes",
    "cpu_mem": "CPU / RAM",
    "disk_usage": "Disk usage",
    "disk_io": "Disk I/O",
    "net": "Network",
    "ib": "InfiniBand",
}
DEFAULT_METRICS = ["gpu", "gpu_procs", "cpu_mem", "disk_usage", "net"]
TRANSPORTS = ("ssh", "local")


class ConfigError(Exception):
    pass


@dataclass
class Machine:
    name: str
    host: Optional[str] = None
    transport: str = "ssh"
    metrics: Optional[List[str]] = None
    python: str = "python3"
    ssh_options: List[str] = field(default_factory=list)

    @property
    def address(self) -> str:
        if self.transport == "local":
            return "local"
        return self.host or ""


@dataclass
class Config:
    interval: float = 1.0
    history_seconds: int = 300
    default_metrics: List[str] = field(default_factory=lambda: list(DEFAULT_METRICS))
    exclude_mounts: List[str] = field(default_factory=list)
    exclude_ifaces: List[str] = field(default_factory=list)
    ssh_options: List[str] = field(default_factory=list)
    machines: List[Machine] = field(default_factory=list)
    path: Optional[Path] = None

    def machine(self, name: str) -> Optional[Machine]:
        for m in self.machines:
            if m.name == name:
                return m
        return None


@dataclass
class Selection:
    """machines is the monitor list; metrics maps each of those names to the metrics to collect."""

    machines: List[str]
    metrics: Dict[str, List[str]]


def config_path() -> Path:
    env = os.environ.get("MMTOP_CONFIG")
    if env:
        return Path(env).expanduser()
    project_root = Path(__file__).resolve().parents[2]
    return project_root / ".config" / "config.toml"


def validate_metrics(metrics: Any, where: str) -> List[str]:
    if not isinstance(metrics, list) or not all(isinstance(m, str) for m in metrics):
        raise ConfigError(f"{where}: metrics must be a list of strings")
    unknown = [m for m in metrics if m not in METRICS]
    if unknown:
        raise ConfigError(f"{where}: unknown metrics {unknown}; available: {', '.join(METRICS)}")
    return [m for m in METRICS if m in metrics]


def _str_list(value: Any, where: str) -> List[str]:
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ConfigError(f"{where} must be a list of strings")
    return list(value)


def _parse_machine(raw: Dict[str, Any], index: int) -> Machine:
    where = f"machines[{index}]"
    if not isinstance(raw, dict):
        raise ConfigError(f"{where} must be a table")
    name = raw.get("name")
    if not isinstance(name, str) or not name:
        raise ConfigError(f"{where}: 'name' is required")
    where = f"machine '{name}'"
    transport = raw.get("transport", "ssh")
    if transport not in TRANSPORTS:
        raise ConfigError(f"{where}: transport must be one of {', '.join(TRANSPORTS)}")
    host = raw.get("host")
    if transport == "ssh" and not isinstance(host, str):
        raise ConfigError(f"{where}: 'host' is required")
    metrics = raw.get("metrics")
    known = {"name", "host", "transport", "metrics", "python", "ssh_options"}
    extra = set(raw) - known
    if extra:
        raise ConfigError(f"{where}: unknown keys {sorted(extra)}")
    return Machine(
        name=name,
        host=host,
        transport=transport,
        metrics=validate_metrics(metrics, where) if metrics is not None else None,
        python=raw.get("python", "python3"),
        ssh_options=_str_list(raw.get("ssh_options", []), f"{where}: ssh_options"),
    )


def parse_config(data: Dict[str, Any], path: Optional[Path] = None) -> Config:
    cfg = Config(path=path)
    interval = data.get("interval", cfg.interval)
    if not isinstance(interval, (int, float)) or not 0.2 <= interval <= 60:
        raise ConfigError("interval must be a number between 0.2 and 60")
    cfg.interval = float(interval)
    history = data.get("history_seconds", cfg.history_seconds)
    if not isinstance(history, int) or history < 10:
        raise ConfigError("history_seconds must be an integer >= 10")
    cfg.history_seconds = history
    if "default_metrics" in data:
        cfg.default_metrics = validate_metrics(data["default_metrics"], "default_metrics")
    cfg.exclude_mounts = _str_list(data.get("exclude_mounts", []), "exclude_mounts")
    cfg.exclude_ifaces = _str_list(data.get("exclude_ifaces", []), "exclude_ifaces")
    cfg.ssh_options = _str_list(data.get("ssh_options", []), "ssh_options")
    machines = data.get("machines", [])
    if not isinstance(machines, list):
        raise ConfigError("'machines' must be an array of tables ([[machines]])")
    seen = set()
    for i, raw in enumerate(machines):
        m = _parse_machine(raw, i)
        if m.name in seen:
            raise ConfigError(f"duplicate machine name '{m.name}'")
        seen.add(m.name)
        cfg.machines.append(m)
    return cfg


def load_config(path: Optional[Path] = None) -> Config:
    path = path or config_path()
    if not path.exists():
        return Config(path=path)
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path}: {e}") from e
    return parse_config(data, path)
