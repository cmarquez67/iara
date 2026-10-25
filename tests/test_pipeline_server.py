"""Pipeline de cena com detector falso + servidor web sem hardware."""

from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from iara.app import build_runtime
from iara.config import DetectionConfig, Settings, VideoSourceKind
from iara.domain import BBox, CounterOccupied, Detection, Frame, PersonEntered
from iara.vision.detector import YoloxOnnxDetector
from iara.vision.events import EventDetector
from iara.vision.motion import MotionGate
from iara.vision.pipeline import ScenePipeline, encode_jpeg
from iara.vision.tracker import IoUTracker
from iara.web.server import create_app

from .conftest import ZONES, person_at

ROOT = Path(__file__).parent.parent
MODEL = ROOT / "models" / "yolox_nano.onnx"


class ScriptedDetector:
    def __init__(self, script: list[list[Detection]]) -> None:
        self.script = script
        self.calls = 0

    def detect(self, image: np.ndarray) -> list[Detection]:
        out = self.script[min(self.calls, len(self.script) - 1)]
        self.calls += 1
        return out


class NullSource:
    name = "null"
    online = True

    def start(self) -> None: ...
    def stop(self) -> None: ...
    def latest(self):
        return None

    async def frames(self, fps):  # pragma: no cover
        return
        yield


def blank(i: int) -> Frame:
    return Frame(np.zeros((240, 320, 3), np.uint8), ts=i * 0.5)


async def test_pipeline_skips_detector_on_static_empty_scene():
    det = ScriptedDetector([[]])
    pipe = ScenePipeline(
        NullSource(),
        det,
        MotionGate(),
        IoUTracker(),
        EventDetector(ZONES, DetectionConfig()),
        sink=None,
        fps=2,
        idle_detection_interval_s=5.0,  # type: ignore[arg-type]
    )
    for i in range(10):  # 5 s de quadros pretos
        await pipe.process(blank(i))
    assert det.calls <= 2  # primeiro quadro + verificação periódica


async def test_pipeline_emits_entry_and_counter_events():
    walk = [[person_at(x, y)] for x, y in [(0.9, 0.9), (0.8, 0.88), (0.7, 0.86), (0.6, 0.84), (0.45, 0.8)]]
    det = ScriptedDetector(walk)
    pipe = ScenePipeline(
        NullSource(),
        det,
        MotionGate(threshold=0.0),
        IoUTracker(),
        EventDetector(ZONES, DetectionConfig()),
        sink=None,
        fps=2,  # type: ignore[arg-type]
    )
    events = []
    for i in range(len(walk)):
        events += await pipe.process(blank(i))
    assert any(isinstance(e, PersonEntered) for e in events)
    assert any(isinstance(e, CounterOccupied) for e in events)


def test_encode_jpeg_downscales_in_memory():
    jpeg = encode_jpeg(np.zeros((1440, 2560, 3), np.uint8), max_side=640)
    img = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
    assert max(img.shape[:2]) == 640


@pytest.mark.skipif(not MODEL.exists(), reason="modelo não baixado (scripts/download_model.py)")
def test_yolox_detector_on_blank_and_shapes():
    det = YoloxOnnxDetector(MODEL)
    assert det.detect(np.zeros((480, 640, 3), np.uint8)) == []
    person = ROOT / "tests" / "fixtures" / "person.jpg"
    if person.exists():
        found = det.detect(cv2.imread(str(person)))
        assert found and all(isinstance(d.bbox, BBox) for d in found)


def test_server_ws_and_health_without_hardware(tmp_path: Path):
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None, video_source=VideoSourceKind.NONE, config_file=ROOT / "config.example.yaml"
    )
    runtime = build_runtime(settings)
    with TestClient(create_app(runtime)) as client:
        assert client.get("/").status_code == 200
        assert client.get("/static/orb.js").status_code == 200
        with client.websocket_connect("/ws") as ws:
            assert ws.receive_json() == {"type": "config", "duplex": "full"}
            assert ws.receive_json() == {"type": "state", "state": "idle"}
            health = client.get("/healthz").json()
            assert health["page_connected"] is True
            assert health["video"] is None
            assert health["voice_active"] is False
        assert client.get("/api/debug/frame.jpg").status_code == 404
        # Sem sessão solicitada, a oferta é recusada sem chamar a OpenAI.
        assert client.post("/api/rtc/offer", content="v=0").status_code == 502
