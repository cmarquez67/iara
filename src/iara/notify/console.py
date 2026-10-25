from __future__ import annotations

import logging

log = logging.getLogger("iara.aviso")


class ConsoleNotifier:
    async def notify(self, kind: str, message: str) -> None:
        log.warning("[AVISO %s] %s", kind, message)
