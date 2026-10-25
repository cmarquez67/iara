from __future__ import annotations

from datetime import datetime

from iara.config import AppConfig


def period_greeting(now: datetime) -> str:
    if 5 <= now.hour < 12:
        return "Bom dia"
    if 12 <= now.hour < 18:
        return "Boa tarde"
    return "Boa noite"


def greeting_text(cfg: AppConfig, now: datetime) -> str:
    return cfg.texts.greeting.format(periodo=period_greeting(now), loja=cfg.store.name)


def greeting_instructions(cfg: AppConfig, now: datetime) -> str:
    return (
        "Uma pessoa acabou de entrar na loja. Cumprimente-a em português do Brasil, com voz "
        f'calorosa e natural, dizendo apenas: "{greeting_text(cfg, now)}". Não acrescente mais nada.'
    )


def session_instructions(cfg: AppConfig, now: datetime) -> str:
    s = cfg.store
    products = "\n".join(
        f"- {p.name}" + (f": {p.price}" if p.price else "") + (f" ({p.notes})" if p.notes else "")
        for p in s.products
    )
    parts = [
        f"Você é a atendente virtual da loja {s.name}. Fala por um alto-falante no balcão.",
        "Sempre responda em português do Brasil, de forma curta (uma ou duas frases), simpática e natural, "
        "como uma atendente de verdade. Não use listas nem formatação.",
        "Responda apenas sobre a loja: horário, produtos, preços, formas de pagamento e localização. "
        "Se não souber algo ou o cliente pedir uma pessoa, use a ferramenta chamar_atendente e diga "
        "que já chamou alguém.",
        "Use ver_camera quando precisar olhar a cena, por exemplo se o cliente mostrar um produto. "
        "Nunca descreva características físicas das pessoas nem tente identificá-las.",
        "Não invente preços nem produtos que não estejam na lista.",
        f"Agora são {now:%H:%M} de {now:%d/%m/%Y}.",
    ]
    if s.hours:
        parts.append(f"Horário de funcionamento: {s.hours}")
    if s.address:
        parts.append(f"Endereço: {s.address}")
    if products:
        parts.append(f"Produtos e preços:\n{products}")
    if s.extra_info:
        parts.append(f"Outras informações: {s.extra_info}")
    if cfg.texts.extra_instructions:
        parts.append(cfg.texts.extra_instructions)
    return "\n".join(parts)


SNAPSHOT_CAPTION = (
    "Imagem atual da câmera da loja (apenas contexto; não descreva as pessoas). "
    "Use-a só se ajudar a responder o cliente."
)
