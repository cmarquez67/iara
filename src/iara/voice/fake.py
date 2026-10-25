from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from iara.voice.base import SessionClosed, SessionReady, ToolSpec, VoiceEvent


class FakeVoiceSession:
    """Registra as chamadas para os testes; eventos são injetados com `emit`."""

    def __init__(self, fail_start: bool = False) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.fail_start = fail_start
        self._active = False
        self._queue: asyncio.Queue[VoiceEvent] = asyncio.Queue()

    @property
    def active(self) -> bool:
        return self._active

    def names(self) -> list[str]:
        return [name for name, _ in self.calls]

    async def start(self, instructions: str, tools: list[ToolSpec]) -> None:
        self.calls.append(("start", instructions))
        if self.fail_start:
            raise ConnectionError("falha simulada")
        self._active = True
        await self._queue.put(SessionReady())

    async def stop(self, reason: str = "") -> None:
        self.calls.append(("stop", reason))
        if self._active:
            self._active = False
            await self._queue.put(SessionClosed(reason))

    async def say(self, instructions: str) -> None:
        self.calls.append(("say", instructions))

    async def respond(self) -> None:
        self.calls.append(("respond", None))

    async def add_image(self, jpeg: bytes, caption: str) -> None:
        self.calls.append(("add_image", caption))

    async def send_tool_result(self, call_id: str, output: str) -> None:
        self.calls.append(("tool_result", (call_id, output)))

    async def emit(self, event: VoiceEvent) -> None:
        await self._queue.put(event)

    async def events(self) -> AsyncIterator[VoiceEvent]:
        while True:
            yield await self._queue.get()
