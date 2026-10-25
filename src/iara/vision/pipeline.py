"""Liga VideoSource → (movimento → detector → tracker → zonas) → eventos de cena."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

import cv2
import numpy as np

from iara.domain import Frame, SceneEvent, Track
from iara.video.base import VideoSource
from iara.vision.detector import PersonDetector
from iara.vision.events import EventDetector
from iara.vision.motion import MotionGate
from iara.vision.tracker import IoUTracker

log = logging.getLogger(__name__)

EventSink = Callable[[SceneEvent], Awaitable[None]]


class ScenePipeline:
    def __init__(
        self,
        source: VideoSource,
        detector: PersonDetector,
        motion: MotionGate,
        tracker: IoUTracker,
        events: EventDetector,
        sink: EventSink,
        fps: float,
        idle_detection_interval_s: float = 5.0,
    ) -> None:
        self.source = source
        self.events = events
        self._detector = detector
        self._motion = motion
        self._tracker = tracker
        self._sink = sink
        self._fps = fps
        self._idle_interval = idle_detection_interval_s
        self._last_detection_ts = float("-inf")
        self.detector_runs = 0

    @property
    def tracks(self) -> list[Track]:
        return self._tracker.tracks

    async def run(self) -> None:
        self.source.start()
        try:
            async for frame in self.source.frames(self._fps):
                for event in await self.process(frame):
                    log.info("Cena: %s", event)
                    await self._sink(event)
        finally:
            self.source.stop()

    async def process(self, frame: Frame) -> list[SceneEvent]:
        moving = self._motion.has_motion(frame.image)
        # Com gente rastreada o detector roda sempre: pessoa parada no balcão não gera movimento.
        must_detect = (
            moving or bool(self._tracker.tracks) or frame.ts - self._last_detection_ts >= self._idle_interval
        )
        if not must_detect:
            return []
        self._last_detection_ts = frame.ts
        self.detector_runs += 1
        detections = await asyncio.to_thread(self._detector.detect, frame.image)
        update = self._tracker.update(detections, frame.ts)
        return self.events.update(update, frame.ts)


def encode_jpeg(image: np.ndarray, max_side: int = 640, quality: int = 80) -> bytes:
    """Reduz e codifica em memória. Nada é gravado em disco."""
    h, w = image.shape[:2]
    scale = min(1.0, max_side / max(h, w))
    if scale < 1.0:
        image = cv2.resize(image, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise RuntimeError("Falha ao codificar JPEG")
    return buf.tobytes()
