from __future__ import annotations

import sys
from typing import List

from .base import COLLECTOR_PATH, SubprocessTransport, collector_args


class LocalTransport(SubprocessTransport):
    def argv(self) -> List[str]:
        return [sys.executable, "-u", str(COLLECTOR_PATH),
                *collector_args(self.metrics, self.config.interval, self.config)]
