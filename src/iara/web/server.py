from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path

import cv2
import numpy as np
from fastapi import FastAPI, HTTPException, Request, WebSocket
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from iara.app import Runtime
from iara.vision.pipeline import ScenePipeline, encode_jpeg

STATIC = Path(__file__).parent / "static"
_STREAM_FPS = 15


class TalkRequest(BaseModel):
    on: bool


def create_app(runtime: Runtime) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await runtime.start()
        yield
        await runtime.stop()

    app = FastAPI(title="IARA", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store"})

    @app.websocket("/ws")
    async def ws(websocket: WebSocket) -> None:
        await runtime.hub.serve(websocket)

    @app.post("/api/rtc/offer")
    async def rtc_offer(request: Request) -> Response:
        sdp = (await request.body()).decode("utf-8")
        try:
            answer = await runtime.voice.handle_offer(sdp)
        except Exception as exc:
            raise HTTPException(
                status_code=502, detail=f"Falha ao conectar à IA: {exc.__class__.__name__}"
            ) from exc
        return Response(content=answer, media_type="application/sdp")

    @app.get("/healthz")
    async def healthz() -> JSONResponse:
        p = runtime.pipeline
        status = p.events.status if p else None
        return JSONResponse(
            {
                "video": None if p is None else {"source": p.source.name, "online": p.source.online},
                "page_connected": runtime.hub.connected,
                "voice_active": runtime.voice.active,
                "scene": None if status is None else asdict(status),
                "usage_today": asdict(runtime.usage.today),
                "cost_today_usd": round(runtime.usage.today.cost_usd(runtime.cfg.prices), 4),
            }
        )

    @app.post("/api/debug/talk")
    async def debug_talk(req: TalkRequest) -> JSONResponse:
        await runtime.brain.set_force_attending(req.on)
        return JSONResponse({"force_attending": req.on, "voice_active": runtime.voice.active})

    @app.get("/api/debug/frame.jpg")
    async def debug_frame() -> Response:
        """Quadro atual com zonas e pessoas desenhadas, para calibrar as zonas. Não é gravado."""
        p = runtime.pipeline
        frame = p.source.latest() if p else None
        if p is None or frame is None:
            raise HTTPException(status_code=404, detail="sem vídeo")
        jpeg = encode_jpeg(annotate(p, frame.image), 960)
        return Response(jpeg, media_type="image/jpeg", headers={"Cache-Control": "no-store"})

    @app.get("/api/debug/stream.mjpg")
    async def debug_stream(request: Request) -> StreamingResponse:
        """Vídeo ao vivo (MJPEG) com zonas e pessoas, só para o painel de debug. Nada é gravado."""
        p = runtime.pipeline
        if p is None:
            raise HTTPException(status_code=404, detail="sem vídeo")

        async def frames() -> AsyncIterator[bytes]:
            last_ts = -1.0
            while not await request.is_disconnected():
                frame = p.source.latest()
                if frame is not None and frame.ts != last_ts:
                    last_ts = frame.ts
                    jpeg = encode_jpeg(annotate(p, frame.image), 960, quality=70)
                    yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
                await asyncio.sleep(1 / _STREAM_FPS)

        return StreamingResponse(
            frames(),
            media_type="multipart/x-mixed-replace; boundary=frame",
            headers={"Cache-Control": "no-store"},
        )

    return app


_ZONE_COLORS = {"door": (0, 200, 255), "counter": (0, 255, 0), "staff": (255, 120, 0)}


def annotate(p: ScenePipeline, image: np.ndarray) -> np.ndarray:
    """Desenha zonas, caixas das pessoas e o ponto dos pés sobre uma cópia do quadro."""
    img = image.copy()
    h, w = img.shape[:2]
    for zone in (p.events.door, p.events.counter, p.events.staff):
        if len(zone.polygon) >= 3:
            color = _ZONE_COLORS[zone.name]
            pts = [(int(x * w), int(y * h)) for x, y in zone.polygon]
            for a, b in zip(pts, pts[1:] + pts[:1], strict=True):
                cv2.line(img, a, b, color, 2)
            label_at = (min(x for x, _ in pts) + 4, min(y for _, y in pts) + 18)
            cv2.putText(img, zone.name, label_at, cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
    for t in p.tracks:
        b = t.bbox
        cv2.rectangle(img, (int(b.x1 * w), int(b.y1 * h)), (int(b.x2 * w), int(b.y2 * h)), (255, 255, 255), 2)
        fx, fy = b.foot
        cv2.circle(img, (int(fx * w), int(fy * h)), 5, (0, 0, 255), -1)
        label_at = (int(b.x1 * w), int(b.y1 * h) - 4)
        cv2.putText(img, f"#{t.id}", label_at, cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
    return img
