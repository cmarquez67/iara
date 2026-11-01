from __future__ import annotations

from iara.voice.base import ToolSpec

VER_CAMERA = "ver_camera"
CHAMAR_ATENDENTE = "chamar_atendente"
CONSULTAR_PRODUTO = "consultar_produto"

TOOLS: list[ToolSpec] = [
    ToolSpec(
        name=VER_CAMERA,
        description=(
            "Obtém uma imagem atual da câmera da loja, em resolução suficiente para ler etiquetas. Use "
            "quando precisar ver algo, como um produto que o cliente está mostrando no balcão e seu preço."
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

PDV_TOOLS: list[ToolSpec] = [
    ToolSpec(
        name=CONSULTAR_PRODUTO,
        description=(
            "Consulta produtos e preços no sistema de caixa da loja. Os produtos estão cadastrados por "
            "tipo e faixa de preço (ex.: 'CANECA 15,00'), sem estoque. Busque pelo tipo de produto e, "
            "se o cliente citar, pelo preço. Se não achar nada, tente outra palavra mais simples."
        ),
        parameters={
            "type": "object",
            "properties": {
                "busca": {
                    "type": "string",
                    "description": "Tipo de produto e opcionalmente o preço, ex.: 'caneca', 'bolo 10'.",
                }
            },
            "required": ["busca"],
        },
    ),
]
