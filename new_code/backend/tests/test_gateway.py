from __future__ import annotations

import asyncio
import time
from pathlib import Path

from fastapi.testclient import TestClient

from veyrasoul.gateway import AppServices, create_app
from veyrasoul.orchestration.ports import AsrUpdate, AsrUpdateHandler
from veyrasoul.domain.perception import VisualSnapshot
from veyrasoul.perception import VisualFrame
from veyrasoul.transport import BinaryKind, build_binary_frame, parse_binary_frame


class FakeLlm:
    async def stream_reply(self, messages: list[dict[str, str]]):
        assert messages[-1]["role"] == "user"
        yield "你好。"
        yield "我记得你喜欢乌龙茶。"


class FakeTts:
    async def synthesize(self, text: str) -> tuple[bytes, str]:
        return b"RIFF" + text.encode("utf-8"), "audio/wav"


class CapturingLlm(FakeLlm):
    def __init__(self) -> None:
        self.messages: list[dict[str, str]] = []

    async def stream_reply(self, messages: list[dict[str, str]]):
        self.messages = messages
        yield "我看见你正戴着眼镜专注地看向屏幕。"


class FakeVision:
    async def analyze(self, frame: VisualFrame) -> VisualSnapshot:
        return VisualSnapshot(
            frame_id=f"camera:{frame.sequence}",
            observed_at_ms=frame.observed_at_ms,
            sequence=frame.sequence,
            semantic_caption="一名戴眼镜的青年在室内专注地看向屏幕。",
            confidence=0.96,
        )


class InterruptibleLlm:
    async def stream_reply(self, messages: list[dict[str, str]]):
        prompt = messages[-1]["content"]
        if "第一问" in prompt:
            await asyncio.sleep(0.2)
            yield "已经过期的回复。"
        else:
            yield "新的回复。"


class FakeAsrSession:
    def __init__(self, transcripts: list[str]) -> None:
        self.transcripts = iter(transcripts)
        self.handler: AsrUpdateHandler | None = None
        self.queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        self.task: asyncio.Task[None] | None = None

    async def start(self, handler: AsrUpdateHandler) -> None:
        self.handler = handler
        self.task = asyncio.create_task(self._run())

    def submit_pcm16(self, pcm16: bytes) -> None:
        if self.task is None or self.task.done():
            raise RuntimeError("fake ASR session is not running")
        self.queue.put_nowait(pcm16)

    async def close(self) -> None:
        task = self.task
        if task is None:
            return
        self.task = None
        await self.queue.put(None)
        await task

    async def _run(self) -> None:
        while True:
            pcm16 = await self.queue.get()
            if pcm16 is None:
                return
            text = next(self.transcripts)
            assert self.handler is not None
            await self.handler(AsrUpdate(text=text[:-1], final=False))
            await self.handler(AsrUpdate(text=text, final=True))


class FakeAsrFactory:
    def __init__(self, transcripts: list[str]) -> None:
        self.transcripts = transcripts
        self.sessions: list[FakeAsrSession] = []

    def create_session(self) -> FakeAsrSession:
        session = FakeAsrSession(self.transcripts.copy())
        self.sessions.append(session)
        return session


def make_app(memory_path: Path):
    return create_app(
        AppServices(
            memory_path=memory_path,
            llm=FakeLlm(),
            tts=FakeTts(),
            stable_system_prompt="你是草莓兔兔，回复自然、温暖且简洁。",
        )
    )


def assert_avatar_intent(
    event: dict[str, object],
    phase: str,
    *,
    turn_id: str | None = None,
    generation: int | None = None,
) -> None:
    assert event["type"] == "avatar.intent"
    if turn_id is not None:
        assert event["turnId"] == turn_id
    if generation is not None:
        assert event["generation"] == generation
    payload = event["payload"]
    assert isinstance(payload, dict)
    assert payload["phase"] == phase
    assert {
        "expression",
        "motion",
        "gazeStrength",
        "bodyTension",
        "smile",
        "eyeOpen",
        "speechRate",
        "speechPitch",
        "affect",
    } <= payload.keys()
    assert set(payload["affect"]) == {
        "valence",
        "arousal",
        "dominance",
        "affinity",
        "trust",
    }


def test_health_endpoint(tmp_path) -> None:
    client = TestClient(make_app(tmp_path / "memory.db"))
    response = client.get("/v2/health")
    assert response.status_code == 200
    assert response.json()["protocol"] == 2


def test_gateway_can_serve_built_web_from_same_origin(tmp_path) -> None:
    web_dist = tmp_path / "dist"
    web_dist.mkdir()
    (web_dist / "index.html").write_text("<h1>VeyraSoul</h1>", encoding="utf-8")
    app = create_app(
        AppServices(
            memory_path=tmp_path / "memory.db",
            llm=FakeLlm(),
            tts=FakeTts(),
            stable_system_prompt="你是草莓兔兔。",
            web_dist=web_dist,
        )
    )
    response = TestClient(app).get("/")
    assert response.status_code == 200
    assert "VeyraSoul" in response.text


