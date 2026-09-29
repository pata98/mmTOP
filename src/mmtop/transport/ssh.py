from __future__ import annotations

import shlex
from typing import List

from .base import SubprocessTransport, collector_args

SSH_BASE_OPTIONS = [
    "-T",
    "-o", "BatchMode=yes",
    "-o", "ServerAliveInterval=5",
    "-o", "ServerAliveCountMax=3",
    "-o", "ConnectTimeout=10",
]


def ssh_argv(host: str, options: List[str], remote_command: str) -> List[str]:
    return ["ssh", *SSH_BASE_OPTIONS, *options, host, remote_command]


class SSHTransport(SubprocessTransport):
    """Pipes the collector source into `python3 -` on the remote host."""

    send_script = True

    def argv(self) -> List[str]:
        m = self.machine
        cmd = [m.python, "-u", "-", *collector_args(self.metrics, self.config.interval, self.config)]
        remote = " ".join(shlex.quote(c) for c in cmd)
        return ssh_argv(m.host or "", [*self.config.ssh_options, *m.ssh_options], remote)
