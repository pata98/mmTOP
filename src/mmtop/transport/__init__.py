from __future__ import annotations

import asyncio
import shlex
import shutil
import sys
from typing import List, Tuple

from ..config import Config, Machine
from .base import Transport, release_pipes
from .local import LocalTransport
from .ssh import SSHTransport, ssh_argv

PROBE_CODE = "import shutil,sys;print(sys.version.split()[0], bool(shutil.which('nvidia-smi')))"


def _probe_summary(output: str) -> Tuple[bool, str]:
    parts = output.split()
    if len(parts) >= 2:
        return True, f"python {parts[0]}, {'GPU' if parts[1] == 'True' else 'no nvidia-smi'}"
    return True, "reachable"


async def probe(machine: Machine, config: Config, timeout: float = 8.0) -> Tuple[bool, str]:
    """Check whether a machine can be monitored. Returns (ok, short description)."""
    kind = machine.transport
    if kind == "local":
        return True, f"python {sys.version.split()[0]}, {'GPU' if shutil.which('nvidia-smi') else 'no nvidia-smi'}"
    remote = f"{shlex.quote(machine.python)} -c {shlex.quote(PROBE_CODE)}"
    argv = ssh_argv(machine.host or "", [*config.ssh_options, *machine.ssh_options, "-o", "ConnectTimeout=5"], remote)
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, start_new_session=True)
    except FileNotFoundError:
        return False, "ssh not found"
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        release_pipes(proc)
        return False, "timeout"
    except asyncio.CancelledError:
        if proc.returncode is None:
            proc.kill()
            await proc.wait()
        release_pipes(proc)
        raise
    if proc.returncode == 0:
        return _probe_summary(out.decode(errors="replace"))
    lines = [l for l in err.decode(errors="replace").splitlines() if l.strip()]
    if proc.returncode == 127:
        return False, f"{machine.python} not found on remote"
    return False, lines[-1] if lines else f"ssh exited with {proc.returncode}"


def make_transport(machine: Machine, metrics: List[str], config: Config) -> Transport:
    kind = machine.transport
    if kind == "local":
        return LocalTransport(machine, metrics, config)
    if kind == "ssh":
        return SSHTransport(machine, metrics, config)
    raise ValueError(f"unknown transport {kind!r}")


__all__ = ["Transport", "LocalTransport", "SSHTransport", "make_transport"]
