import json
from datetime import datetime

import pytest

from iara.brain.brain import Brain
from iara.config import AppConfig
from iara.domain import (
    CounterOccupied,
    CounterVacated,
    CustomerWaitingUnattended,
    PeopleCountChanged,
    PersonEntered,
    PersonLingering,
)
from iara.pdv.catalog import PdvProduct
from iara.usage import UsageTracker
from iara.voice.base import (
    AssistantSpeechEnded,
    AssistantSpeechStarted,
    SessionClosed,
    ToolCallRequested,
    UsageReported,
    UserTurnEnded,
)
from iara.voice.fake import FakeVoiceSession

from .conftest import FakeClock, RecordingNotifier, RecordingUi

AFTERNOON = datetime(2026, 10, 24, 15, 0)


class Rig:
    def __init__(
        self, cfg: AppConfig, voice: FakeVoiceSession | None = None, snapshot=b"jpeg", catalog=None
    ) -> None:
        self.clock = FakeClock()
        self.voice = voice or FakeVoiceSession()
        self.notifier = RecordingNotifier()
        self.ui = RecordingUi()
        self.snapshot_sizes: list[int] = []
        self.usage = UsageTracker(cfg.prices)
        self.brain = Brain(
            cfg,
            self.voice,
            self.notifier,
            self.ui,
            self.usage,
            snapshot=lambda side: self.snapshot_sizes.append(side) or snapshot,
            catalog=catalog,
            clock=self.clock,
            now=lambda: AFTERNOON,
        )

    async def scene(self, *events) -> None:
        for e in events:
            await self.brain.handle_scene(e)

    async def voice_ev(self, *events) -> None:
        for e in events:
            await self.brain.handle_voice(e)

    def says(self) -> list[str]:
        return [arg for name, arg in self.voice.calls if name == "say"]


@pytest.fixture
def rig(app_config: AppConfig) -> Rig:
    return Rig(app_config)


async def test_greets_with_period_of_day_on_entry(rig: Rig):
    await rig.scene(PeopleCountChanged(1), PersonEntered(1))
    assert rig.voice.names()[:2] == ["start", "say"]
    assert "Boa tarde" in rig.says()[0]
    assert "falar comigo na câmera do caixa" in rig.says()[0]
    assert rig.usage.today.sessions == 1


async def test_greeting_cooldown(rig: Rig, app_config: AppConfig):
    app_config.brain.greet_after_empty_s = 0  # só o cooldown
    await rig.scene(PersonEntered(1))
    rig.clock.advance(20)
    await rig.scene(PersonEntered(2))
    assert len(rig.says()) == 1
    rig.clock.advance(61)
    await rig.scene(PersonEntered(3))
    assert len(rig.says()) == 2


async def test_greets_once_per_visit_despite_detector_flicker(rig: Rig):
    await rig.scene(PeopleCountChanged(1), PersonEntered(1))
    # Pessoa "fantasma" e troca de ID do tracker com a mesma pessoa na loja: não cumprimenta de novo.
    rig.clock.advance(90)
    await rig.scene(PeopleCountChanged(2), PersonEntered(2), PeopleCountChanged(1))
    # Loja vazia por um instante (piscar do detector) também não conta como nova visita.
    rig.clock.advance(90)
    await rig.scene(PeopleCountChanged(0))
    rig.clock.advance(3)
    await rig.scene(PeopleCountChanged(1), PersonEntered(3))
    assert len(rig.says()) == 1
    # Loja vazia de verdade: próxima entrada é uma nova visita.
    await rig.scene(PeopleCountChanged(0))
    rig.clock.advance(11)
    await rig.scene(PeopleCountChanged(1), PersonEntered(4))
    assert len(rig.says()) == 2


async def test_no_greeting_during_conversation(rig: Rig, app_config: AppConfig):
    app_config.brain.greet_after_empty_s = 0
    await rig.scene(CounterOccupied())
    await rig.voice_ev(UserTurnEnded())  # cliente falando no balcão
    rig.clock.advance(61)
    await rig.voice_ev(AssistantSpeechStarted())
    await rig.scene(PersonEntered(1))
    assert rig.says() == []  # IA falando
    await rig.voice_ev(AssistantSpeechEnded())
    rig.clock.advance(10)
    await rig.scene(PersonEntered(2))
    assert rig.says() == []  # conversa recente
    rig.clock.advance(31)
    await rig.scene(PersonEntered(3))
    assert len(rig.says()) == 1


async def test_does_not_answer_when_nobody_at_counter(rig: Rig):
    await rig.scene(PeopleCountChanged(1), PersonEntered(1))
    await rig.voice_ev(UserTurnEnded())
    assert "respond" not in rig.voice.names()


async def test_answers_at_counter_with_one_snapshot_first(rig: Rig):
    await rig.scene(PeopleCountChanged(1), CounterOccupied())
    await rig.voice_ev(UserTurnEnded())
    assert rig.voice.names()[-2:] == ["add_image", "respond"]
    assert rig.ui.states[-1] == "thinking"
    await rig.voice_ev(AssistantSpeechStarted())
    assert rig.ui.states[-1] == "speaking"
    await rig.voice_ev(AssistantSpeechEnded(), UserTurnEnded())
    # segundo turno não manda outra imagem
    assert rig.voice.names()[-2:] == ["respond", "respond"]
    assert rig.usage.today.images_sent == 1


