"""Baixa o detector de pessoas YOLOX-nano (Apache-2.0) do release oficial e confere o SHA-256.

Uso: uv run python scripts/download_model.py
"""

from __future__ import annotations

import hashlib
import sys
import urllib.request
from pathlib import Path

URL = "https://github.com/Megvii-BaseDetection/YOLOX/releases/download/0.1.1rc0/yolox_nano.onnx"
SHA256 = "c789161ed43c8269fcd4e67c67eeeb4e80c622da2eb296a20bc6007bd18a0b7d"
DEST = Path(__file__).resolve().parent.parent / "models" / "yolox_nano.onnx"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    if DEST.exists() and sha256(DEST) == SHA256:
        print(f"Modelo já presente: {DEST}")
        return 0
    DEST.parent.mkdir(parents=True, exist_ok=True)
    tmp = DEST.with_suffix(".part")
    print(f"Baixando {URL} ...")
    urllib.request.urlretrieve(URL, tmp)
    digest = sha256(tmp)
    if digest != SHA256:
        tmp.unlink()
        print(f"SHA-256 inesperado ({digest}); download descartado.", file=sys.stderr)
        return 1
    tmp.replace(DEST)
    print(f"Modelo salvo em {DEST}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
