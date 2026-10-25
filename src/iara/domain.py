"""Tipos de domínio, independentes de câmera, detector e provedor de IA."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass(frozen=True, slots=True)
class Frame:
    image: np.ndarray  # BGR, HxWx3
    ts: float  # time.monotonic() da captura


@dataclass(frozen=True, slots=True)
class BBox:
    """Caixa em coordenadas normalizadas (0..1)."""

    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def foot(self) -> tuple[float, float]:
        """Ponto do chão (base central): o que define em que zona a pessoa está."""
        return ((self.x1 + self.x2) / 2, self.y2)

    @property
    def center(self) -> tuple[float, float]:
        return ((self.x1 + self.x2) / 2, (self.y1 + self.y2) / 2)

    @property
    def area(self) -> float:
        return max(0.0, self.x2 - self.x1) * max(0.0, self.y2 - self.y1)

    def iou(self, other: BBox) -> float:
        ix1, iy1 = max(self.x1, other.x1), max(self.y1, other.y1)
        ix2, iy2 = min(self.x2, other.x2), min(self.y2, other.y2)
        inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
        union = self.area + other.area - inter
        return inter / union if union > 0 else 0.0


@dataclass(frozen=True, slots=True)
class Detection:
    bbox: BBox
    score: float


@dataclass(slots=True)
class Track:
    id: int
    bbox: BBox
    first_seen: float
    last_seen: float
    history: list[tuple[float, tuple[float, float]]] = field(default_factory=list)  # (ts, pé)


# --- Eventos de cena (saída do EventDetector) ---


@dataclass(frozen=True, slots=True)
class PersonEntered:
    track_id: int


@dataclass(frozen=True, slots=True)
class PersonLeft:
    track_id: int


@dataclass(frozen=True, slots=True)
class PeopleCountChanged:
    count: int


@dataclass(frozen=True, slots=True)
class CounterOccupied:
    pass


@dataclass(frozen=True, slots=True)
class CounterVacated:
    pass


@dataclass(frozen=True, slots=True)
class PersonLingering:
    track_id: int
    seconds: float


@dataclass(frozen=True, slots=True)
class CustomerWaitingUnattended:
    seconds: float


SceneEvent = (
    PersonEntered
    | PersonLeft
    | PeopleCountChanged
    | CounterOccupied
    | CounterVacated
    | PersonLingering
    | CustomerWaitingUnattended
)
