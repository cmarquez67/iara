from __future__ import annotations

from typing import Protocol


class Notifier(Protocol):
    """Avisos para o dono da loja. MVP: console; depois WhatsApp/Telegram."""

    async def notify(self, kind: str, message: str) -> None: ...
