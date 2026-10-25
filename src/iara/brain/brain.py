"""Orquestrador: decide quando cumprimentar, responder, olhar a câmera e avisar o dono.

Não sabe de onde vem o vídeo nem qual provedor de voz está por trás.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from collections.abc import Callable
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from iara.brain import prompts
from iara.brain.tools import CHAMAR_ATENDENTE, TOOLS, VER_CAMERA
from iara.config import AppConfig
from iara.domain import (
    CounterOccupied,
    CounterVacated,
    CustomerWaitingUnattended,
    PeopleCountChanged,
    PersonEntered,
    PersonLeft,
    PersonLingering,
    SceneEvent,
)
from iara.notify.base import Notifier
from iara.usage import UsageTracker
from iara.voice.base import (
    AssistantSpeechEnded,
    AssistantSpeechStarted,
    ResponseFinished,
    SessionClosed,
    SessionReady,
    ToolCallRequested,
    UsageReported,
    UserSpeechStarted,
    UserTurnEnded,
    VoiceError,
    VoiceEvent,
    VoiceSession,
)

log = logging.getLogger(__name__)

SnapshotFn = Callable[[], bytes | None]


class UiState(StrEnum):
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"


class UiSink(Protocol):
    async def set_state(self, state: UiState) -> None: ...


class Brain:
    def __init__(
        self,
        cfg: AppConfig,
        voice: VoiceSession,
        notifier: Notifier,
        ui: UiSink,
        usage: UsageTracker,
        snapshot: SnapshotFn | None = None,
        clock: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = datetime.now,
    ) -> None:
        self._cfg = cfg
        self._bc = cfg.brain
        self._voice = voice
        self._notifier = notifier
        self._ui = ui
        self._usage = usage
        self._snapshot = snapshot
        self._clock = clock
        self._now = now
        self._lock = asyncio.Lock()

        self.people = 0
        self.counter_occupied = False
        self.force_attending = False  # modo debug "conversar agora"
        self.speaking = False
        self.thinking = False
        self._snapshot_pending = False
        self._last_greet = float("-inf")
        self._last_alert: dict[str, float] = {}
        self._last_start_failure = float("-inf")
        self._last_presence = float("-inf")
        self._session_started = float("-inf")
        self._ui_state: UiState | None = None

    @property
    def attending(self) -> bool:
        return self.counter_occupied or self.force_attending

    # --- Laço principal ---

    async def run(self, scene_events: asyncio.Queue[SceneEvent]) -> None:
        await self._push_ui()
        async with asyncio.TaskGroup() as tg:
            tg.create_task(self._consume_scene(scene_events))
            tg.create_task(self._consume_voice())
            tg.create_task(self._ticker())

    async def _consume_scene(self, queue: asyncio.Queue[SceneEvent]) -> None:
        while True:
            event = await queue.get()
            await self._guarded(self.handle_scene, event)

    async def _consume_voice(self) -> None:
        async for event in self._voice.events():
            await self._guarded(self.handle_voice, event)

    async def _ticker(self) -> None:
        while True:
            await asyncio.sleep(1.0)
            await self._guarded(self.tick)

    async def _guarded(self, fn, *args) -> None:  # type: ignore[no-untyped-def]
        async with self._lock:
            try:
                await fn(*args)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Erro tratando %s", args[0].__class__.__name__ if args else fn.__name__)

    # --- Eventos de cena ---

    async def handle_scene(self, event: SceneEvent) -> None:
        now = self._clock()
        match event:
            case PersonEntered():
                self._last_presence = now
                if now - self._last_greet < self._bc.greet_cooldown_s:
                    log.info("Saudação suprimida (cooldown)")
                    return
                self._last_greet = now
                if await self._ensure_session():
                    await self._voice.say(prompts.greeting_instructions(self._cfg, self._now()))
            case PersonLeft():
                pass
            case PeopleCountChanged(count=count):
                self.people = count
                if count:
                    self._last_presence = now
            case CounterOccupied():
                self.counter_occupied = True
                self._snapshot_pending = True
                self._last_presence = now
                await self._ensure_session()
            case CounterVacated():
                self.counter_occupied = False
            case PersonLingering(seconds=seconds):
                await self._alert("pessoa_parada", f"Pessoa parada há {seconds:.0f} s fora do balcão.")
            case CustomerWaitingUnattended(seconds=seconds):
                await self._alert(
                    "cliente_esperando", f"Cliente esperando no balcão há {seconds:.0f} s sem atendente."
                )
        await self._push_ui()

    # --- Eventos de voz ---

    async def handle_voice(self, event: VoiceEvent) -> None:
        match event:
            case SessionReady():
                pass
            case SessionClosed():
                self.speaking = False
                self.thinking = False
            case UserSpeechStarted():
                self.thinking = False
            case UserTurnEnded():
                await self._on_user_turn()
            case AssistantSpeechStarted():
                self.speaking = True
                self.thinking = False
            case AssistantSpeechEnded():
                self.speaking = False
            case ResponseFinished(status=status):
                if status != "completed":
                    self.thinking = False
            case ToolCallRequested():
                await self._on_tool_call(event)
            case UsageReported():
                self._usage.record(event)
            case VoiceError(message=message):
                log.warning("Voz: %s", message)
        await self._push_ui()

    async def _on_user_turn(self) -> None:
        if not self.attending:
            log.debug("Fala ignorada: ninguém no balcão")
            return
        if self._snapshot_pending:
            self._snapshot_pending = False
            await self._send_snapshot()
        await self._voice.respond()
        self.thinking = True

    async def _on_tool_call(self, call: ToolCallRequested) -> None:
        log.info("Ferramenta pedida: %s", call.name)
        self.thinking = True
        if call.name == VER_CAMERA:
            jpeg = self._snapshot() if self._snapshot else None
            if jpeg is None:
                await self._voice.send_tool_result(call.call_id, _json(ok=False, erro="câmera indisponível"))
            else:
                await self._voice.send_tool_result(
                    call.call_id, _json(ok=True, info="imagem enviada a seguir")
                )
                await self._voice.add_image(jpeg, prompts.SNAPSHOT_CAPTION)
                self._usage.image_sent()
        elif call.name == CHAMAR_ATENDENTE:
            motivo = str(call.arguments.get("motivo", "")).strip()
            await self._notifier.notify(
                "chamar_atendente", "Cliente no balcão pediu atendimento" + (f": {motivo}" if motivo else ".")
            )
            await self._voice.send_tool_result(call.call_id, _json(ok=True))
        else:
            await self._voice.send_tool_result(call.call_id, _json(ok=False, erro="ferramenta desconhecida"))
        await self._voice.respond()

    # --- Tempo ---

    async def tick(self) -> None:
        now = self._clock()
        present = self.people > 0 or self.attending
        if present:
            self._last_presence = now
        if self._voice.active:
            busy = self.speaking or self.thinking
            if not present and not busy and now - self._last_presence >= self._bc.session_idle_close_s:
                await self._voice.stop("loja vazia")
            elif not busy and now - self._session_started >= self._bc.session_max_s:
                await self._voice.stop("duração máxima")
        elif self.attending:
            # Cliente no balcão sem sessão (queda, falha anterior ou duração máxima): reabre.
            await self._ensure_session()
        await self._push_ui()

    # --- Debug ---

    async def set_force_attending(self, on: bool) -> None:
        async with self._lock:
            self.force_attending = on
            if on:
                self._snapshot_pending = True
                await self._ensure_session()
            await self._push_ui()

    # --- Auxiliares ---

    async def _ensure_session(self) -> bool:
        if self._voice.active:
            return True
        now = self._clock()
        if now - self._last_start_failure < self._bc.session_retry_s:
            return False
        try:
            await self._voice.start(prompts.session_instructions(self._cfg, self._now()), TOOLS)
        except Exception as exc:
            self._last_start_failure = now
            log.warning("Não foi possível abrir a sessão de voz: %s", exc)
            return False
        self._session_started = self._clock()
        self._last_presence = self._session_started
        self._usage.session_started()
        return True

    async def _send_snapshot(self) -> None:
        if self._snapshot is None:
            return
        jpeg = self._snapshot()
        if jpeg is not None:
            await self._voice.add_image(jpeg, prompts.SNAPSHOT_CAPTION)
            self._usage.image_sent()

    async def _alert(self, kind: str, message: str) -> None:
        now = self._clock()
        if now - self._last_alert.get(kind, float("-inf")) < self._bc.alert_cooldown_s:
            return
        self._last_alert[kind] = now
        await self._notifier.notify(kind, message)

    def _compute_ui(self) -> UiState:
        if not self._voice.active:
            return UiState.IDLE
        if self.speaking:
            return UiState.SPEAKING
        if self.thinking:
            return UiState.THINKING
        if self.attending:
            return UiState.LISTENING
        return UiState.IDLE

    async def _push_ui(self) -> None:
        state = self._compute_ui()
        if state != self._ui_state:
            self._ui_state = state
            with contextlib.suppress(Exception):
                await self._ui.set_state(state)


def _json(**kwargs: object) -> str:
    return json.dumps(kwargs, ensure_ascii=False)
