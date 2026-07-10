"""E-stop state — shared, async-safe."""

from __future__ import annotations

import asyncio


class EStopState:
    """Boolean latch protected by an asyncio.Lock.

    Fail-closed: created engaged by default.  Callers must explicitly
    release it after policy checks pass, typically via the safety
    dashboard's release button.
    """

    def __init__(self, *, engaged: bool = True) -> None:
        self._engaged = engaged
        self._lock = asyncio.Lock()

    async def engaged(self) -> bool:
        async with self._lock:
            return self._engaged

    async def engage(self) -> bool:
        async with self._lock:
            if self._engaged:
                return False
            self._engaged = True
            return True

    async def release(self) -> bool:
        async with self._lock:
            if not self._engaged:
                return False
            self._engaged = False
            return True
