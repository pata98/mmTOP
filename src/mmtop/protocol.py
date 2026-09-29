from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union

from .collector import PROTOCOL_VERSION


class ProtocolError(Exception):
    pass


def _build(cls, data: Any):
    if not isinstance(data, dict):
        raise ProtocolError(f"expected object for {cls.__name__}")
    names = {f.name for f in dataclasses.fields(cls)}
    return cls(**{k: v for k, v in data.items() if k in names})


def _build_list(cls, data: Any) -> list:
    if data is None:
        return []
    if not isinstance(data, list):
        raise ProtocolError(f"expected list for {cls.__name__}")
    return [_build(cls, d) for d in data]


@dataclass
class Gpu:
    index: Optional[int] = None
    uuid: Optional[str] = None
    name: Optional[str] = None
    util: Optional[float] = None
    mem_util: Optional[float] = None
    mem_used: Optional[int] = None
    mem_total: Optional[int] = None
    temp: Optional[float] = None
    power: Optional[float] = None
    power_limit: Optional[float] = None
    fan: Optional[float] = None
    clock_sm: Optional[float] = None
    clock_mem: Optional[float] = None
    clock_sm_max: Optional[float] = None
    clock_mem_max: Optional[float] = None
    pcie_gen: Optional[int] = None
    pcie_width: Optional[int] = None
    pcie_rx: Optional[float] = None
    pcie_tx: Optional[float] = None
    enc: Optional[float] = None
    dec: Optional[float] = None

    @property
    def mem_pct(self) -> Optional[float]:
        if self.mem_used is None or not self.mem_total:
            return None
        return 100.0 * self.mem_used / self.mem_total


@dataclass
class GpuProc:
    pid: int = 0
    gpu_index: Optional[int] = None
    gpu_uuid: Optional[str] = None
    gpu_mem: Optional[int] = None
    sm: Optional[float] = None
    user: Optional[str] = None
    cmd: Optional[str] = None
    cpu: Optional[float] = None
    rss: Optional[int] = None


@dataclass
class Cpu:
    pct: Optional[float] = None
    per_core: List[Optional[float]] = field(default_factory=list)
    count: int = 0
    load: List[float] = field(default_factory=list)


@dataclass
class Mem:
    total: int = 0
    used: int = 0
    available: int = 0
    swap_total: int = 0
    swap_used: int = 0


@dataclass
class Disk:
    mount: str = ""
    device: str = ""
    fstype: str = ""
    total: Optional[int] = None
    used: Optional[int] = None
    avail: Optional[int] = None
    stale: bool = False

    @property
    def pct(self) -> Optional[float]:
        if self.used is None or self.avail is None or self.used + self.avail == 0:
            return None
        return 100.0 * self.used / (self.used + self.avail)


@dataclass
class DiskIO:
    name: str = ""
    read: Optional[float] = None
    write: Optional[float] = None
    busy: Optional[float] = None


@dataclass
class NetIf:
    name: str = ""
    rx: Optional[float] = None
    tx: Optional[float] = None
    speed: Optional[int] = None
    up: Optional[bool] = None
    rx_total: Optional[int] = None
    tx_total: Optional[int] = None


@dataclass
class IbPort:
    name: str = ""
    rx: Optional[float] = None
    tx: Optional[float] = None
    rate: Optional[str] = None
    state: Optional[str] = None


@dataclass
class Hello:
    v: int
    hostname: str = ""
    metrics: List[str] = field(default_factory=list)
    gpu_backend: Optional[str] = None
    python: Optional[str] = None
    kernel: Optional[str] = None
    pid: Optional[int] = None


@dataclass
class Sample:
    ts: float
    uptime: Optional[float] = None
    cpu: Optional[Cpu] = None
    mem: Optional[Mem] = None
    gpus: Optional[List[Gpu]] = None
    procs: Optional[List[GpuProc]] = None
    disks: Optional[List[Disk]] = None
    diskio: Optional[List[DiskIO]] = None
    net: Optional[List[NetIf]] = None
    ib: Optional[List[IbPort]] = None
    errors: Dict[str, str] = field(default_factory=dict)

    def gpu(self, index: int) -> Optional[Gpu]:
        for g in self.gpus or []:
            if g.index == index:
                return g
        return None


@dataclass
class ErrorMessage:
    message: str


Message = Union[Hello, Sample, ErrorMessage]

_LIST_FIELDS = {
    "gpus": Gpu, "procs": GpuProc, "disks": Disk, "diskio": DiskIO, "net": NetIf, "ib": IbPort,
}


def parse_message(line: Union[str, bytes]) -> Message:
    try:
        data = json.loads(line)
    except ValueError as e:
        text = line.decode(errors="replace") if isinstance(line, bytes) else line
        raise ProtocolError(f"invalid JSON: {text.strip()[:200]}") from e
    if not isinstance(data, dict):
        raise ProtocolError("message must be a JSON object")
    kind = data.get("type")
    if kind == "error":
        return ErrorMessage(str(data.get("message", "unknown error")))
    if data.get("v") != PROTOCOL_VERSION:
        raise ProtocolError(f"protocol version mismatch: got {data.get('v')}, expected {PROTOCOL_VERSION}")
    try:
        if kind == "hello":
            return _build(Hello, data)
        if kind == "sample":
            kwargs: Dict[str, Any] = {"ts": float(data.get("ts", 0)), "uptime": data.get("uptime")}
            kwargs["errors"] = {str(k): str(v) for k, v in (data.get("errors") or {}).items()}
            if "cpu" in data:
                kwargs["cpu"] = _build(Cpu, data["cpu"])
            if "mem" in data:
                kwargs["mem"] = _build(Mem, data["mem"])
            for key, cls in _LIST_FIELDS.items():
                if key in data:
                    kwargs[key] = _build_list(cls, data[key])
            return Sample(**kwargs)
    except (TypeError, ValueError) as e:
        raise ProtocolError(f"malformed {kind}: {e}") from e
    raise ProtocolError(f"unknown message type {kind!r}")
