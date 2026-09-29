from __future__ import annotations

from typing import List, Optional

from rich.text import Text

from ..manager import MachineState
from ..protocol import Gpu, Sample
from .base import Panel, error_line, section_title
from .render import (chart, fmt_bytes, fmt_num, fmt_rate, join_columns, labeled_bar, pct_style,
                     temp_style, truncate)


def gpu_header(g: Gpu, width: int) -> Text:
    right = Text()
    right.append(fmt_num(g.temp, "°C"), style=temp_style(g.temp))
    right.append("  ")
    power = f"{fmt_num(g.power, 'W')}/{fmt_num(g.power_limit, 'W')}"
    ppct = 100.0 * g.power / g.power_limit if g.power is not None and g.power_limit else None
    right.append(power, style=pct_style(ppct))
    if g.fan is not None:
        right.append(f"  fan {g.fan:.0f}%")
    left = Text(f"[{g.index}] ", style="bold")
    left.append(truncate(g.name, max(4, width - len(left) - len(right) - 1)), style="bold white")
    pad = max(1, width - len(left) - len(right))
    return Text.assemble(left, " " * pad, right)


def gpu_bars(g: Gpu, width: int) -> Text:
    half = (width - 2) // 2
    util = labeled_bar("GPU", g.util, half, f"{fmt_num(g.util, '%'):>4}")
    mem_suffix = f"{fmt_bytes(g.mem_used)}/{fmt_bytes(g.mem_total)}"
    mem = labeled_bar("MEM", g.mem_pct, width - half - 2, mem_suffix)
    return join_columns([util, mem])


def gpu_extra(g: Gpu) -> Text:
    parts = []
    if g.clock_sm is not None:
        parts.append(f"SM {fmt_num(g.clock_sm)}/{fmt_num(g.clock_sm_max)}MHz")
    if g.clock_mem is not None:
        parts.append(f"MEM {fmt_num(g.clock_mem)}/{fmt_num(g.clock_mem_max)}MHz")
    if g.pcie_gen is not None:
        pcie = f"PCIe Gen{g.pcie_gen}x{fmt_num(g.pcie_width)}"
        if g.pcie_rx is not None:
            pcie += f" RX {fmt_rate(g.pcie_rx)} TX {fmt_rate(g.pcie_tx)}"
        parts.append(pcie)
    if g.enc is not None or g.dec is not None:
        parts.append(f"ENC {fmt_num(g.enc, '%')} DEC {fmt_num(g.dec, '%')}")
    return Text("   ".join(parts), style="grey62")


def gpu_lines(sample: Optional[Sample], width: int) -> List[Text]:
    if sample is None:
        return []
    if sample.gpus is None:
        return error_line(sample, "gpu")
    if not sample.gpus:
        return [Text("no GPUs", style="dim")]
    out: List[Text] = []
    for g in sample.gpus:
        out.append(gpu_header(g, width))
        out.append(gpu_bars(g, width))
    return out


def proc_lines(sample: Optional[Sample], width: int, limit: int = 3) -> List[Text]:
    if sample is None or sample.procs is None:
        return error_line(sample, "gpu_procs")
    if not sample.procs:
        return [Text("no GPU processes", style="dim")]
    out = []
    for p in sample.procs[:limit]:
        head = f"gpu{p.gpu_index if p.gpu_index is not None else '?'} {p.pid:>7} {truncate(p.user, 10):<10} {fmt_bytes(p.gpu_mem):>6} "
        out.append(Text(head + truncate(p.cmd, width - len(head)), style="grey70"))
    if len(sample.procs) > limit:
        out.append(Text(f"… {len(sample.procs) - limit} more processes", style="dim"))
    return out


class GpuPanel(Panel):
    CHART_HEIGHT = 5

    def build_lines(self, state: MachineState, width: int) -> List[Text]:
        s = state.latest
        if "gpu" not in state.metrics or s is None:
            return []
        out = [section_title("GPU", width)]
        if not s.gpus:
            return out + gpu_lines(s, width)
        history = list(state.history)
        half = (width - 3) // 2
        for g in s.gpus:
            out.append(gpu_header(g, width))
            extra = gpu_extra(g)
            if extra.plain:
                out.append(extra)
            out.append(gpu_bars(g, width))
            util_hist = []
            mem_hist = []
            for h in history:
                hg = h.gpu(g.index) if g.index is not None else None
                util_hist.append(hg.util if hg else None)
                mem_hist.append(hg.mem_pct if hg else None)
            left = chart(util_hist, half, self.CHART_HEIGHT, 100.0, "green")
            right = chart(mem_hist, width - half - 3, self.CHART_HEIGHT, 100.0, "magenta")
            for i, (a, b) in enumerate(zip(left, right)):
                out.append(Text.assemble(a, Text(" │ ", style="grey30"), b))
            out.append(Text.assemble(Text("GPU util %".ljust(half + 3), style="green"),
                                     Text("GPU memory %", style="magenta")))
        return out
