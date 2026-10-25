import asyncio
import json

import pytest

from iara.brain.tools import TOOLS
from iara.voice.base import (
    AssistantSpeechEnded,
    AssistantSpeechStarted,
    ResponseFinished,
    ToolCallRequested,
    UsageReported,
    UserSpeechStarted,
    UserTurnEnded,
    VoiceError,
)
from iara.voice.openai_realtime import OpenAIRealtimeSession, build_session_config, map_server_event


def test_session_config_lets_backend_decide_when_to_respond():
    cfg = build_session_config("gpt-realtime-2.1-mini", "marin", "instr", TOOLS)
    td = cfg["audio"]["input"]["turn_detection"]
    assert cfg["type"] == "realtime"
    assert td["create_response"] is False
    assert td["interrupt_response"] is True
    assert cfg["audio"]["output"]["voice"] == "marin"
    assert {t["name"] for t in cfg["tools"]} == {"ver_camera", "chamar_atendente"}
    json.dumps(cfg)  # serializável


@pytest.mark.parametrize(
    ("event", "expected"),
    [
        ({"type": "input_audio_buffer.speech_started", "item_id": "i"}, [UserSpeechStarted()]),
        ({"type": "input_audio_buffer.committed", "item_id": "i"}, [UserTurnEnded()]),
        ({"type": "output_audio_buffer.started", "response_id": "r"}, [AssistantSpeechStarted()]),
        ({"type": "output_audio_buffer.stopped"}, [AssistantSpeechEnded(interrupted=False)]),
        ({"type": "output_audio_buffer.cleared"}, [AssistantSpeechEnded(interrupted=True)]),
        ({"type": "response.output_audio_transcript.delta", "delta": "oi"}, []),
        (
            {"type": "error", "error": {"type": "invalid_request_error", "code": "x", "message": "ruim"}},
            [VoiceError("ruim", "x")],
        ),
    ],
)
def test_map_simple_events(event, expected):
    assert map_server_event(event) == expected


def test_map_response_done_with_tool_call_and_usage():
    event = {
        "type": "response.done",
        "response": {
            "status": "completed",
            "output": [
                {
                    "type": "function_call",
                    "name": "chamar_atendente",
                    "call_id": "call_1",
                    "arguments": '{"motivo": "dúvida"}',
                },
                {"type": "message", "content": []},
            ],
            "usage": {
                "total_tokens": 300,
                "input_tokens": 200,
                "output_tokens": 100,
                "input_token_details": {
                    "text_tokens": 120,
                    "audio_tokens": 50,
                    "image_tokens": 30,
                    "cached_tokens": 64,
                },
                "output_token_details": {"text_tokens": 20, "audio_tokens": 80},
            },
        },
    }
    assert map_server_event(event) == [
        ToolCallRequested("call_1", "chamar_atendente", {"motivo": "dúvida"}),
        UsageReported(
            input_text=120, input_audio=50, input_image=30, input_cached=64, output_text=20, output_audio=80
        ),
        ResponseFinished("completed"),
    ]


def test_map_response_done_with_bad_arguments():
    event = {
        "type": "response.done",
        "response": {
            "status": "completed",
            "output": [{"type": "function_call", "name": "ver_camera", "call_id": "c", "arguments": "{"}],
        },
    }
    assert map_server_event(event)[0] == ToolCallRequested("c", "ver_camera", {})


class FakePage:
    def __init__(self, connected: bool = True) -> None:
        self.connected = connected
        self.sent: list[dict] = []

    async def send(self, message: dict) -> None:
        self.sent.append(message)


async def test_start_fails_fast_without_page():
    voice = OpenAIRealtimeSession("sk-test", "m", "marin", "loja", FakePage(connected=False))
    with pytest.raises(ConnectionError):
        await voice.start("i", TOOLS)
    await voice.aclose()


async def test_start_aborts_when_page_reports_webrtc_failure():
    page = FakePage()
    voice = OpenAIRealtimeSession("sk-test", "m", "marin", "loja", page, connect_timeout_s=5)
    task = asyncio.create_task(voice.start("i", TOOLS))
    await asyncio.sleep(0.05)
    assert {"type": "voice.connect"} in page.sent
    await voice.handle_page_event({"type": "rtc.state", "state": "failed"})
    with pytest.raises(ConnectionError, match="WebRTC"):
        await asyncio.wait_for(task, 1)
    assert page.sent[-1] == {"type": "voice.disconnect"}
    await voice.aclose()


async def test_page_output_buffer_events_reach_brain_queue():
    voice = OpenAIRealtimeSession("sk-test", "m", "marin", "loja", FakePage())
    await voice.handle_page_event({"type": "output_audio_buffer.started", "response_id": "r"})
    events = voice.events()
    assert await anext(events) == AssistantSpeechStarted()
    await voice.aclose()
