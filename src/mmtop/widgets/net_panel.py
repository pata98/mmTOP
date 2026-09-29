from __future__ import annotations

from typing import Dict, List, Optional

from rich.text import Text

from ..manager import MachineState
from .base import Panel, error_line, section_title
from .render import fmt_rate, sparkline, truncate


def _history(state: MachineState, attr: str) -> Dict[str, List[List[Optional[float]]]]:
    """{name: [rx_values, tx_values]} across the history for `net` or `ib`."""
    samples = list(state.history)
    out: Dict[str, List[List[Optional[float]]]] = {}
    for i, s in enumerate(samples):
        for item in getattr(s, attr) or []:
            series = out.setdefault(item.name, [[None] * len(samples), [None] * len(samples)])
            series[0][i] = item.rx
            series[1][i] = item.tx
    return out


def _speed(speed_mbit: Optional[int]) -> str:
    if not speed_mbit:
        return ""
    return f"{speed_mbit // 1000}G" if speed_mbit >= 1000 else f"{speed_mbit}M"


def link_lines(state: MachineState, attr: str, width: int, detail: bool,
               limit: Optional[int] = None) -> List[Text]:
    s = state.latest
    metric = "net" if attr == "net" else "ib"
    if s is None or getattr(s, attr) is None:
        return error_line(s, metric)
    items = getattr(s, attr)
    if not items:
        return [Text("no interfaces" if attr == "net" else "no InfiniBand ports", style="dim")]
    hist = _history(state, attr)
    shown = items[:limit] if limit else items
    name_w = min(16, max(len(i.name) for i in shown))
    out = []
    for item in shown:
        link = _speed(getattr(item, "speed", None)) if attr == "net" else (item.rate or "").split(" (")[0]
        down = item.up is False if attr == "net" else (item.state not in (None, "ACTIVE"))
        head = Text(truncate(item.name, name_w).ljust(name_w) + " ", style="bold" if not down else "dim")
        head.append(f"↓{fmt_rate(item.rx):>9} ", style="green")
        head.append(f"↑{fmt_rate(item.tx):>9}", style="blue")
        if link:
            head.append(f" {link}", style="grey62")
        rx, tx = hist.get(item.name, [[], []])
        spark_w = width - len(head) - 1
        if detail:
            out.append(head)
            half = (width - 5) // 2
            out.append(Text.assemble(Text(" ↓ ", style="green"), sparkline(rx, half, style="green"),
                                     Text(" ↑ ", style="blue"), sparkline(tx, width - half - 6, style="blue")))
        elif spark_w >= 6:
            total = [(a or 0) + (b or 0) if a is not None or b is not None else None for a, b in zip(rx, tx)]
            out.append(Text.assemble(head, " ", sparkline(total, spark_w)))
        else:
            out.append(head)
    if limit and len(items) > limit:
        out.append(Text(f"… {len(items) - limit} more", style="dim"))
    return out


class NetPanel(Panel):
    def build_lines(self, state: MachineState, width: int) -> List[Text]:
        if state.latest is None:
            return []
        out: List[Text] = []
        if "net" in state.metrics:
            out.append(section_title("Network", width))
            out += link_lines(state, "net", width, detail=True)
        if "ib" in state.metrics:
            out.append(section_title("InfiniBand", width))
            out += link_lines(state, "ib", width, detail=True)
        return out
