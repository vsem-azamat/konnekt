"""At most one of something per key per window, in this process.

In memory and per process on purpose: what it protects against is a member
repeating a command in a burst, and a restart that forgets the window costs one
extra message.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Hashable


class Throttle:
    def __init__(self, window_seconds: float, *, max_keys: int = 10_000) -> None:
        self.window_seconds = window_seconds
        self.max_keys = max_keys
        self._last: dict[Hashable, float] = {}

    def allow(self, key: Hashable) -> bool:
        """True the first time per window; records the attempt if so."""
        now = time.monotonic()
        if len(self._last) > self.max_keys:
            self._last = {k: t for k, t in self._last.items() if now - t < self.window_seconds}
        if now - self._last.get(key, -self.window_seconds) < self.window_seconds:
            return False
        self._last[key] = now
        return True

    def clear(self) -> None:
        self._last.clear()
