"""Webcam, RTSP e arquivo pelo mesmo caminho de código (cv2.VideoCapture)."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import threading
import time
from collections.abc import AsyncIterator

import cv2

from iara.config import Settings, VideoSourceKind
from iara.domain import Frame

log = logging.getLogger(__name__)

# RTSP por TCP evita quadros corrompidos em Wi-Fi com perda de pacotes.
os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp|timeout;5000000")

_BACKENDS = {
    "any": cv2.CAP_ANY,
    "dshow": cv2.CAP_DSHOW,
    "msmf": cv2.CAP_MSMF,
    "v4l2": cv2.CAP_V4L2,
    "ffmpeg": cv2.CAP_FFMPEG,
}


def mask_credentials(url: str) -> str:
    return re.sub(r"//[^/@]+@", "//***:***@", url)


class OpenCvSource:
    """Lê numa thread própria e guarda só o quadro mais recente (descarta o buffer acumulado).

    Reconecta sozinha com espera crescente se a captura falhar (câmera offline, Wi-Fi caiu).
    """

    def __init__(
        self,
        target: int | str,
        name: str,
        backend: int = cv2.CAP_ANY,
        loop_file: bool = False,
        max_backoff_s: float = 30.0,
    ) -> None:
        self.name = name
        self._target = target
        self._backend = backend
        self._loop_file = loop_file
        self._max_backoff_s = max_backoff_s
        self._lock = threading.Lock()
        self._latest: Frame | None = None
        self._online = False
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def online(self) -> bool:
        return self._online

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name=f"video-{self.name}", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        self._online = False

    def latest(self) -> Frame | None:
        with self._lock:
            return self._latest

    async def frames(self, fps: float) -> AsyncIterator[Frame]:
        interval = 1.0 / fps
        last_ts = -1.0
        while not self._stop.is_set():
            await asyncio.sleep(interval)
            frame = self.latest()
            if frame is not None and frame.ts != last_ts:
                last_ts = frame.ts
                yield frame

    def _open(self) -> cv2.VideoCapture:
        return cv2.VideoCapture(self._target, self._backend)

    def _run(self) -> None:
        backoff = 1.0
        label = mask_credentials(str(self._target))
        while not self._stop.is_set():
            cap = self._open()
            if not cap.isOpened():
                log.warning("Vídeo %s indisponível (%s); nova tentativa em %.0fs", self.name, label, backoff)
                cap.release()
                self._stop.wait(backoff)
                backoff = min(backoff * 2, self._max_backoff_s)
                continue

            log.info("Vídeo %s conectado (%s)", self.name, label)
            self._online = True
            backoff = 1.0
            file_fps = (cap.get(cv2.CAP_PROP_FPS) or 25.0) if self._loop_file else 0.0
            try:
                while not self._stop.is_set():
                    ok, image = cap.read()
                    if not ok:
                        if self._loop_file:
                            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                            ok, image = cap.read()
                        if not ok:
                            log.warning("Vídeo %s parou de entregar quadros; reconectando", self.name)
                            break
                    with self._lock:
                        self._latest = Frame(image=image, ts=time.monotonic())
                    if file_fps:
                        time.sleep(1.0 / file_fps)  # arquivo: simula tempo real
            finally:
                self._online = False
                cap.release()


def create_video_source(settings: Settings) -> OpenCvSource | None:
    """Única função que sabe de onde vem o vídeo. Todo o resto recebe só `Frame`."""
    match settings.video_source:
        case VideoSourceKind.NONE:
            return None
        case VideoSourceKind.WEBCAM:
            backend = _BACKENDS.get(settings.webcam_backend.lower(), cv2.CAP_ANY)
            return OpenCvSource(settings.webcam_index, "webcam", backend=backend)
        case VideoSourceKind.RTSP:
            return OpenCvSource(settings.resolved_rtsp_url(), "rtsp", backend=cv2.CAP_FFMPEG)
        case VideoSourceKind.FILE:
            if not settings.video_file:
                raise ValueError("Defina VIDEO_FILE para VIDEO_SOURCE=file")
            return OpenCvSource(settings.video_file, "file", backend=cv2.CAP_FFMPEG, loop_file=True)
