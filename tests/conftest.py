from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from iara.config import AppConfig, ZonesConfig
from iara.domain import BBox, Detection


@dataclass
class FakeClock:
    t: float = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, s: float) -> None:
        self.t += s


@dataclass
class RecordingNotifier:
    sent: list[tuple[str, str]] = field(default_factory=list)

    async def notify(self, kind: str, message: str) -> None:
        self.sent.append((kind, message))


@dataclass
class RecordingUi:
    states: list[str] = field(default_factory=list)

    async def set_state(self, state) -> None:  # type: ignore[no-untyped-def]
        self.states.append(state.value)


# Cena de teste: porta à direita, balcão embaixo à esquerda, atendente no canto superior esquerdo.
ZONES = ZonesConfig(
    door=[(0.75, 0.3), (1.0, 0.3), (1.0, 1.0), (0.75, 1.0)],
    counter=[(0.0, 0.6), (0.5, 0.6), (0.5, 1.0), (0.0, 1.0)],
    staff=[(0.0, 0.0), (0.25, 0.0), (0.25, 0.45), (0.0, 0.45)],
)


def person_at(fx: float, fy: float, w: float = 0.1, h: float = 0.3, score: float = 0.9) -> Detection:
    """Detecção cujo ponto dos pés fica em (fx, fy)."""
    return Detection(BBox(fx - w / 2, fy - h, fx + w / 2, fy), score)


@pytest.fixture
def app_config() -> AppConfig:
    return AppConfig(zones=ZONES)
