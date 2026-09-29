from __future__ import annotations

from typing import Dict, List

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, SelectionList, Static
from textual.widgets.selection_list import Selection

from ..config import METRIC_LABELS, METRICS


class SelectMetricsScreen(Screen):
    """Pick metrics per machine. Dismisses with {name: metrics}, or None to go back."""

    BINDINGS = [
        Binding("enter", "confirm", "Start", priority=True),
        Binding("a", "toggle_all", "All/none"),
        Binding("escape", "back", "Back"),
    ]

    DEFAULT_CSS = """
    SelectMetricsScreen #metric-lists { height: 1fr; }
    SelectMetricsScreen .machine-name { padding: 0 1; height: 1; }
    SelectMetricsScreen SelectionList { height: auto; max-height: 20; margin: 0 1 1 1; }
    """

    def __init__(self, names: List[str], defaults: Dict[str, List[str]]):
        super().__init__()
        self.names = names
        self.defaults = defaults

    def compose(self) -> ComposeResult:
        yield Static(Text("Select what to monitor", style="bold"), classes="title")
        yield Static(Text("space: toggle   a: all/none   tab: next machine   enter: start   esc: back",
                          style="grey62"))
        with VerticalScroll(id="metric-lists"):
            for i, name in enumerate(self.names):
                yield Static(Text(name, style="bold cyan"), classes="machine-name")
                chosen = set(self.defaults.get(name, ()))
                yield SelectionList(
                    *[Selection(Text.assemble((f"{m:<11}", "bold"), (METRIC_LABELS[m], "grey70")), m, m in chosen)
                      for m in METRICS],
                    id=f"metrics-{i}",
                )
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#metrics-0", SelectionList).focus()

    def _focused_list(self) -> SelectionList:
        if isinstance(self.focused, SelectionList):
            return self.focused
        return self.query_one("#metrics-0", SelectionList)

    def action_toggle_all(self) -> None:
        sl = self._focused_list()
        if len(sl.selected) == len(METRICS):
            sl.deselect_all()
        else:
            sl.select_all()

    def action_confirm(self) -> None:
        chosen: Dict[str, List[str]] = {}
        for i, name in enumerate(self.names):
            sl = self.query_one(f"#metrics-{i}", SelectionList)
            selected = [m for m in METRICS if m in set(sl.selected)]
            if not selected:
                self.notify(f"Select at least one metric for {name}", severity="warning")
                sl.focus()
                return
            chosen[name] = selected
        self.dismiss(chosen)

    def action_back(self) -> None:
        self.dismiss(None)
