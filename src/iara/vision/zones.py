from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

Point = tuple[float, float]
_EDGE = 1e-6


@dataclass(frozen=True, slots=True)
class Zone:
    name: str
    polygon: tuple[Point, ...]

    @classmethod
    def from_points(cls, name: str, points: Sequence[Sequence[float]]) -> Zone:
        return cls(name, tuple((float(x), float(y)) for x, y in points))

    def contains(self, point: Point) -> bool:
        """Ray casting. Zona vazia (não configurada) não contém nada."""
        if len(self.polygon) < 3:
            return False
        # Caixas encostadas na borda da imagem (pessoa perto da câmera) têm o pé em y=1.0;
        # traz para dentro para não cair exatamente sobre a aresta do polígono.
        x = min(max(point[0], 0.0), 1.0 - _EDGE)
        y = min(max(point[1], 0.0), 1.0 - _EDGE)
        inside = False
        n = len(self.polygon)
        for i in range(n):
            x1, y1 = self.polygon[i]
            x2, y2 = self.polygon[(i + 1) % n]
            if (y1 > y) != (y2 > y):
                x_cross = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
                if x < x_cross:
                    inside = not inside
        return inside
