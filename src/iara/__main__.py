"""Ponto de entrada: `uv run python -m iara` (ou `uv run iara`, se o Windows não bloquear o .exe)."""

from __future__ import annotations

import logging

import uvicorn

from iara.app import build_runtime
from iara.config import Settings
from iara.web.server import create_app


def main() -> None:
    settings = Settings()
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    runtime = build_runtime(settings)
    app = create_app(runtime)
    # Uvicorn trata SIGINT/SIGTERM (e Ctrl+C no Windows) e chama o lifespan para desligar limpo.
    # timeout_graceful_shutdown: o stream de debug fica aberto; não pode travar o desligamento.
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        log_level="warning",
        ws="websockets-sansio",
        timeout_graceful_shutdown=3,
    )


if __name__ == "__main__":
    main()
