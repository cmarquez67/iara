"""Vídeo e configuração: troca de fonte só pelo .env, e arquivo simulando o stream RTSP."""

import asyncio
import os
import shutil
import subprocess
from pathlib import Path

import cv2
import numpy as np
import pytest

from iara.config import AppConfig, Settings, VideoSourceKind, load_app_config
from iara.video.opencv_source import create_video_source, mask_credentials

ROOT = Path(__file__).parent.parent


def make_settings(**kw) -> Settings:
    return Settings(_env_file=None, **kw)  # type: ignore[call-arg]


def test_rtsp_url_from_parts_escapes_password():
    s = make_settings(rtsp_host="192.168.0.50", rtsp_user="loja", rtsp_password="p@ss:1", rtsp_path="stream2")
    assert s.resolved_rtsp_url() == "rtsp://loja:p%40ss%3A1@192.168.0.50:554/stream2"


def test_rtsp_url_override_wins():
    s = make_settings(rtsp_url="rtsp://a:b@cam/stream1", rtsp_host="ignorado")
    assert s.resolved_rtsp_url() == "rtsp://a:b@cam/stream1"


def test_mask_credentials():
    assert (
        mask_credentials("rtsp://loja:segredo@10.0.0.2:554/stream2") == "rtsp://***:***@10.0.0.2:554/stream2"
    )


@pytest.mark.parametrize(
    ("kind", "extra", "name"),
    [
        (VideoSourceKind.WEBCAM, {}, "webcam"),
        (VideoSourceKind.RTSP, {"rtsp_host": "10.0.0.2"}, "rtsp"),
        (VideoSourceKind.FILE, {"video_file": "x.mp4"}, "file"),
    ],
)
def test_factory_picks_source_from_config(kind, extra, name):
    src = create_video_source(make_settings(video_source=kind, **extra))
    assert src is not None and src.name == name


def test_factory_none():
    assert create_video_source(make_settings(video_source=VideoSourceKind.NONE)) is None


def test_example_config_is_valid():
    cfg = load_app_config(ROOT / "config.example.yaml")
    assert isinstance(cfg, AppConfig)
    assert len(cfg.zones.counter) >= 3
    assert cfg.store.products


def write_test_video(path: Path, frames: int = 30, size=(320, 240)) -> None:
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 15, size)
    assert writer.isOpened()
    for i in range(frames):
        img = np.zeros((size[1], size[0], 3), np.uint8)
        cv2.rectangle(img, (10 + i * 5, 80), (50 + i * 5, 200), (255, 255, 255), -1)
        writer.write(img)
    writer.release()


async def test_file_source_delivers_frames_like_a_stream(tmp_path: Path):
    """Mesmo caminho de código do RTSP (cv2.VideoCapture + FFMPEG), lido em loop."""
    video = tmp_path / "amostra.mp4"
    write_test_video(video)
    src = create_video_source(make_settings(video_source=VideoSourceKind.FILE, video_file=str(video)))
    assert src is not None
    src.start()
    try:
        got = []
        async with asyncio.timeout(10):
            async for frame in src.frames(fps=10):
                got.append(frame)
                if len(got) == 5:
                    break
        assert src.online
        assert got[0].image.shape == (240, 320, 3)
        assert len({f.ts for f in got}) == 5  # só quadros novos
    finally:
        src.stop()
    assert not src.online


async def test_unreachable_source_stays_offline_without_crashing():
    src = create_video_source(make_settings(video_source=VideoSourceKind.FILE, video_file="/nao/existe.mp4"))
    assert src is not None
    src.start()
    await asyncio.sleep(0.3)
    assert not src.online
    assert src.latest() is None
    src.stop()


@pytest.mark.integration
async def test_real_rtsp_server(tmp_path: Path):
    """Opcional: precisa de mediamtx rodando em localhost:8554 e ffmpeg no PATH.

    uv run pytest -m integration
    """
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg não encontrado")
    video = tmp_path / "amostra.mp4"
    write_test_video(video, frames=60)
    url = os.environ.get("IARA_TEST_RTSP", "rtsp://127.0.0.1:8554/stream2")
    pub = subprocess.Popen(
        [
            "ffmpeg",
            "-loglevel",
            "error",
            "-re",
            "-stream_loop",
            "-1",
            "-i",
            str(video),
            "-c",
            "copy",
            "-f",
            "rtsp",
            "-rtsp_transport",
            "tcp",
            url,
        ]
    )
    try:
        await asyncio.sleep(2)
        src = create_video_source(make_settings(video_source=VideoSourceKind.RTSP, rtsp_url=url))
        assert src is not None
        src.start()
        async with asyncio.timeout(15):
            async for frame in src.frames(fps=2):
                assert frame.image.shape[2] == 3
                break
        src.stop()
    finally:
        pub.terminate()
