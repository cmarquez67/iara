"""Composição: o único lugar que escolhe implementações a partir da configuração."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from iara.brain.brain import Brain
from iara.config import AppConfig, Settings, load_app_config
from iara.domain import SceneEvent
from iara.notify.console import ConsoleNotifier
from iara.usage import UsageTracker
from iara.video.opencv_source import create_video_source
from iara.vision.detector import YoloxOnnxDetector
from iara.vision.events import EventDetector
from iara.vision.motion import MotionGate
from iara.vision.pipeline import ScenePipeline, encode_jpeg
from iara.vision.tracker import IoUTracker
from iara.voice.openai_realtime import OpenAIRealtimeSession
from iara.web.hub import PageHub

log = logging.getLogger(__name__)


async def supervise(name: str, factory: Callable[[], Awaitable[None]], max_backoff_s: float = 30.0) -> None:
    """Roda a corrotina para sempre; se cair, registra e reinicia com espera crescente."""
    backoff = 1.0
    while True:
        started = time.monotonic()
        try:
            await factory()
            log.warning("%s terminou; reiniciando", name)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("%s caiu; reiniciando em %.0fs", name, backoff)
        if time.monotonic() - started > 60:
            backoff = 1.0
        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, max_backoff_s)


@dataclass
class Runtime:
    settings: Settings
    cfg: AppConfig
    hub: PageHub
    voice: OpenAIRealtimeSession
    brain: Brain
    usage: UsageTracker
    scene_events: asyncio.Queue[SceneEvent]
    pipeline: ScenePipeline | None = None
    _tasks: list[asyncio.Task[None]] = field(default_factory=list)

    def snapshot(self) -> bytes | None:
        frame = self.pipeline.source.latest() if self.pipeline else None
        if frame is None:
            return None
        return encode_jpeg(frame.image, self.cfg.brain.snapshot_max_side)

    async def start(self) -> None:
        self._tasks.append(asyncio.create_task(supervise("brain", lambda: self.brain.run(self.scene_events))))
        if self.pipeline is not None:
            self._tasks.append(asyncio.create_task(supervise("vídeo", self.pipeline.run)))

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        await self.voice.aclose()


def build_runtime(settings: Settings) -> Runtime:
    cfg = load_app_config(settings.config_file)
    hub = PageHub({"duplex": settings.audio_duplex.value})
    voice = OpenAIRealtimeSession(
        api_key=settings.openai_api_key.get_secret_value(),
        model=settings.openai_realtime_model,
        voice=settings.openai_voice,
        safety_id=settings.openai_safety_id,
        page=hub,
    )
    hub.on_page_event = voice.handle_page_event
    usage = UsageTracker(cfg.prices)
    scene_events: asyncio.Queue[SceneEvent] = asyncio.Queue(maxsize=100)

    runtime_ref: list[Runtime] = []
    brain = Brain(cfg, voice, ConsoleNotifier(), hub, usage, snapshot=lambda: runtime_ref[0].snapshot())
    runtime = Runtime(settings, cfg, hub, voice, brain, usage, scene_events)
    runtime_ref.append(runtime)

    source = create_video_source(settings)
    detector: YoloxOnnxDetector | None = None
    if source is not None:
        d = cfg.detection
        try:
            detector = YoloxOnnxDetector(settings.detector_model, d.score_threshold, d.nms_threshold)
        except FileNotFoundError as exc:
            log.error("%s. Vídeo desativado; só voz até corrigir.", exc)
    if source is not None and detector is not None:
        runtime.pipeline = ScenePipeline(
            source=source,
            detector=detector,
            motion=MotionGate(d.motion_threshold),
            tracker=IoUTracker(d.track_iou_threshold, d.track_max_distance, d.track_max_missed_s),
            events=EventDetector(cfg.zones, d),
            sink=scene_events.put,
            fps=settings.detection_fps,
            idle_detection_interval_s=d.idle_detection_interval_s,
        )
    elif source is None:
        log.info("Vídeo desligado (VIDEO_SOURCE=none): só voz, use o modo 'conversar agora'")
    return runtime
