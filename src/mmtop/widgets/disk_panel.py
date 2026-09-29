from __future__ import annotations

from typing import List, Optional

from rich.text import Text

from ..manager import MachineState
from ..protocol import Sample
from .base import Panel, error_line, section_title
from .render import fmt_bytes, fmt_num, fmt_rate, labeled_bar, truncate


def disk_usage_lines(sample: Optional[Sample], width: int, limit: Optional[int] = None) -> List[Text]:
    if sample is None or sample.disks is None:
        return error_line(sample, "disk_usage")
    disks = sample.disks
    shown = disks[:limit] if limit else disks
    label_w = min(24, max(8, max((len(d.mount) for d in shown), default=8)))
    out = []
    for d in shown:
        label = truncate(d.mount, label_w).ljust(label_w)
        if d.stale:
            out.append(Text(f"{label} not responding", style="yellow"))
            continue
        suffix = f"{fmt_bytes(d.used)}/{fmt_bytes(d.total)} {fmt_num(d.pct, '%'):>4}"
        out.append(labeled_bar(label, d.pct, width, suffix))
    if limit and len(disks) > limit:
        out.append(Text(f"… {len(disks) - limit} more mounts", style="dim"))
    return out


def disk_io_lines(sample: Optional[Sample], width: int, limit: Optional[int] = None) -> List[Text]:
    if sample is None or sample.diskio is None:
        return error_line(sample, "disk_io")
    items = sample.diskio
    if limit:
        items = sorted(items, key=lambda d: -((d.read or 0) + (d.write or 0)))[:limit]
    out = []
    for d in items:
        suffix = f"R {fmt_rate(d.read):>9} W {fmt_rate(d.write):>9} {fmt_num(d.busy, '%'):>4}"
        out.append(labeled_bar(truncate(d.name, 10).ljust(10), d.busy, width, suffix))
    return out


class DiskPanel(Panel):
    def build_lines(self, state: MachineState, width: int) -> List[Text]:
        s = state.latest
        if s is None:
            return []
        out: List[Text] = []
        if "disk_usage" in state.metrics:
            out.append(section_title("Disk usage", width))
            out += disk_usage_lines(s, width)
        if "disk_io" in state.metrics:
            out.append(section_title("Disk I/O (busy %)", width))
            out += disk_io_lines(s, width)
        return out