def test_realtime_turn_sends_audio_before_matching_text(tmp_path) -> None:
    app = make_app(tmp_path / "memory.db")
    client = TestClient(app)
    with client.websocket_connect("/v2/realtime?session=test-user") as websocket:
        ready = websocket.receive_json()
        assert ready["type"] == "session.ready"
        websocket.send_json({"v": 2, "type": "turn.user_text", "payload": {"text": "你记得什么？"}})
        phase = websocket.receive_json()
        assert phase["type"] == "reply.phase"
        assert_avatar_intent(websocket.receive_json(), "thinking", generation=phase["generation"])
        first_speaking = websocket.receive_json()
        assert_avatar_intent(first_speaking, "speaking", generation=phase["generation"])
        assert first_speaking["payload"]["segmentIndex"] == 0
        audio_message = websocket.receive()
        frame = parse_binary_frame(audio_message["bytes"])
        assert frame.kind is BinaryKind.AUDIO
        assert frame.payload.startswith(b"RIFF")
        segment = websocket.receive_json()
        assert segment["type"] == "reply.segment.ready"
        assert segment["payload"]["audioSeq"] == frame.sequence
        assert segment["payload"]["text"] == "你好。"

        second_speaking = websocket.receive_json()
        assert_avatar_intent(second_speaking, "speaking", generation=phase["generation"])
        assert second_speaking["payload"]["segmentIndex"] == 1
        second_audio = parse_binary_frame(websocket.receive()["bytes"])
        second_segment = websocket.receive_json()
        assert second_segment["payload"]["audioSeq"] == second_audio.sequence
        assert "乌龙茶" in second_segment["payload"]["text"]
        completed = websocket.receive_json()
        assert completed["type"] == "reply.completed"
        assert completed["payload"]["segments"] == 2
        assert_avatar_intent(websocket.receive_json(), "idle", generation=phase["generation"])

    turns = app.state.registry.memory.recent_turns("test-user")
    assert turns[-1]["assistant_text"] == "你好。我记得你喜欢乌龙茶。"


def test_binary_media_header_is_validated(tmp_path) -> None:
    client = TestClient(make_app(tmp_path / "memory.db"))
    with client.websocket_connect("/v2/realtime?session=media-user") as websocket:
        websocket.receive_json()
        websocket.send_bytes(
            build_binary_frame(BinaryKind.PCM16, 7, 1000, b"\x00\x00" * 320, flags=1)
        )
        accepted = websocket.receive_json()
        assert accepted["type"] == "media.accepted"
        assert accepted["payload"] == {"kind": "pcm16", "sequence": 7, "bytes": 640}


def test_visual_semantics_are_published_and_injected_into_every_turn(tmp_path) -> None:
    llm = CapturingLlm()
    app = create_app(
        AppServices(
            memory_path=tmp_path / "memory.db",
            llm=llm,
            tts=FakeTts(),
            vision=FakeVision(),
            stable_system_prompt="你是草莓兔兔。",
        )
    )
    jpeg = b"\xff\xd8camera-frame\xff\xd9"
    observed_at_ms = int(time.time() * 1000)
    with TestClient(app).websocket_connect("/v2/realtime?session=visual-user") as websocket:
        websocket.receive_json()
        websocket.send_bytes(build_binary_frame(BinaryKind.JPEG, 9, observed_at_ms, jpeg))
        perception = websocket.receive_json()
        assert perception["type"] == "perception.snapshot"
        assert "戴眼镜" in perception["payload"]["summary"]

        websocket.send_json({"v": 2, "type": "turn.user_text", "payload": {"text": "今天聊什么？"}})
        phase = websocket.receive_json()
        assert phase["type"] == "reply.phase"
        assert_avatar_intent(websocket.receive_json(), "thinking", generation=phase["generation"])
        assert_avatar_intent(websocket.receive_json(), "speaking", generation=phase["generation"])
        parse_binary_frame(websocket.receive()["bytes"])
        assert websocket.receive_json()["type"] == "reply.segment.ready"
        assert websocket.receive_json()["type"] == "reply.completed"
        assert_avatar_intent(websocket.receive_json(), "idle", generation=phase["generation"])

    assert "视觉：一名戴眼镜的青年" in llm.messages[-1]["content"]


