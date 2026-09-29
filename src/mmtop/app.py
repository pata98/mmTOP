from __future__ import annotations

from typing import List, Optional

from textual.app import App
from textual.binding import Binding

from .config import METRICS, Config, Machine, Selection
from .manager import ConnectionManager
from .screens.detail import DetailScreen
from .screens.overview import OverviewScreen
from .screens.select_machines import SelectMachinesScreen
from .screens.select_metrics import SelectMetricsScreen

TICK_SECONDS = 0.5


class MmtopApp(App):
    TITLE = "mmtop"
    CSS = """
    .title { padding: 0 1; height: auto; }
    SelectionList { height: auto; max-height: 1fr; margin: 1 1; }
    """
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("m", "select", "Machines/metrics"),
    ]

    def __init__(self, config: Config, machines: List[Machine]):
        super().__init__()
        self.config = config
        self.machines = machines
        self.selection: Optional[Selection] = None
        self.manager: Optional[ConnectionManager] = None
        self.overview: Optional[OverviewScreen] = None

    def on_mount(self) -> None:
        self.manager = ConnectionManager(self.config, self.machines)
        self.set_interval(TICK_SECONDS, self._tick)
        self.action_select()

    def _tick(self) -> None:
        tick = getattr(self.screen, "tick", None)
        if tick is not None:
            tick()

    def action_select(self) -> None:
        if isinstance(self.screen, (SelectMachinesScreen, SelectMetricsScreen)):
            return
        first = self.overview is None
        if self.selection is not None:
            pre = set(self.selection.machines)
        else:
            pre = {m.name for m in self.machines}

        def after_machines(names: Optional[List[str]]) -> None:
            if names is None:
                if first:
                    self.exit()
                return
            saved = self.selection.metrics if self.selection else {}
            defaults = {}
            for name in names:
                chosen = [m for m in saved.get(name, []) if m in METRICS]
                defaults[name] = chosen or list(self.config.default_metrics)

            def after_metrics(metrics: Optional[dict]) -> None:
                if metrics is None:
                    self.selection = Selection(names, defaults)
                    self.action_select()
                    return
                self._apply(Selection(names, metrics))

            self.push_screen(SelectMetricsScreen(names, defaults), after_metrics)

        self.push_screen(SelectMachinesScreen(self.machines, self.config, pre), after_machines)

    def _apply(self, selection: Selection) -> None:
        assert self.manager is not None
        self.selection = selection
        self.manager.apply(selection.machines, selection.metrics)
        if self.overview is None:
            self.overview = OverviewScreen(self.manager, self.config.interval)
            self.push_screen(self.overview)
            return
        while isinstance(self.screen, DetailScreen) and self.screen.machine_name not in self.manager.states:
            self.pop_screen()
        self.overview.rebuild()

    def open_detail(self, name: str) -> None:
        assert self.manager is not None
        self.push_screen(DetailScreen(self.manager, name, self.config.interval))

    async def action_quit(self) -> None:
        if self.manager is not None:
            await self.manager.stop_all()
        self.exit()

    async def on_unmount(self) -> None:
        if self.manager is not None:
            await self.manager.stop_all()