async def test_ui_listening_at_counter_and_idle_without_session(rig: Rig):
    assert rig.ui.states == []
    await rig.scene(CounterOccupied())
    assert rig.ui.states[-1] == "listening"
    await rig.voice_ev(SessionClosed("x"))
    await rig.voice.stop()
    await rig.scene(CounterVacated())
    assert rig.ui.states[-1] == "idle"


async def test_tool_ver_camera_sends_result_image_and_continues(rig: Rig):
    await rig.scene(CounterOccupied())
    await rig.voice_ev(ToolCallRequested("c1", "ver_camera"))
    assert rig.voice.names()[-3:] == ["tool_result", "add_image", "respond"]
    assert '"ok": true' in rig.voice.calls[-3][1][1]


async def test_tool_ver_camera_without_video(app_config: AppConfig):
    rig = Rig(app_config, snapshot=None)
    await rig.scene(CounterOccupied())
    await rig.voice_ev(ToolCallRequested("c1", "ver_camera"))
    assert rig.voice.names()[-2:] == ["tool_result", "respond"]
    assert '"ok": false' in rig.voice.calls[-2][1][1]


async def test_tool_chamar_atendente_notifies(rig: Rig):
    await rig.scene(CounterOccupied())
    await rig.voice_ev(ToolCallRequested("c2", "chamar_atendente", {"motivo": "troca de produto"}))
    assert rig.notifier.sent == [
        ("chamar_atendente", "Cliente no balcão pediu atendimento: troca de produto")
    ]
    assert rig.voice.names()[-2:] == ["tool_result", "respond"]


async def test_alerts_have_cooldown(rig: Rig):
    await rig.scene(CustomerWaitingUnattended(50), CustomerWaitingUnattended(60))
    await rig.scene(PersonLingering(3, 130))
    kinds = [k for k, _ in rig.notifier.sent]
    assert kinds == ["cliente_esperando", "pessoa_parada"]
    rig.clock.advance(301)
    await rig.scene(CustomerWaitingUnattended(50))
    assert len(rig.notifier.sent) == 3


async def test_session_closes_after_store_empty(rig: Rig):
    await rig.scene(PeopleCountChanged(1), PersonEntered(1))
    await rig.scene(PeopleCountChanged(0))
    rig.clock.advance(30)
    await rig.brain.tick()
    assert rig.voice.active
    rig.clock.advance(31)
    await rig.brain.tick()
    assert not rig.voice.active
    assert rig.voice.calls[-1] == ("stop", "loja vazia")


async def test_session_not_closed_while_speaking(rig: Rig):
    await rig.scene(PersonEntered(1))
    await rig.voice_ev(AssistantSpeechStarted())
    rig.clock.advance(120)
    await rig.brain.tick()
    assert rig.voice.active


async def test_start_failure_backs_off_and_reopens_for_counter(app_config: AppConfig):
    voice = FakeVoiceSession(fail_start=True)
    rig = Rig(app_config, voice=voice)
    await rig.scene(CounterOccupied())
    assert rig.voice.names() == ["start"]
    rig.clock.advance(5)
    await rig.brain.tick()
    assert rig.voice.names() == ["start"]  # ainda no intervalo de nova tentativa
    voice.fail_start = False
    rig.clock.advance(6)
    await rig.brain.tick()
    assert rig.voice.names() == ["start", "start"]
    assert rig.voice.active


async def test_force_attending_debug_mode(rig: Rig):
    await rig.brain.set_force_attending(True)
    await rig.voice_ev(UserTurnEnded())
    assert rig.voice.names() == ["start", "add_image", "respond"]


async def test_usage_is_recorded(rig: Rig):
    await rig.voice_ev(UsageReported(input_audio=1000, output_audio=2000))
    assert rig.usage.today.responses == 1
    assert rig.usage.today.cost_usd(rig.usage.prices) == pytest.approx(0.05)


class FakeCatalog:
    def __init__(self, products: list[PdvProduct] | None = None, fail: bool = False) -> None:
        self.products = products or []
        self.fail = fail
        self.queries: list[str] = []

    def types(self) -> list[str]:
        if self.fail:
            raise OSError("arquivo travado")
        return ["BISCOITO", "CANECA"]

    def search(self, query: str) -> list[PdvProduct]:
        self.queries.append(query)
        if self.fail:
            raise OSError("arquivo travado")
        return self.products


async def test_pdv_tool_and_instructions_only_when_catalog(app_config: AppConfig):
    rig = Rig(app_config)
    await rig.scene(CounterOccupied())
    assert "consultar_produto" not in rig.voice.calls[0][1]

    rig = Rig(app_config, catalog=FakeCatalog())
    await rig.scene(CounterOccupied())
    assert "consultar_produto" in rig.voice.calls[0][1]


