from __future__ import annotations

from typing import List, Optional

from textual.widgets import DataTable

from ..manager import MachineState
from ..protocol import GpuProc
from .render import fmt_bytes, fmt_num

SORT_KEYS = {
    "gpu mem": lambda p: -(p.gpu_mem or 0),
    "cpu": lambda p: -(p.cpu or 0),
    "sm": lambda p: -(p.sm or 0),
    "pid": lambda p: p.pid,
    "gpu": lambda p: (p.gpu_index if p.gpu_index is not None else 1 << 30, -(p.gpu_mem or 0)),
}


class ProcTable(DataTable):
    DEFAULT_CSS = """
    ProcTable {
        height: auto;
        max-height: 20;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(cursor_type="row", zebra_stripes=True, **kwargs)
        self.sort_names = list(SORT_KEYS)
        self.sort_index = 0
        self.gpu_filter: Optional[int] = None
        self._version = None

    def on_mount(self) -> None:
        self.add_columns("GPU", "PID", "USER", "GPU MEM", "SM%", "CPU%", "HOST MEM", "COMMAND")

    @property
    def sort_name(self) -> str:
        return self.sort_names[self.sort_index]

    def cycle_sort(self) -> None:
        self.sort_index = (self.sort_index + 1) % len(self.sort_names)
        self._version = None

    def cycle_gpu_filter(self, gpu_indices: List[int]) -> None:
        options: List[Optional[int]] = [None, *gpu_indices]
        i = options.index(self.gpu_filter) if self.gpu_filter in options else 0
        self.gpu_filter = options[(i + 1) % len(options)]
        self._version = None

    def set_state(self, state: MachineState) -> None:
        if state.latest is None or state.version == self._version:
            return
        self._version = state.version
        procs: List[GpuProc] = list(state.latest.procs or [])
        if self.gpu_filter is not None:
            procs = [p for p in procs if p.gpu_index == self.gpu_filter]
        procs.sort(key=SORT_KEYS[self.sort_name])
        selected = None
        if self.row_count and 0 <= self.cursor_row < self.row_count:
            selected = self.coordinate_to_cell_key((self.cursor_row, 0)).row_key.value
        self.clear()
        for p in procs:
            self.add_row(
                str(p.gpu_index) if p.gpu_index is not None else "?",
                str(p.pid),
                p.user or "?",
                fmt_bytes(p.gpu_mem),
                fmt_num(p.sm),
                fmt_num(p.cpu, digits=1),
                fmt_bytes(p.rss),
                (p.cmd or "?")[:200],
                key=f"{p.pid}-{p.gpu_index}",
            )
        if selected is not None:
            try:
                self.move_cursor(row=self.get_row_index(selected))
            except Exception:
                pass
