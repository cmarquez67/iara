"""OpenAI Realtime via WebRTC no Chrome + canal de controle (sideband) no backend.

Fluxo:
  1. Brain chama start(); pedimos à página (WS) que abra a conexão WebRTC.
  2. A página manda a oferta SDP para POST /api/rtc/offer -> handle_offer().
  3. handle_offer() chama POST /v1/realtime/calls com a chave (que nunca sai do backend)
     e a configuração da sessão; o call_id vem no cabeçalho Location.
  4. Abrimos o sideband wss://.../v1/realtime?call_id=... para receber eventos e controlar a sessão.
O áudio vai direto Chrome <-> OpenAI, então o cancelador de eco do Chrome enxerga a fala da IA.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
from collections.abc import AsyncIterator
from typing import Any, Protocol

import httpx
from websockets.asyncio.client import ClientConnection, connect

from iara.voice.base import (
    AssistantSpeechEnded,
    AssistantSpeechStarted,
    ResponseFinished,
    ResponseStarted,
    SessionClosed,
    SessionReady,
    ToolCallRequested,
    ToolSpec,
    UsageReported,
    UserSpeechStarted,
    UserTurnEnded,
    VoiceError,
    VoiceEvent,
)

log = logging.getLogger(__name__)

CALLS_URL = "https://api.openai.com/v1/realtime/calls"
SIDEBAND_URL = "wss://api.openai.com/v1/realtime?call_id={call_id}"
_PAGE_EVENT_PREFIX = "output_audio_buffer."  # só chegam pelo data channel da página


class PageLink(Protocol):
    """Canal com a página do Chrome que segura microfone e alto-falante."""

    @property
    def connected(self) -> bool: ...

    async def send(self, message: dict[str, Any]) -> None: ...


def build_session_config(model: str, voice: str, instructions: str, tools: list[ToolSpec]) -> dict[str, Any]:
    return {
        "type": "realtime",
        "model": model,
        "instructions": instructions,
        "output_modalities": ["audio"],
        "audio": {
            "input": {
                "noise_reduction": {"type": "far_field"},
                # O Brain decide quando responder (só com cliente no balcão).
                "turn_detection": {
                    "type": "semantic_vad",
                    "eagerness": "auto",
                    "create_response": False,
                    "interrupt_response": True,
                },
            },
            "output": {"voice": voice},
        },
        "tools": [
            {
                "type": "function",
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            }
            for t in tools
        ],
        "tool_choice": "auto",
    }


def map_server_event(event: dict[str, Any]) -> list[VoiceEvent]:
    """Traduz um evento da OpenAI para eventos neutros. Função pura (testada)."""
    match event.get("type"):
        case "input_audio_buffer.speech_started":
            return [UserSpeechStarted()]
        case "input_audio_buffer.committed":
            return [UserTurnEnded()]
        case "response.created":
            return [ResponseStarted()]
        case "response.done":
            return _map_response_done(event.get("response") or {})
        case "output_audio_buffer.started":
            return [AssistantSpeechStarted()]
        case "output_audio_buffer.stopped":
            return [AssistantSpeechEnded(interrupted=False)]
        case "output_audio_buffer.cleared":
            return [AssistantSpeechEnded(interrupted=True)]
        case "error":
            err = event.get("error") or {}
            return [VoiceError(str(err.get("message", "erro desconhecido")), str(err.get("code") or ""))]
    return []


def _map_response_done(response: dict[str, Any]) -> list[VoiceEvent]:
    out: list[VoiceEvent] = []
    for item in response.get("output") or []:
        if item.get("type") != "function_call":
            continue
        try:
            args = json.loads(item.get("arguments") or "{}")
        except json.JSONDecodeError:
            args = {}
        out.append(ToolCallRequested(str(item.get("call_id", "")), str(item.get("name", "")), args))
    usage = response.get("usage")
    if usage:
        inp = usage.get("input_token_details") or {}
        outp = usage.get("output_token_details") or {}
        out.append(
            UsageReported(
                input_text=int(inp.get("text_tokens") or 0),
                input_audio=int(inp.get("audio_tokens") or 0),
                input_image=int(inp.get("image_tokens") or 0),
                input_cached=int(inp.get("cached_tokens") or 0),
                output_text=int(outp.get("text_tokens") or 0),
                output_audio=int(outp.get("audio_tokens") or 0),
            )
        )
    out.append(ResponseFinished(str(response.get("status", ""))))
    return out


class OpenAIRealtimeSession:
    def __init__(
        self,
        api_key: str,
        model: str,
        voice: str,
        safety_id: str,
        page: PageLink,
        connect_timeout_s: float = 20.0,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._voice = voice
        self._safety_id = safety_id
        self._page = page
        self._connect_timeout_s = connect_timeout_s
        self._http = httpx.AsyncClient(timeout=20.0)
        self._queue: asyncio.Queue[VoiceEvent] = asyncio.Queue()
        self._session_config: dict[str, Any] | None = None
        self._ws: ClientConnection | None = None
        self._sideband_task: asyncio.Task[None] | None = None
        self._sideband_up = asyncio.Event()
        self._rtc_up = asyncio.Event()
        self._changed = asyncio.Event()  # sinaliza qualquer mudança durante a conexão
        self._connect_error: str | None = None
        self._closing = False

    @property
    def active(self) -> bool:
        return self._ws is not None and self._rtc_up.is_set()

    async def start(self, instructions: str, tools: list[ToolSpec]) -> None:
        if self.active:
            return
        if not self._api_key:
            raise RuntimeError("OPENAI_API_KEY não configurada")
        if not self._page.connected:
            raise ConnectionError("Página de áudio (Chrome) não está conectada")
        await self._teardown()
        self._session_config = build_session_config(self._model, self._voice, instructions, tools)
        self._closing = False
        self._connect_error = None
        await self._page.send({"type": "voice.connect"})
        try:
            async with asyncio.timeout(self._connect_timeout_s):
                while not (self._sideband_up.is_set() and self._rtc_up.is_set()):
                    if self._connect_error:
                        raise ConnectionError(self._connect_error)
                    self._changed.clear()
                    await self._changed.wait()
        except TimeoutError:
            await self._teardown()
            raise ConnectionError("Tempo esgotado abrindo a sessão de voz") from None
        except ConnectionError:
            await self._teardown()
            raise
        log.info("Sessão de voz pronta (%s)", self._model)
        await self._queue.put(SessionReady())

    async def handle_offer(self, sdp: str) -> str:
        """Chamado pela rota HTTP com a oferta SDP do Chrome; devolve a resposta SDP."""
        if self._session_config is None:
            raise RuntimeError("Nenhuma sessão de voz foi solicitada")
        resp = await self._http.post(
            CALLS_URL,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "OpenAI-Safety-Identifier": self._safety_id,
            },
            files={
                "sdp": (None, sdp, "application/sdp"),
                "session": (None, json.dumps(self._session_config), "application/json"),
            },
        )
        if resp.status_code >= 400:
            log.error("OpenAI recusou a chamada (%s): %s", resp.status_code, resp.text[:500])
            resp.raise_for_status()
        location = resp.headers.get("Location", "")
        call_id = location.rstrip("/").rsplit("/", 1)[-1]
        if not call_id:
            raise RuntimeError("Resposta sem call_id no cabeçalho Location")
        self._sideband_task = asyncio.create_task(self._run_sideband(call_id), name="realtime-sideband")
        return resp.text

    async def handle_page_event(self, event: dict[str, Any]) -> None:
        """Eventos vindos da página: estado do WebRTC e eventos do data channel."""
        etype = str(event.get("type", ""))
        if etype == "rtc.state":
            state = event.get("state")
            if state == "connected":
                self._rtc_up.set()
                self._changed.set()
            elif state in ("failed", "closed") and self._rtc_up.is_set():
                log.warning("WebRTC %s", state)
                await self.stop(f"webrtc {state}")
            elif state == "failed" and self._session_config is not None:
                self._connect_error = "A página não conseguiu abrir o WebRTC"
                self._changed.set()
        elif etype.startswith(_PAGE_EVENT_PREFIX):
            for ev in map_server_event(event):
                await self._queue.put(ev)

    async def stop(self, reason: str = "") -> None:
        if self._closing:
            return
        was_open = self._ws is not None or self._rtc_up.is_set()
        self._closing = True
        await self._teardown()
        if was_open:
            log.info("Sessão de voz encerrada: %s", reason or "-")
            await self._queue.put(SessionClosed(reason))

    async def say(self, instructions: str) -> None:
        await self._send({"type": "response.create", "response": {"instructions": instructions}})

    async def respond(self) -> None:
        await self._send({"type": "response.create"})

    async def add_image(self, jpeg: bytes, caption: str) -> None:
        data_url = "data:image/jpeg;base64," + base64.b64encode(jpeg).decode("ascii")
        await self._send(
            {
                "type": "conversation.item.create",
                "item": {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": caption},
                        {"type": "input_image", "image_url": data_url, "detail": "low"},
                    ],
                },
            }
        )

    async def send_tool_result(self, call_id: str, output: str) -> None:
        await self._send(
            {
                "type": "conversation.item.create",
                "item": {"type": "function_call_output", "call_id": call_id, "output": output},
            }
        )

    async def events(self) -> AsyncIterator[VoiceEvent]:
        while True:
            yield await self._queue.get()

    async def aclose(self) -> None:
        await self.stop("encerrando")
        await self._http.aclose()

    async def _send(self, event: dict[str, Any]) -> None:
        if self._ws is None:
            raise ConnectionError("Sessão de voz não está aberta")
        await self._ws.send(json.dumps(event))

    async def _run_sideband(self, call_id: str) -> None:
        reason = "sideband encerrado"
        try:
            async with connect(
                SIDEBAND_URL.format(call_id=call_id),
                additional_headers={"Authorization": f"Bearer {self._api_key}"},
                max_size=None,
            ) as ws:
                self._ws = ws
                self._sideband_up.set()
                self._changed.set()
                async for raw in ws:
                    event = json.loads(raw)
                    if str(event.get("type", "")).startswith(_PAGE_EVENT_PREFIX):
                        continue  # já chegam pela página; evita duplicar
                    for ev in map_server_event(event):
                        if isinstance(ev, VoiceError):
                            log.error("Erro da Realtime API: %s (%s)", ev.message, ev.code)
                        await self._queue.put(ev)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # rede, auth, protocolo: a sessão cai, o processo não
            reason = f"sideband falhou: {exc.__class__.__name__}"
            log.warning("Sideband da Realtime caiu: %s", exc)
            self._connect_error = reason
            self._changed.set()
        finally:
            self._ws = None
            self._sideband_up.clear()
        if not self._closing:
            asyncio.get_running_loop().create_task(self.stop(reason))

    async def _teardown(self) -> None:
        task, self._sideband_task = self._sideband_task, None
        ws, self._ws = self._ws, None
        if ws is not None:
            with contextlib.suppress(Exception):
                await ws.close()
        if task is not None and task is not asyncio.current_task():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        self._sideband_up.clear()
        self._rtc_up.clear()
        self._session_config = None
        if self._page.connected:
            with contextlib.suppress(Exception):
                await self._page.send({"type": "voice.disconnect"})
