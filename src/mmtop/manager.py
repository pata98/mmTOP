from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Dict, List, Optional

from .config import METRICS, Config, Machine
from .protocol import ErrorMessage, Hello, ProtocolError, Sample, parse_message
from .transport import Transport, make_transport

BACKOFF_MIN = 1.0
BACKOFF_MAX = 30.0


class Status(str, Enum):
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"


@dataclass
class MachineState:
    machine: Machine
    metrics: List[str]
    history: deque
    status: Status = Status.CONNECTING
    error: Optional[str] = None
    hello: Optional[Hello] = None
    latest: Optional[Sample] = None
    last_update: float = 0.0
    retry_at: Optional[float] = None
    version: int = 0

    def touch(self) -> None:
        self.version += 1


def effective_metrics(selected: List[str]) -> List[str]:
    return [m for m in METRICS if m in selected]


TransportFactory = Callable[[Machine, List[str], Config], Transport]


class ConnectionManager:
    def __init__(self, config: Config, machines: List[Machine],
                 transport_factory: TransportFactory = make_transport):
        self.config = config
        self.machines: Dict[str, Machine] = {m.name: m for m in machines}
        self.transport_factory = transport_factory
        self.states: Dict[str, MachineState] = {}
        self._tasks: Dict[str, asyncio.Task] = {}
        self.history_len = max(10, int(config.history_seconds / config.interval))

    def apply(self, names: List[str], metrics: Dict[str, List[str]]) -> None:
        """Connect to `names`, disconnect everything else, restart machines whose metrics changed."""
        wanted = [n for n in names if n in self.machines]
        for name in list(self.states):
            if name not in wanted:
                self._stop(name)
        new_states: Dict[str, MachineState] = {}
        for name in wanted:
            machine = self.machines[name]
            eff = effective_metrics(metrics.get(name, []))
            st = self.states.get(name)
            if st is None or st.metrics != eff:
                if st is not None:
                    self._stop(name)
                st = MachineState(machine=machine, metrics=eff, history=deque(maxlen=self.history_len))
                self._tasks[name] = asyncio.ensure_future(self._run(st))
            new_states[name] = st
        self.states = new_states

    def _stop(self, name: str) -> None:
        task = self._tasks.pop(name, None)
        if task is not None:
            task.cancel()
        self.states.pop(name, None)

    async def stop_all(self) -> None:
        tasks = list(self._tasks.values())
        for name in list(self._tasks):
            self._stop(name)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _run(self, st: MachineState) -> None:
        backoff = BACKOFF_MIN
        while True:
            transport = self.transport_factory(st.machine, st.metrics, self.config)
            error: Optional[str] = None
            try:
                await transport.open()
                while True:
                    line = await transport.readline()
                    if not line:
                        break
                    try:
                        msg = parse_message(line)
                    except ProtocolError as e:
                        error = str(e)
                        continue
                    if isinstance(msg, ErrorMessage):
                        error = msg.message
                        break
                    st.status = Status.CONNECTED
                    st.error = None
                    st.retry_at = None
                    if isinstance(msg, Hello):
                        st.hello = msg
                    elif isinstance(msg, Sample):
                        st.latest = msg
                        st.history.append(msg)
                        st.last_update = time.monotonic()
                        backoff = BACKOFF_MIN
                    st.touch()
            except asyncio.CancelledError:
                await transport.close()
                raise
            except (OSError, ValueError, ConnectionError) as e:
                error = str(e) or type(e).__name__
            await transport.close()
            st.status = Status.RECONNECTING
            st.error = transport.error_text() or error or "connection closed"
            st.retry_at = time.monotonic() + backoff
            st.touch()
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, BACKOFF_MAX)
