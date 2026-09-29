from __future__ import annotations

import time
from typing import List

from rich.text import Text

from ..manager import MachineState, Status
from .base import Panel, section_title
from .disk_panel import disk_io_lines, disk_usage_lines
from .gpu_panel import gpu_lines, proc_lines
from .net_panel import link_lines
from .render import fmt_duration, truncate
from .sys_panel import sys_lines

STATUS_STYLE = {
    Status.CONNECTED: ("●", "green"),
    Status.CONNECTING: ("◌", "yellow"),
    Status.RECONNECTING: ("●", "red"),
}


def header_lines(state: MachineState, width: int, interval: float) -> List[Text]:
    m = state.machine
    dot, style = STATUS_STYLE[state.status]
    head = Text(f"{dot} ", style=style)
    head.append(m.name, style="bold")
    info = []
    if state.hello and state.hello.hostname and state.hello.hostname != m.name:
        info.append(state.hello.hostname)
    if m.address and m.address != "local":
        info.append(m.address)
    if state.latest and state.latest.uptime:
        info.append(f"up {fmt_duration(state.latest.uptime)}")
    rest = "  ".join(info)
    if rest:
        head.append("  " + truncate(rest, width - len(head) - 2), style="grey62")
    out = [head]
    now = time.monotonic()
    if state.status == Status.CONNECTING:
        out.append(Text("connecting…", style="yellow"))
    elif state.status == Status.RECONNECTING:
        wait = max(0, int((state.retry_at or now) - now))
        msg = f"disconnected, retry in {wait}s"
        if state.error:
            msg += f": {state.error}"
        out.append(Text(truncate(msg, width * 3), style="red"))
    elif state.latest is not None and now - state.last_update > max(5.0, interval * 3):
        out.append(Text(f"stale: no data for {int(now - state.last_update)}s", style="yellow"))
    return out


class MachineCard(Panel, can_focus=True):
    DEFAULT_CSS = """
    MachineCard {
        height: auto;
        border: round $panel-lighten-2;
        padding: 0 1;
    }
    MachineCard:focus {
        border: round $accent;
    }
    """

    def __init__(self, state: MachineState, interval: float, **kwargs):
        super().__init__(**kwargs)
        self.interval = interval
        self.state = state

    def on_mount(self) -> None:
        self.redraw(force=True)

    def build_lines(self, state: MachineState, width: int) -> List[Text]:
        out = header_lines(state, width, self.interval)
        s = state.latest
        if s is None:
            return out
        sections = [
            ("gpu", "GPU", lambda: gpu_lines(s, width)),
            ("gpu_procs", "GPU processes", lambda: proc_lines(s, width)),
            ("cpu_mem", "CPU / RAM", lambda: sys_lines(s, width)),
            ("disk_usage", "Disk", lambda: disk_usage_lines(s, width, limit=5)),
            ("disk_io", "Disk I/O", lambda: disk_io_lines(s, width, limit=4)),
            ("net", "Network", lambda: link_lines(state, "net", width, detail=False, limit=4)),
            ("ib", "InfiniBand", lambda: link_lines(state, "ib", width, detail=False, limit=4)),
        ]
        for metric, title, fn in sections:
            if metric not in state.metrics:
                continue
            lines = fn()
            if lines:
                out.append(section_title(title, width))
                out += lines
        return out
