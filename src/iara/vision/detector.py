"""Detecção de pessoas. Implementação padrão: YOLOX-nano (Apache-2.0) via ONNX Runtime, só CPU."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

import cv2
import numpy as np

from iara.domain import BBox, Detection

_PERSON_CLASS = 0


class PersonDetector(Protocol):
    def detect(self, image: np.ndarray) -> list[Detection]: ...


class YoloxOnnxDetector:
    def __init__(
        self,
        model_path: Path,
        score_threshold: float = 0.45,
        nms_threshold: float = 0.45,
        input_size: int = 416,
    ) -> None:
        import onnxruntime as ort

        if not model_path.exists():
            raise FileNotFoundError(
                f"Modelo {model_path} não encontrado. Rode: uv run python scripts/download_model.py"
            )
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 2  # deixa CPU para o resto do sistema
        self._session = ort.InferenceSession(
            str(model_path), sess_options=opts, providers=["CPUExecutionProvider"]
        )
        self._input_name = self._session.get_inputs()[0].name
        self._size = input_size
        self._score_threshold = score_threshold
        self._nms_threshold = nms_threshold
        self._grids, self._strides = _make_grids(input_size)

    def detect(self, image: np.ndarray) -> list[Detection]:
        h, w = image.shape[:2]
        blob, ratio = _letterbox(image, self._size)
        raw = self._session.run(None, {self._input_name: blob})[0][0]

        xy = (raw[:, :2] + self._grids) * self._strides
        wh = np.exp(raw[:, 2:4]) * self._strides
        scores = raw[:, 4] * raw[:, 5 + _PERSON_CLASS]
        keep = scores >= self._score_threshold
        if not np.any(keep):
            return []
        xy, wh, scores = xy[keep], wh[keep], scores[keep]

        boxes = np.concatenate([xy - wh / 2, wh], axis=1) / ratio  # x, y, w, h em pixels
        idx = cv2.dnn.NMSBoxes(boxes.tolist(), scores.tolist(), self._score_threshold, self._nms_threshold)
        out: list[Detection] = []
        for i in np.array(idx).flatten():
            x, y, bw, bh = boxes[i]
            out.append(
                Detection(
                    BBox(_clip(x / w), _clip(y / h), _clip((x + bw) / w), _clip((y + bh) / h)),
                    float(scores[i]),
                )
            )
        return out


def _clip(v: float) -> float:
    return float(min(1.0, max(0.0, v)))


def _letterbox(image: np.ndarray, size: int) -> tuple[np.ndarray, float]:
    h, w = image.shape[:2]
    ratio = min(size / h, size / w)
    resized = cv2.resize(image, (int(w * ratio), int(h * ratio)), interpolation=cv2.INTER_LINEAR)
    padded = np.full((size, size, 3), 114, dtype=np.uint8)
    padded[: resized.shape[0], : resized.shape[1]] = resized
    blob = np.ascontiguousarray(padded.transpose(2, 0, 1)[None], dtype=np.float32)
    return blob, ratio


def _make_grids(size: int) -> tuple[np.ndarray, np.ndarray]:
    grids, strides = [], []
    for stride in (8, 16, 32):
        n = size // stride
        xv, yv = np.meshgrid(np.arange(n), np.arange(n))
        grids.append(np.stack((xv, yv), 2).reshape(-1, 2))
        strides.append(np.full((n * n, 1), stride))
    return np.concatenate(grids).astype(np.float32), np.concatenate(strides).astype(np.float32)
