from __future__ import annotations

import cv2
import numpy as np


class MotionGate:
    """Subtração de fundo (MOG2) num quadro reduzido; devolve a fração de pixels em movimento."""

    def __init__(self, threshold: float = 0.01, width: int = 320) -> None:
        self.threshold = threshold
        self._width = width
        self._mog = cv2.createBackgroundSubtractorMOG2(history=200, varThreshold=25, detectShadows=False)

    def motion_ratio(self, image: np.ndarray) -> float:
        h, w = image.shape[:2]
        scale = self._width / w
        small = cv2.resize(image, (self._width, max(1, int(h * scale))), interpolation=cv2.INTER_AREA)
        gray = cv2.GaussianBlur(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY), (5, 5), 0)
        mask = self._mog.apply(gray)
        return float(np.count_nonzero(mask)) / mask.size

    def has_motion(self, image: np.ndarray) -> bool:
        return self.motion_ratio(image) >= self.threshold
