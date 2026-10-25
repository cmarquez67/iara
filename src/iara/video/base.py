from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol

from iara.domain import Frame


class VideoSource(Protocol):
    """Qualquer origem de vídeo. O núcleo só conhece esta interface."""

    name: str

    @property
    def online(self) -> bool: ...

    def start(self) -> None: ...

    def stop(self) -> None: ...

    def latest(self) -> Frame | None:
        """Quadro mais recente (ou None se ainda não houver)."""
        ...

    def frames(self, fps: float) -> AsyncIterator[Frame]:
        """Quadros amostrados na taxa pedida; só entrega quadros novos."""
        ...
