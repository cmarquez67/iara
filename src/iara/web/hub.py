"""WebSocket com a(s) página(s) do Chrome: envia estado/comandos, recebe eventos do WebRTC."""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import WebSocket

from iara.brain.brain import UiState

log = logging.getLogger(__name__)

PageEventHandler = Callable[[dict[str, Any]], Awaitable[None]]


class PageHub:
    """A página mais recente é a "página de áudio" (dona do microfone e do WebRTC)."""

    def __init__(self, page_config: dict[str, Any]) -> None:
        self._clients: list[WebSocket] = []
        self._page_config = page_config
        self._state = UiState.IDLE
        self.on_page_event: PageEventHandler | None = None

    @property
    def connected(self) -> bool:
        return bool(self._clients)

    async def send(self, message: dict[str, Any]) -> None:
        """Comando para a página de áudio."""
        if not self._clients:
            raise ConnectionError("Nenhuma página conectada")
        await self._clients[-1].send_json(message)

    async def set_state(self, state: UiState) -> None:
        self._state = state
        await self._broadcast({"type": "state", "state": state.value})

    async def serve(self, ws: WebSocket) -> None:
        await ws.accept()
        self._clients.append(ws)
        log.info("Página conectada (%d)", len(self._clients))
        try:
            await ws.send_json({"type": "config", **self._page_config})
            await ws.send_json({"type": "state", "state": self._state.value})
            while True:
                message = await ws.receive_json()
                if self.on_page_event is not None and isinstance(message, dict):
                    try:
                        await self.on_page_event(message)
                    except Exception:
                        log.exception("Erro tratando evento da página")
        except Exception as exc:  # WebSocketDisconnect ou JSON inválido
            log.info("Página desconectada (%s)", exc.__class__.__name__)
        finally:
            was_audio_page = bool(self._clients) and self._clients[-1] is ws
            with contextlib.suppress(ValueError):
                self._clients.remove(ws)
            if was_audio_page and self.on_page_event is not None:
                # A página de áudio sumiu: a conexão WebRTC dela morreu junto.
                with contextlib.suppress(Exception):
                    await self.on_page_event({"type": "rtc.state", "state": "closed"})

    async def _broadcast(self, message: dict[str, Any]) -> None:
        for ws in list(self._clients):
            with contextlib.suppress(Exception):
                await ws.send_json(message)
