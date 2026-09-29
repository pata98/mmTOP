from __future__ import annotations

from typing import Iterable, List, Optional, Sequence

from rich.text import Text

EIGHTHS = " ▏▎▍▌▋▊▉█"
SPARK = " ▁▂▃▄▅▆▇█"


def fmt_bytes(n: Optional[float], unit: str = "") -> str:
    if n is None:
        return "-"
    n = float(n)
    for suffix in ("B", "K", "M", "G", "T", "P"):
        if abs(n) < 1024 or suffix == "P":
            if suffix == "B":
                return f"{n:.0f}{suffix}{unit}"
            return f"{n:.1f}{suffix}{unit}" if abs(n) < 100 else f"{n:.0f}{suffix}{unit}"
        n /= 1024
    return "-"


def fmt_rate(n: Optional[float]) -> str:
    return fmt_bytes(n, "/s")


def fmt_num(v: Optional[float], unit: str = "", digits: int = 0) -> str:
    if v is None:
        return "-"
    return f"{v:.{digits}f}{unit}"


def fmt_duration(seconds: Optional[float]) -> str:
    if seconds is None:
        return "-"
    s = int(seconds)
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    m, _ = divmod(s, 60)
    if d:
        return f"{d}d {h}h"
    if h:
        return f"{h}h {m}m"
    return f"{m}m"


def pct_style(pct: Optional[float]) -> str:
    if pct is None:
        return "grey50"
    if pct < 50:
        return "green"
    if pct < 80:
        return "yellow"
    return "red"


def temp_style(t: Optional[float]) -> str:
    if t is None:
        return "grey50"
    return "green" if t < 70 else "yellow" if t < 85 else "red"


def bar(pct: Optional[float], width: int, style: Optional[str] = None) -> Text:
    width = max(1, width)
    text = Text()
    if pct is None:
        text.append("·" * width, style="grey30")
        return text
    frac = min(max(pct / 100.0, 0.0), 1.0)
    cells = frac * width
    full = int(cells)
    part = int(round((cells - full) * 8))
    if part == 8:
        full, part = full + 1, 0
    body = "█" * full + (EIGHTHS[part] if part and full < width else "")
    text.append(body, style=style or pct_style(pct))
    text.append("·" * (width - len(body)), style="grey30")
    return text


def labeled_bar(label: str, pct: Optional[float], width: int, suffix: str, style: Optional[str] = None) -> Text:
    """`LABEL [bar] suffix` fitted into `width` cells."""
    t = Text()
    t.append(label, style="bold")
    t.append(" ")
    bar_w = max(4, width - len(label) - len(suffix) - 2)
    t.append_text(bar(pct, bar_w, style))
    t.append(" ")
    t.append(suffix)
    return t


def sparkline(values: Sequence[Optional[float]], width: int, max_value: Optional[float] = None,
              style: str = "cyan") -> Text:
    vals = list(values)[-width:] if width > 0 else []
    known = [v for v in vals if v is not None]
    top = max_value if max_value else (max(known) if known else 0)
    chars = []
    for v in vals:
        if v is None or top <= 0:
            chars.append(" ")
        else:
            idx = int(round(min(v / top, 1.0) * 8))
            chars.append(SPARK[idx] if idx else ("▁" if v > 0 else " "))
    return Text(" " * (width - len(chars)) + "".join(chars), style=style)


def chart(values: Sequence[Optional[float]], width: int, height: int, max_value: float = 100.0,
          style: str = "green") -> List[Text]:
    """Multi-row block chart, newest value on the right. Returns rows top to bottom."""
    vals = list(values)[-width:]
    vals = [None] * (width - len(vals)) + vals
    rows: List[Text] = []
    for row in range(height):
        level_top = height - row
        line = []
        for v in vals:
            if v is None or max_value <= 0:
                line.append(" ")
                continue
            filled = min(max(v / max_value, 0.0), 1.0) * height
            if filled >= level_top:
                line.append("█")
            elif filled > level_top - 1:
                line.append(SPARK[int((filled - (level_top - 1)) * 8)] or " ")
            else:
                line.append(" ")
        rows.append(Text("".join(line), style=style))
    return rows


def join_columns(parts: Iterable[Text], sep: str = "  ") -> Text:
    out = Text()
    for i, p in enumerate(parts):
        if i:
            out.append(sep)
        out.append_text(p)
    return out


def truncate(s: Optional[str], width: int) -> str:
    s = s or ""
    if width <= 0:
        return ""
    return s if len(s) <= width else s[: max(0, width - 1)] + "…"
