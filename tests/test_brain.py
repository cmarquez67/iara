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
    def __init__(self, cfg: AppConfig, voice: FakeVoiceSession | None = None, snapshot=b"jpeg") -> None:
        self.clock = FakeClock()
        self.voice = voice or FakeVoiceSession()
        self.notifier = RecordingNotifier()
        self.ui = RecordingUi()
        self.usage = UsageTracker(cfg.prices)
        self.brain = Brain(
            cfg,
            self.voice,
            self.notifier,
            self.ui,
            self.usage,
            snapshot=(lambda: snapshot),
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
    assert rig.usage.today.sessions == 1


async def test_greeting_cooldown(rig: Rig):
    await rig.scene(PersonEntered(1))
    rig.clock.advance(20)
    await rig.scene(PersonEntered(2))
    assert len(rig.says()) == 1
    rig.clock.advance(61)
    await rig.scene(PersonEntered(3))
    assert len(rig.says()) == 2


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
