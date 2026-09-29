from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections import deque
from functools import lru_cache
from pathlib import Path
from typing import List, Optional

from ..config import Config, Machine

STREAM_LIMIT = 16 * 1024 * 1024
COLLECTOR_PATH = Path(__file__).resolve().parent.parent / "collector.py"


@lru_cache(maxsize=1)
def collector_source() -> bytes:
    return COLLECTOR_PATH.read_bytes()


def collector_args(metrics: List[str], interval: float, config: Config) -> List[str]:
    args = ["--metrics", ",".join(metrics), "--interval", f"{interval:g}"]
    if config.exclude_mounts:
        args += ["--exclude-mounts", ",".join(config.exclude_mounts)]
    if config.exclude_ifaces:
        args += ["--exclude-ifaces", ",".join(config.exclude_ifaces)]
    return args


def release_pipes(proc: asyncio.subprocess.Process) -> None:
    """Close the pipes of an exited subprocess even if they were not read to EOF."""
    transport = getattr(proc, "_transport", None)
    if transport is not None:
        transport.close()


class Transport(ABC):
    def __init__(self, machine: Machine, metrics: List[str], config: Config):
        self.machine = machine
        self.metrics = metrics
        self.config = config
        self.stderr_tail: deque = deque(maxlen=20)

    @abstractmethod
    async def open(self) -> None: ...

    @abstractmethod
    async def readline(self) -> bytes:
        """Return one line, or b'' once the stream has ended."""

    @abstractmethod
    async def close(self) -> None: ...

    def error_text(self) -> Optional[str]:
        lines = [l for l in self.stderr_tail if l.strip()]
        return lines[-1] if lines else None


class SubprocessTransport(Transport):
    send_script = False

    def __init__(self, machine: Machine, metrics: List[str], config: Config):
        super().__init__(machine, metrics, config)
        self.proc: Optional[asyncio.subprocess.Process] = None
        self._stderr_task: Optional[asyncio.Task] = None

    @abstractmethod
    def argv(self) -> List[str]: ...

    async def open(self) -> None:
        argv = self.argv()
        try:
            self.proc = await asyncio.create_subprocess_exec(
                *argv,
                stdin=asyncio.subprocess.PIPE if self.send_script else asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=STREAM_LIMIT,
                start_new_session=True,
            )
        except FileNotFoundError as e:
            raise ConnectionError(f"{argv[0]} not found") from e
        assert self.proc.stderr is not None
        self._stderr_task = asyncio.ensure_future(self._drain_stderr(self.proc.stderr))
        if self.send_script:
            assert self.proc.stdin is not None
            try:
                self.proc.stdin.write(collector_source())
                await self.proc.stdin.drain()
                self.proc.stdin.close()
            except (BrokenPipeError, ConnectionResetError):
                pass

    async def _drain_stderr(self, stream: asyncio.StreamReader) -> None:
        while True:
            line = await stream.readline()
            if not line:
                return
            self.stderr_tail.append(line.decode(errors="replace").rstrip())

    async def readline(self) -> bytes:
        if self.proc is None or self.proc.stdout is None:
            return b""
        return await self.proc.stdout.readline()

    async def close(self) -> None:
        proc, self.proc = self.proc, None
        if proc is not None and proc.returncode is None:
            try:
                proc.terminate()
                await asyncio.wait_for(proc.wait(), 3)
            except ProcessLookupError:
                pass
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
        if self._stderr_task is not None:
            try:
                await asyncio.wait_for(self._stderr_task, 1)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._stderr_task.cancel()
            self._stderr_task = None
        if proc is not None:
            release_pipes(proc)
            if proc.returncode not in (0, None, -15) and not self.error_text():
                self.stderr_tail.append(f"exited with status {proc.returncode}")
