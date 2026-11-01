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


def session_instructions(cfg: AppConfig, now: datetime, product_types: list[str] | None = None) -> str:
    """`product_types` é o vocabulário do cadastro do PDV; None quando a consulta ao PDV está desligada."""
    s = cfg.store
    pdv = product_types is not None
    products = "\n".join(
        f"- {p.name}" + (f": {p.price}" if p.price else "") + (f" ({p.notes})" if p.notes else "")
        for p in s.products
    )
    parts = [
        f"Você é a atendente virtual da loja {s.name}. Fala por um alto-falante no balcão.",
        "Sempre responda em português do Brasil, de forma curta (uma ou duas frases), simpática e natural, "
        "como uma atendente de verdade. Não use listas nem formatação.",
        "Responda apenas sobre a loja: horário, produtos, preços, formas de pagamento, localização e onde "
        "ficam os produtos. "
        "Se não souber algo ou o cliente pedir uma pessoa, use a ferramenta chamar_atendente e diga "
        "que já chamou alguém.",
        "Use ver_camera quando precisar olhar a cena, por exemplo se o cliente mostrar um produto. "
        "Nunca descreva características físicas das pessoas nem tente identificá-las.",
        "Não invente preços nem produtos que não estejam na lista."
        + (" Para os demais produtos, use consultar_produto." if pdv else ""),
        f"Agora são {now:%H:%M} de {now:%d/%m/%Y}.",
    ]
    if pdv:
        parts.append(
            "Antes de dizer se a loja vende algo ou quanto custa, use consultar_produto. Se vierem vários "
            "preços, diga a faixa (do mais barato ao mais caro) em vez de ler todos. O sistema não tem "
            "estoque confiável: nunca garanta que há unidades disponíveis; se perguntarem, diga que a "
            "atendente pode mostrar as opções."
        )
        if product_types:
            parts.append(
                "Tipos de produto no cadastro do caixa (use estas palavras em consultar_produto; um item "
                "pode estar cadastrado com um nome mais genérico): " + ", ".join(product_types)
            )
    if s.price_labels:
        parts.append(price_label_instructions(s.price_labels, pdv))
    if s.layout:
        parts.append(
            f"Onde fica cada coisa na loja (você está no balcão do caixa):\n{s.layout.strip()}\n"
            "Ao indicar onde fica algo, prefira pontos de referência (fundo da loja, atrás do caixa, em "
            "cima, móvel do centro). Se usar esquerda ou direita, diga de que ponto de vista, por exemplo "
            "'à sua esquerda, olhando para o caixa'. Se o produto não estiver nesta lista ou o cliente não "
            "achar, use chamar_atendente."
        )
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


def price_label_instructions(price_labels: str, pdv: bool) -> str:
    confirm = (
        " Antes de falar, confirme com consultar_produto usando o tipo e o preço lidos (ex.: 'caneca 15'); "
        "se não encontrar, busque só pelo preço e veja se algum item combina. Se nada confirmar, peça ao "
        "cliente para conferir o valor da etiqueta."
        if pdv
        else ""
    )
    unreadable = (
        "Se não conseguir ler a etiqueta, consulte o tipo do produto com consultar_produto e diga a faixa de "
        "preço desse tipo (ex.: 'temos canecas de 10 a 50 reais'); em seguida explique que o preço exato "
        "está na etiqueta do produto ou na plaquinha do expositor de onde ele pegou."
        if pdv
        else "Se não conseguir ler a etiqueta, explique que o preço exato está na etiqueta do produto ou na "
        "plaquinha do expositor de onde ele pegou."
    )
    return (
        f"Como o cliente encontra o preço na loja: {price_labels}\n"
        "Quando o cliente mostrar um produto ou perguntar o preço de algo que está segurando, use "
        "ver_camera, identifique o tipo do produto e procure a etiqueta de preço. Se conseguir ler o preço "
        "com clareza, diga o preço." + confirm + " " + unreadable + " Você pode pedir para mostrar a "
        "etiqueta mais perto da câmera. Nunca diga um preço exato que não leu na etiqueta. Se o cliente "
        "ainda precisar de ajuda, use chamar_atendente."
    )


SNAPSHOT_CAPTION = (
    "Imagem atual da câmera da loja (apenas contexto; não descreva as pessoas). "
    "Use-a só se ajudar a responder o cliente."
)

PRODUCT_SNAPSHOT_CAPTION = (
    "Imagem atual da câmera da loja em alta resolução (não descreva as pessoas). Se o cliente estiver "
    "mostrando um produto, identifique o tipo e procure a etiqueta de preço."
)
