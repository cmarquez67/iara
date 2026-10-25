"""Configuração: segredos e escolhas de ambiente no `.env`, regras da loja no YAML."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Literal
from urllib.parse import quote

import yaml
from pydantic import BaseModel, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class VideoSourceKind(StrEnum):
    NONE = "none"
    WEBCAM = "webcam"
    RTSP = "rtsp"
    FILE = "file"


class DuplexMode(StrEnum):
    FULL = "full"
    HALF = "half"


class Settings(BaseSettings):
    """Variáveis de ambiente (ver `.env.example`)."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    openai_api_key: SecretStr = SecretStr("")
    openai_realtime_model: str = "gpt-realtime-2.1-mini"
    openai_voice: str = "marin"
    openai_safety_id: str = "iara-loja"

    video_source: VideoSourceKind = VideoSourceKind.WEBCAM
    webcam_index: int = 0
    webcam_backend: str = "any"  # any | dshow | msmf | v4l2
    rtsp_url: str = ""  # se preenchida, ignora os campos RTSP_* abaixo
    rtsp_host: str = ""
    rtsp_port: int = 554
    rtsp_user: str = ""
    rtsp_password: SecretStr = SecretStr("")
    rtsp_path: str = "stream2"
    video_file: str = ""
    detection_fps: float = 2.0
    detector_model: Path = Path("models/yolox_nano.onnx")

    audio_duplex: DuplexMode = DuplexMode.FULL

    host: str = "127.0.0.1"
    port: int = 8000
    config_file: Path = Path("config.yaml")
    log_level: str = "INFO"

    def resolved_rtsp_url(self) -> str:
        if self.rtsp_url:
            return self.rtsp_url
        if not self.rtsp_host:
            raise ValueError("Defina RTSP_URL ou RTSP_HOST para VIDEO_SOURCE=rtsp")
        auth = ""
        if self.rtsp_user:
            password = quote(self.rtsp_password.get_secret_value(), safe="")
            auth = f"{quote(self.rtsp_user, safe='')}:{password}@"
        return f"rtsp://{auth}{self.rtsp_host}:{self.rtsp_port}/{self.rtsp_path.lstrip('/')}"


Point = tuple[float, float]


class Product(BaseModel):
    name: str
    price: str = ""
    notes: str = ""


class StoreInfo(BaseModel):
    name: str = "Loja"
    hours: str = ""
    address: str = ""
    products: list[Product] = Field(default_factory=list)
    extra_info: str = ""


class ZonesConfig(BaseModel):
    """Polígonos em coordenadas normalizadas (0..1), origem no canto superior esquerdo."""

    door: list[Point] = Field(default_factory=list)
    counter: list[Point] = Field(default_factory=list)
    staff: list[Point] = Field(default_factory=list)


class DetectionConfig(BaseModel):
    # door: cumprimenta quem nasce na zona da porta e anda para dentro (loja).
    # appear: cumprimenta qualquer pessoa que fique visível por entry_confirm_s (teste com webcam).
    entry_mode: Literal["door", "appear"] = "door"
    entry_confirm_s: float = 1.0
    score_threshold: float = 0.45
    nms_threshold: float = 0.45
    motion_threshold: float = 0.01  # fração de pixels em movimento para rodar o detector
    idle_detection_interval_s: float = 5.0  # roda o detector mesmo sem movimento
    track_iou_threshold: float = 0.25
    track_max_distance: float = 0.15  # fallback por distância de centróide (normalizada)
    track_max_missed_s: float = 2.5
    counter_vacate_s: float = 3.0
    lingering_s: float = 120.0
    lingering_max_displacement: float = 0.05
    unattended_s: float = 45.0


class BrainConfig(BaseModel):
    greet_cooldown_s: float = 60.0
    alert_cooldown_s: float = 300.0
    session_idle_close_s: float = 60.0
    session_max_s: float = 25 * 60.0
    session_retry_s: float = 10.0
    snapshot_max_side: int = 640


class TextsConfig(BaseModel):
    greeting: str = "{periodo}, seja bem-vindo à {loja}!"
    extra_instructions: str = ""


class PricesConfig(BaseModel):
    """Preços em US$ por milhão de tokens, só para estimar custo no log."""

    text_in: float = 0.60
    text_out: float = 2.40
    audio_in: float = 10.0
    audio_out: float = 20.0
    image_in: float = 0.80
    cached_in: float = 0.06


class AppConfig(BaseModel):
    store: StoreInfo = Field(default_factory=StoreInfo)
    zones: ZonesConfig = Field(default_factory=ZonesConfig)
    detection: DetectionConfig = Field(default_factory=DetectionConfig)
    brain: BrainConfig = Field(default_factory=BrainConfig)
    texts: TextsConfig = Field(default_factory=TextsConfig)
    prices: PricesConfig = Field(default_factory=PricesConfig)


def load_app_config(path: Path) -> AppConfig:
    if not path.exists():
        example = path.with_name("config.example.yaml")
        if example.exists():
            path = example
        else:
            return AppConfig()
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return AppConfig.model_validate(data)