def test_new_turn_cancels_slow_previous_generation(tmp_path) -> None:
    app = create_app(
        AppServices(
            memory_path=tmp_path / "memory.db",
            llm=InterruptibleLlm(),
            tts=FakeTts(),
            stable_system_prompt="你是草莓兔兔。",
        )
    )
    with TestClient(app).websocket_connect("/v2/realtime?session=interrupt-user") as websocket:
        websocket.receive_json()
        websocket.send_json(
            {"v": 2, "type": "turn.user_text", "payload": {"text": "第一问", "turnId": "first"}}
        )
        first_phase = websocket.receive_json()
        assert_avatar_intent(
            websocket.receive_json(), "thinking", turn_id="first", generation=first_phase["generation"]
        )
        websocket.send_json(
            {"v": 2, "type": "turn.user_text", "payload": {"text": "第二问", "turnId": "second"}}
        )
        second_phase = websocket.receive_json()
        assert second_phase["generation"] > first_phase["generation"]
        assert_avatar_intent(
            websocket.receive_json(), "thinking", turn_id="second", generation=second_phase["generation"]
        )
        assert_avatar_intent(
            websocket.receive_json(), "speaking", turn_id="second", generation=second_phase["generation"]
        )
        parse_binary_frame(websocket.receive()["bytes"])
        segment = websocket.receive_json()
        assert segment["payload"]["text"] == "新的回复。"
        assert websocket.receive_json()["type"] == "reply.completed"
        assert_avatar_intent(
            websocket.receive_json(), "idle", turn_id="second", generation=second_phase["generation"]
        )

    turns = app.state.registry.memory.recent_turns("interrupt-user")
    assert len(turns) == 1
    assert turns[0]["user_text"] == "第二问"


def test_pcm_asr_updates_start_turn_and_cancel_previous_generation(tmp_path) -> None:
    asr = FakeAsrFactory(["第一问", "第二问"])
    app = create_app(
        AppServices(
            memory_path=tmp_path / "memory.db",
            llm=InterruptibleLlm(),
            tts=FakeTts(),
            stable_system_prompt="你是草莓兔兔。",
            asr=asr,
        )
    )
    pcm_frame = build_binary_frame(BinaryKind.PCM16, 1, 1000, b"\x00\x00" * 320)
    with TestClient(app).websocket_connect("/v2/realtime?session=voice-user") as websocket:
        websocket.receive_json()
        websocket.send_bytes(pcm_frame)
        assert websocket.receive_json()["type"] == "asr.partial"
        listening = websocket.receive_json()
        assert_avatar_intent(listening, "listening")
        assert websocket.receive_json()["type"] == "asr.final"
        first_phase = websocket.receive_json()
        assert first_phase["type"] == "reply.phase"
        assert first_phase["turnId"] == listening["turnId"]
        assert first_phase["generation"] > listening["generation"]
        assert_avatar_intent(websocket.receive_json(), "thinking", generation=first_phase["generation"])

        websocket.send_bytes(pcm_frame)
        assert websocket.receive_json()["type"] == "asr.partial"
        second_listening = websocket.receive_json()
        assert_avatar_intent(second_listening, "listening")
        assert second_listening["generation"] > first_phase["generation"]
        assert websocket.receive_json()["type"] == "asr.final"
        second_phase = websocket.receive_json()
        assert second_phase["type"] == "reply.phase"
        assert second_phase["generation"] > first_phase["generation"]
        assert second_phase["turnId"] == second_listening["turnId"]
        assert_avatar_intent(websocket.receive_json(), "thinking", generation=second_phase["generation"])
        assert_avatar_intent(websocket.receive_json(), "speaking", generation=second_phase["generation"])
        audio = parse_binary_frame(websocket.receive()["bytes"])
        assert audio.kind is BinaryKind.AUDIO
        segment = websocket.receive_json()
        assert segment["type"] == "reply.segment.ready"
        assert segment["payload"]["audioSeq"] == audio.sequence
        assert segment["payload"]["text"] == "新的回复。"
        assert websocket.receive_json()["type"] == "reply.completed"
        assert_avatar_intent(websocket.receive_json(), "idle", generation=second_phase["generation"])

    assert len(asr.sessions) == 1
    turns = app.state.registry.memory.recent_turns("voice-user")
    assert len(turns) == 1
    assert turns[0]["user_text"] == "第二问"


def test_explicit_cancel_emits_generation_bound_idle_intent(tmp_path) -> None:
    app = create_app(
        AppServices(
            memory_path=tmp_path / "memory.db",
            llm=InterruptibleLlm(),
            tts=FakeTts(),
            stable_system_prompt="你是草莓兔兔。",
        )
    )
    with TestClient(app).websocket_connect("/v2/realtime?session=cancel-user") as websocket:
        websocket.receive_json()
        websocket.send_json(
            {"v": 2, "type": "turn.user_text", "payload": {"text": "第一问", "turnId": "cancel-me"}}
        )
        phase = websocket.receive_json()
        assert_avatar_intent(websocket.receive_json(), "thinking", generation=phase["generation"])
        websocket.send_json({"v": 2, "type": "turn.cancel", "payload": {}})
        cancelled = websocket.receive_json()
        assert cancelled["type"] == "turn.cancelled"
        assert cancelled["turnId"] == "cancel-me"
        assert cancelled["generation"] > phase["generation"]
        assert_avatar_intent(
            websocket.receive_json(),
            "idle",
            turn_id="cancel-me",
            generation=cancelled["generation"],
        )
