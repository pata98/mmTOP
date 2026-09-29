from __future__ import annotations

from typing import List, Optional

from rich.text import Text

from ..manager import MachineState
from ..protocol import Sample
from .base import Panel, error_line, section_title
from .render import bar, fmt_bytes, fmt_num, join_columns, labeled_bar


def sys_lines(sample: Optional[Sample], width: int) -> List[Text]:
    if sample is None:
        return []
    if sample.cpu is None or sample.mem is None:
        return error_line(sample, "cpu_mem")
    cpu, mem = sample.cpu, sample.mem
    half = (width - 2) // 2
    load = " ".join(f"{x:.2f}" for x in cpu.load)
    cpu_t = labeled_bar("CPU", cpu.pct, half, f"{fmt_num(cpu.pct, '%'):>4}")
    mem_pct = 100.0 * mem.used / mem.total if mem.total else None
    mem_t = labeled_bar("RAM", mem_pct, width - half - 2, f"{fmt_bytes(mem.used)}/{fmt_bytes(mem.total)}")
    out = [join_columns([cpu_t, mem_t])]
    info = f"{cpu.count} cores  load {load}"
    if mem.swap_total:
        info += f"  swap {fmt_bytes(mem.swap_used)}/{fmt_bytes(mem.swap_total)}"
    out.append(Text(info, style="grey62"))
    return out


class SysPanel(Panel):
    def build_lines(self, state: MachineState, width: int) -> List[Text]:
        s = state.latest
        if "cpu_mem" not in state.metrics or s is None:
            return []
        out = [section_title("CPU / RAM", width)] + sys_lines(s, width)
        if s.cpu and s.cpu.per_core:
            cell = 18
            cols = max(1, width // cell)
            row: List[Text] = []
            for i, pct in enumerate(s.cpu.per_core):
                t = Text(f"{i:>3} ", style="grey62")
                t.append_text(bar(pct, cell - 10))
                t.append(f" {fmt_num(pct, '%'):>4} ")
                row.append(t)
                if len(row) == cols:
                    out.append(Text.assemble(*row))
                    row = []
            if row:
                out.append(Text.assemble(*row))
        return out
