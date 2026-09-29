from __future__ import annotations

from typing import List

from rich.console import Group
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Static

from ..manager import ConnectionManager, MachineState
from ..widgets.base import Panel, section_title
from ..widgets.disk_panel import DiskPanel
from ..widgets.gpu_panel import GpuPanel
from ..widgets.machine_card import header_lines
from ..widgets.net_panel import NetPanel
from ..widgets.proc_table import ProcTable
from ..widgets.sys_panel import SysPanel


class HeaderPanel(Panel):
    def __init__(self, interval: float, **kwargs):
        super().__init__(**kwargs)
        self.interval = interval

    def build_lines(self, state: MachineState, width: int) -> List[Text]:
        return header_lines(state, width, self.interval)


class DetailScreen(Screen):
    BINDINGS = [
        Binding("escape,backspace", "back", "Back"),
        Binding("s", "sort", "Sort procs"),
        Binding("g", "gpu_filter", "Filter GPU"),
    ]

    DEFAULT_CSS = """
    DetailScreen #body { height: 1fr; padding: 0 1; }
    DetailScreen HeaderPanel { padding: 0 1; background: $boost; }
    DetailScreen #proc-title { height: 1; }
    """

    def __init__(self, manager: ConnectionManager, machine_name: str, interval: float):
        super().__init__()
        self.manager = manager
        self.machine_name = machine_name
        self.interval = interval

    def compose(self) -> ComposeResult:
        yield HeaderPanel(self.interval)
        with VerticalScroll(id="body"):
            yield SysPanel()
            yield GpuPanel()
            yield Static(id="proc-title")
            yield ProcTable()
            yield DiskPanel()
            yield NetPanel()
        yield Footer()

    def on_mount(self) -> None:
        self.tick()
        self.query_one(ProcTable).focus()

    def tick(self) -> None:
        state = self.manager.states.get(self.machine_name)
        if state is None:
            return
        for panel in self.query(Panel):
            panel.set_state(state)
        table = self.query_one(ProcTable)
        title = self.query_one("#proc-title", Static)
        show_procs = "gpu_procs" in state.metrics
        table.display = show_procs
        title.display = show_procs
        if show_procs:
            width = max(20, title.size.width or 80)
            filt = "all" if table.gpu_filter is None else f"gpu{table.gpu_filter}"
            err = (state.latest.errors.get("gpu_procs") or state.latest.errors.get("gpu")) if state.latest else None
            label = f"GPU processes  sort: {table.sort_name}  gpu: {filt}"
            lines = [section_title(label, width)]
            if err:
                lines.append(Text(err, style="dim red"))
            title.styles.height = len(lines)
            title.update(Group(*lines))
            table.set_state(state)

    def action_back(self) -> None:
        self.app.pop_screen()

    def action_sort(self) -> None:
        self.query_one(ProcTable).cycle_sort()
        self.tick()

    def action_gpu_filter(self) -> None:
        state = self.manager.states.get(self.machine_name)
        gpus = [g.index for g in (state.latest.gpus or [])] if state and state.latest else []
        self.query_one(ProcTable).cycle_gpu_filter([g for g in gpus if g is not None])
        self.tick()
