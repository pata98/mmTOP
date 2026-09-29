from __future__ import annotations

from typing import Dict, Optional

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Static

from ..manager import ConnectionManager
from ..widgets.machine_card import MachineCard

class OverviewScreen(Screen):
    BINDINGS = [
        Binding("enter", "open", "Details"),
        Binding("right,down,j,l", "app.focus_next", "Next", show=False),
        Binding("left,up,k,h", "app.focus_previous", "Prev", show=False),
    ]

    DEFAULT_CSS = """
    OverviewScreen #cards { height: 1fr; }
    OverviewScreen MachineCard { width: 1fr; }
    """

    def __init__(self, manager: ConnectionManager, interval: float):
        super().__init__()
        self.manager = manager
        self.interval = interval
        self.cards: Dict[str, MachineCard] = {}
        self._layout_key = None

    def compose(self) -> ComposeResult:
        yield Static(id="title", classes="title")
        yield VerticalScroll(id="cards")
        yield Footer()

    def on_mount(self) -> None:
        self.rebuild()

    def on_resize(self) -> None:
        self.rebuild()

    def rebuild(self) -> None:
        names = list(self.manager.states)
        key = (tuple(names), tuple(id(s) for s in self.manager.states.values()))
        if key == self._layout_key:
            return
        self._layout_key = key
        focused: Optional[str] = None
        for name, card in self.cards.items():
            if card.has_focus:
                focused = name
        container = self.query_one("#cards", VerticalScroll)
        container.remove_children()
        self.cards = {name: MachineCard(self.manager.states[name], self.interval) for name in names}
        container.mount_all(list(self.cards.values()))
        target = self.cards.get(focused or "") or next(iter(self.cards.values()), None)
        if target is not None:
            self.call_after_refresh(target.focus)
        self.tick()

    def tick(self) -> None:
        states = self.manager.states
        connected = sum(1 for s in states.values() if s.status == "connected")
        title = Text("mmtop", style="bold cyan")
        title.append(f"  {connected}/{len(states)} connected  every {self.interval:g}s", style="grey62")
        self.query_one("#title", Static).update(title)
        for name, card in self.cards.items():
            st = states.get(name)
            if st is not None:
                card.set_state(st)

    def action_open(self) -> None:
        for name, card in self.cards.items():
            if card.has_focus:
                self.app.open_detail(name)
                return
