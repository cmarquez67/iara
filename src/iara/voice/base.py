"""Interface de voz neutra. O Brain só conhece isto, nunca o formato de eventos do provedor."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class SessionReady:
    pass


@dataclass(frozen=True, slots=True)
class SessionClosed:
    reason: str


@dataclass(frozen=True, slots=True)
class UserSpeechStarted:
    pass


@dataclass(frozen=True, slots=True)
class UserTurnEnded:
    pass


@dataclass(frozen=True, slots=True)
class ResponseStarted:
    pass


@dataclass(frozen=True, slots=True)
class ResponseFinished:
    status: str


@dataclass(frozen=True, slots=True)
class AssistantSpeechStarted:
    pass


@dataclass(frozen=True, slots=True)
class AssistantSpeechEnded:
    interrupted: bool = False


@dataclass(frozen=True, slots=True)
class ToolCallRequested:
    call_id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class UsageReported:
    input_text: int = 0
    input_audio: int = 0
    input_image: int = 0
    input_cached: int = 0
    output_text: int = 0
    output_audio: int = 0


@dataclass(frozen=True, slots=True)
class VoiceError:
    message: str
    code: str = ""


VoiceEvent = (
    SessionReady
    | SessionClosed
    | UserSpeechStarted
    | UserTurnEnded
    | ResponseStarted
    | ResponseFinished
    | AssistantSpeechStarted
    | AssistantSpeechEnded
    | ToolCallRequested
    | UsageReported
    | VoiceError
)


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any] = field(
        default_factory=lambda: {"type": "object", "properties": {}, "required": []}
    )


class VoiceSession(Protocol):
    @property
    def active(self) -> bool: ...

    async def start(self, instructions: str, tools: list[ToolSpec]) -> None:
        """Abre a sessão; retorna quando estiver pronta para falar. Lança exceção se falhar."""
        ...

    async def stop(self, reason: str = "") -> None: ...

    async def say(self, instructions: str) -> None:
        """Faz a IA falar por iniciativa própria (ex.: saudação)."""
        ...

    async def respond(self) -> None:
        """Responde ao último turno do cliente."""
        ...

    async def add_image(self, jpeg: bytes, caption: str) -> None: ...

    async def send_tool_result(self, call_id: str, output: str) -> None: ...

    def events(self) -> AsyncIterator[VoiceEvent]: ...
