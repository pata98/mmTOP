from __future__ import annotations

from typing import List, Optional, Sequence

from rich.console import Group
from rich.text import Text
from textual.widgets import Static

from ..manager import MachineState
from ..protocol import Sample


def section_title(title: str, width: int) -> Text:
    t = Text(f"─ {title} ", style="bold cyan")
    t.append("─" * max(0, width - len(t)), style="grey30")
    return t


def error_line(sample: Optional[Sample], *metrics: str) -> List[Text]:
    if sample is None:
        return []
    for m in metrics:
        if m in sample.errors:
            return [Text(f"{m}: {sample.errors[m]}", style="dim red")]
    return []


class Panel(Static):
    """Static that re-renders from a MachineState only when the data or width changed."""

    DEFAULT_CSS = "Panel { height: auto; }"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.state: Optional[MachineState] = None
        self.plain = ""
        self._key = None

    def build_lines(self, state: MachineState, width: int) -> Sequence[Text]:
        raise NotImplementedError

    def set_state(self, state: Optional[MachineState]) -> None:
        self.state = state
        self.redraw()

    def redraw(self, force: bool = False) -> None:
        if self.state is None:
            return
        width = max(20, self.content_region.width or self.size.width or 80)
        key = (self.state.version, width, id(self.state))
        if key == self._key and not force:
            return
        self._key = key
        lines = list(self.build_lines(self.state, width))
        self.plain = "\n".join(l.plain for l in lines)
        self.display = bool(lines)
        self.update(Group(*lines) if lines else "")

    def on_resize(self) -> None:
        self.redraw()