async def test_tool_consultar_produto_returns_prices(app_config: AppConfig):
    catalog = FakeCatalog([PdvProduct("C15,00", "CANECA 15,00", 15.0)])
    rig = Rig(app_config, catalog=catalog)
    await rig.scene(CounterOccupied())
    await rig.voice_ev(ToolCallRequested("c3", "consultar_produto", {"busca": " caneca 15 "}))
    assert catalog.queries == ["caneca 15"]
    assert rig.voice.names()[-2:] == ["tool_result", "respond"]
    result = json.loads(rig.voice.calls[-2][1][1])
    assert result == {
        "ok": True,
        "total": 1,
        "produtos": [{"descricao": "CANECA 15,00", "preco": "R$ 15,00"}],
    }


async def test_tool_consultar_produto_gives_price_range_for_few_results(app_config: AppConfig):
    products = [PdvProduct("B1", "BOLO 10,00", 10.0), PdvProduct("B5", "BOLO 50,00", 50.0)]
    rig = Rig(app_config, catalog=FakeCatalog(products))
    await rig.scene(CounterOccupied())
    await rig.voice_ev(ToolCallRequested("c7", "consultar_produto", {"busca": "bolo"}))
    result = json.loads(rig.voice.calls[-2][1][1])
    assert result["faixa_de_preco"] == "de R$ 10,00 a R$ 50,00"
    assert "tipos" not in result


async def test_tool_consultar_produto_limits_results_and_gives_price_range(app_config: AppConfig):
    app_config.pdv.max_results = 2
    products = [PdvProduct(f"C{i}", f"CANECA {i},00", float(i)) for i in (4, 5, 10, 25)]
    rig = Rig(app_config, catalog=FakeCatalog(products))
    await rig.scene(CounterOccupied())
    await rig.voice_ev(ToolCallRequested("c4", "consultar_produto", {"busca": "caneca"}))
    result = json.loads(rig.voice.calls[-2][1][1])
    assert result["total"] == 4
    assert len(result["produtos"]) == 2
    assert result["faixa_de_preco"] == "de R$ 4,00 a R$ 25,00"
    assert result["tipos"] == ["CANECA"]


async def test_tool_consultar_produto_reports_failure(app_config: AppConfig):
    rig = Rig(app_config, catalog=FakeCatalog(fail=True))
    await rig.scene(CounterOccupied())
    await rig.voice_ev(ToolCallRequested("c5", "consultar_produto", {"busca": "biscoito"}))
    assert json.loads(rig.voice.calls[-2][1][1]) == {"ok": False, "erro": "sistema de produtos indisponível"}
    assert rig.voice.names()[-1] == "respond"


async def test_ver_camera_sends_high_detail_image_and_first_turn_low(rig: Rig):
    await rig.scene(CounterOccupied())
    await rig.voice_ev(UserTurnEnded())
    await rig.voice_ev(ToolCallRequested("c6", "ver_camera"))
    bc = rig.brain._bc
    assert rig.snapshot_sizes == [bc.snapshot_max_side, bc.product_snapshot_max_side]
    assert [high for _, high in rig.voice.images] == [False, True]


async def test_session_lists_pdv_product_types(app_config: AppConfig):
    rig = Rig(app_config, catalog=FakeCatalog())
    await rig.scene(CounterOccupied())
    assert "Tipos de produto no cadastro do caixa" in rig.voice.calls[0][1]
    assert "BISCOITO, CANECA" in rig.voice.calls[0][1]


async def test_session_opens_even_if_pdv_types_fail(app_config: AppConfig):
    rig = Rig(app_config, catalog=FakeCatalog(fail=True))
    await rig.scene(CounterOccupied())
    assert rig.voice.active
    assert "consultar_produto" in rig.voice.calls[0][1]
    assert "Tipos de produto" not in rig.voice.calls[0][1]


async def test_price_label_flow_only_when_configured(app_config: AppConfig):
    rig = Rig(app_config)
    await rig.scene(CounterOccupied())
    assert "etiqueta de preço" not in rig.voice.calls[0][1]

    app_config.store.price_labels = "Todo produto tem etiqueta com o preço."
    rig = Rig(app_config)
    await rig.scene(CounterOccupied())
    instructions = rig.voice.calls[0][1]
    assert "Todo produto tem etiqueta com o preço." in instructions
    assert "Nunca diga um preço exato" in instructions
    assert "consultar_produto" not in instructions  # sem PDV, não manda confirmar no cadastro

    rig = Rig(app_config, catalog=FakeCatalog())
    await rig.scene(CounterOccupied())
    assert "confirme com consultar_produto" in rig.voice.calls[0][1]
    assert "diga a faixa de preço desse tipo" in rig.voice.calls[0][1]


async def test_store_layout_in_instructions(app_config: AppConfig):
    rig = Rig(app_config)
    await rig.scene(CounterOccupied())
    assert "Onde fica cada coisa" not in rig.voice.calls[0][1]

    app_config.store.layout = "- Bonés: na parte de cima.\n"
    rig = Rig(app_config)
    await rig.scene(CounterOccupied())
    instructions = rig.voice.calls[0][1]
    assert "(você está no balcão do caixa):\n- Bonés: na parte de cima.\n" in instructions
    assert "de que ponto de vista" in instructions
