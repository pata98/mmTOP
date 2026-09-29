from __future__ import annotations

from typing import Dict, List, Optional, Set, Tuple

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Footer, SelectionList, Static
from textual.widgets.selection_list import Selection

from ..config import Config, Machine
from ..transport import probe

CHECKING = (None, "checking…")


class SelectMachinesScreen(Screen):
    """Pick which machines to monitor. Dismisses with a list of machine names, or None."""

    BINDINGS = [
        Binding("enter", "confirm", "Next", priority=True),
        Binding("a", "toggle_all", "All/none"),
        Binding("r", "recheck", "Recheck"),
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(self, machines: List[Machine], config: Config, preselected: Set[str],
                 cancel_label: str = "Cancel"):
        super().__init__()
        self.machines = machines
        self.config = config
        self.preselected = preselected
        self.status: Dict[str, Tuple[Optional[bool], str]] = {m.name: CHECKING for m in machines}
        self.cancel_label = cancel_label

    def compose(self) -> ComposeResult:
        yield Static(Text("Select machines to monitor", style="bold"), classes="title")
        yield Static(Text("space: toggle   a: all/none   r: re-check   enter: next", style="grey62"))
        yield SelectionList(*self._options(self.preselected), id="machines")
        yield Footer()

    def _options(self, selected: Set[str]) -> List[Selection]:
        name_w = max(len(m.name) for m in self.machines)
        addr_w = max(len(m.address) for m in self.machines)
        opts = []
        for m in self.machines:
            ok, msg = self.status[m.name]
            prompt = Text(f"{m.name:<{name_w}}  ", style="bold")
            prompt.append(f"{m.address:<{addr_w}}  ", style="grey62")
            icon, style = ("…", "yellow") if ok is None else ("✓", "green") if ok else ("✗", "red")
            prompt.append(f"{icon} {msg}", style=style)
            opts.append(Selection(prompt, m.name, m.name in selected))
        return opts

    def on_mount(self) -> None:
        self.query_one(SelectionList).focus()
        self.action_recheck()

    def _rebuild(self) -> None:
        sl = self.query_one(SelectionList)
        selected = set(sl.selected)
        highlighted = sl.highlighted
        sl.clear_options()
        sl.add_options(self._options(selected))
        if highlighted is not None:
            sl.highlighted = highlighted

    async def _check(self, machine: Machine) -> None:
        self.status[machine.name] = await probe(machine, self.config)
        self._rebuild()

    def action_recheck(self) -> None:
        for m in self.machines:
            self.status[m.name] = CHECKING
        self._rebuild()
        for m in self.machines:
            self.run_worker(self._check(m), group="probe")

    def action_toggle_all(self) -> None:
        sl = self.query_one(SelectionList)
        if len(sl.selected) == len(self.machines):
            sl.deselect_all()
        else:
            sl.select_all()

    def action_confirm(self) -> None:
        selected = set(self.query_one(SelectionList).selected)
        if not selected:
            self.notify("Select at least one machine", severity="warning")
            return
        self.dismiss([m.name for m in self.machines if m.name in selected])

    def action_cancel(self) -> None:
        self.dismiss(None)
