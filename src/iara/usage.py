"""Contagem de chamadas e tokens da IA, com custo estimado. Só números, nenhum conteúdo."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date

from iara.config import PricesConfig
from iara.voice.base import UsageReported

log = logging.getLogger("iara.uso")


@dataclass(slots=True)
class UsageTotals:
    sessions: int = 0
    responses: int = 0
    images_sent: int = 0
    input_text: int = 0
    input_audio: int = 0
    input_image: int = 0
    input_cached: int = 0
    output_text: int = 0
    output_audio: int = 0

    def add(self, u: UsageReported) -> None:
        self.responses += 1
        self.input_text += u.input_text
        self.input_audio += u.input_audio
        self.input_image += u.input_image
        self.input_cached += u.input_cached
        self.output_text += u.output_text
        self.output_audio += u.output_audio

    def cost_usd(self, p: PricesConfig) -> float:
        # cached_tokens já está incluído nos de entrada; desconta e cobra pelo preço de cache
        uncached_text = max(0, self.input_text - self.input_cached)
        return (
            uncached_text * p.text_in
            + self.input_cached * p.cached_in
            + self.input_audio * p.audio_in
            + self.input_image * p.image_in
            + self.output_text * p.text_out
            + self.output_audio * p.audio_out
        ) / 1_000_000


@dataclass(slots=True)
class UsageTracker:
    prices: PricesConfig
    day: date = field(default_factory=date.today)
    today: UsageTotals = field(default_factory=UsageTotals)

    def _roll(self) -> None:
        if date.today() != self.day:
            log.info("Uso do dia %s: %s (~US$ %.4f)", self.day, self.today, self.today.cost_usd(self.prices))
            self.day = date.today()
            self.today = UsageTotals()

    def session_started(self) -> None:
        self._roll()
        self.today.sessions += 1

    def image_sent(self) -> None:
        self._roll()
        self.today.images_sent += 1

    def record(self, u: UsageReported) -> None:
        self._roll()
        self.today.add(u)
        log.info(
            "Resposta: in(texto=%d áudio=%d imagem=%d cache=%d) out(texto=%d áudio=%d) | "
            "hoje: %d sessões, %d respostas, ~US$ %.4f",
            u.input_text,
            u.input_audio,
            u.input_image,
            u.input_cached,
            u.output_text,
            u.output_audio,
            self.today.sessions,
            self.today.responses,
            self.today.cost_usd(self.prices),
        )
