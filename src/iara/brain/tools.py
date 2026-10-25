from __future__ import annotations

from iara.voice.base import ToolSpec

VER_CAMERA = "ver_camera"
CHAMAR_ATENDENTE = "chamar_atendente"

TOOLS: list[ToolSpec] = [
    ToolSpec(
        name=VER_CAMERA,
        description=(
            "Obtém uma imagem atual da câmera da loja. Use quando precisar ver algo, como um produto "
            "que o cliente está mostrando no balcão."
        ),
    ),
    ToolSpec(
        name=CHAMAR_ATENDENTE,
        description="Chama um atendente humano para ajudar o cliente.",
        parameters={
            "type": "object",
            "properties": {"motivo": {"type": "string", "description": "Motivo curto, sem dados pessoais."}},
            "required": [],
        },
    ),
]
