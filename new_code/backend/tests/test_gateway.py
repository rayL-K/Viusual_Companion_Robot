from __future__ import annotations

import asyncio
import time
from pathlib import Path

from fastapi.testclient import TestClient

from veyrasoul.gateway import AppServices, create_app
from veyrasoul.identity import AnimaId, SessionIdentity, UserId
from veyrasoul.orchestration.ports import (
    AsrUpdate,
    AsrUpdateHandler,
    SpeechSynthesisRequest,
)
from veyrasoul.domain.perception import VisualSnapshot
from veyrasoul.perception import VisualFrame
from veyrasoul.transport import BinaryKind, build_binary_frame, parse_binary_frame


class FakeLlm:
    async def stream_reply(self, messages: list[dict[str, str]]):
        assert messages[-1]["role"] == "user"
        yield "你好。"
        yield "我记得你喜欢乌龙茶。"


class FakeTts:
    def __init__(self) -> None:
        self.requests: list[SpeechSynthesisRequest] = []

    async def synthesize(self, request: SpeechSynthesisRequest) -> tuple[bytes, str]:
        self.requests.append(request)
        return b"RIFF" + request.text.encode("utf-8"), "audio/wav"


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


class FailingVision:
    async def analyze(self, frame: VisualFrame) -> VisualSnapshot:
        raise RuntimeError(f"private path leaked: C:/users/test/{frame.sequence}")


class InterruptibleLlm:
    async def stream_reply(self, messages: list[dict[str, str]]):
        prompt = messages[-1]["content"]
        if "第一问" in prompt:
            await asyncio.sleep(0.2)
            yield "已经过期的回复。"
        else:
            yield "新的回复。"


class ProfileAwareLlm:
    def __init__(self) -> None:
        self.messages: list[dict[str, str]] = []

    async def stream_reply(self, messages: list[dict[str, str]]):
        self.messages = messages
        yield "1234567890。"


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


def resolve_client_asserted_identity(
    raw_user_id: object,
    raw_anima_id: object,
    _session_id: str,
) -> SessionIdentity:
    return SessionIdentity(
        user_id=UserId.parse(raw_user_id),
        anima_id=AnimaId.default() if raw_anima_id is None else AnimaId.parse(raw_anima_id),
        anonymous=False,
        assurance="client_asserted",
    )


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

    from veyrasoul.identity import AnimaId, UserId
    from veyrasoul.memory import MemoryStore

    turns = MemoryStore(
        app.state.registry.layout.state_database(
            UserId.anonymous_for("test-user"), AnimaId.default()
        )
    ).recent_turns("test-user")
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


def test_visual_failure_returns_stable_error_without_internal_details(tmp_path) -> None:
    app = create_app(
        AppServices(
            memory_path=tmp_path / "memory.db",
            llm=FakeLlm(),
            tts=FakeTts(),
            vision=FailingVision(),
            stable_system_prompt="你是草莓兔兔。",
        )
    )
    jpeg = b"\xff\xd8camera-frame\xff\xd9"
    with TestClient(app).websocket_connect("/v2/realtime?session=visual-error") as websocket:
        websocket.receive_json()
        websocket.send_bytes(
            build_binary_frame(BinaryKind.JPEG, 9, int(time.time() * 1000), jpeg)
        )
        error = websocket.receive_json()
    assert error["type"] == "perception.error"
    assert error["payload"] == {
        "code": "perception_failed",
        "message": "视觉语义分析暂时不可用",
    }
    assert "private path" not in str(error)


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

    from veyrasoul.identity import AnimaId, UserId
    from veyrasoul.memory import MemoryStore

    turns = MemoryStore(
        app.state.registry.layout.state_database(
            UserId.anonymous_for("interrupt-user"), AnimaId.default()
        )
    ).recent_turns("interrupt-user")
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
    from veyrasoul.identity import AnimaId, UserId
    from veyrasoul.memory import MemoryStore

    turns = MemoryStore(
        app.state.registry.layout.state_database(
            UserId.anonymous_for("voice-user"), AnimaId.default()
        )
    ).recent_turns("voice-user")
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


def test_settings_events_persist_profile_and_constrain_next_turn(tmp_path) -> None:
    llm = ProfileAwareLlm()
    tts = FakeTts()
    app = create_app(
        AppServices(
            memory_path=tmp_path / "legacy.db",
            data_root=tmp_path / "accounts",
            llm=llm,
            tts=tts,
            stable_system_prompt="默认 Anima 人设",
            identity_resolver=resolve_client_asserted_identity,
        )
    )
    url = "/v2/realtime?session=profile-session&user=alice&anima=rabbit"
    with TestClient(app).websocket_connect(url) as websocket:
        ready = websocket.receive_json()
        assert ready["payload"]["protocol"] == 2
        assert ready["payload"]["userId"] == "alice"
        assert ready["payload"]["animaId"] == "rabbit"
        assert ready["payload"]["anonymous"] is False
        assert ready["payload"]["identityAssurance"] == "client_asserted"
        websocket.send_json({"v": 2, "type": "settings.get", "payload": {}})
        initial = websocket.receive_json()
        assert initial["type"] == "settings.current"
        assert initial["payload"]["personaMarkdown"] == "默认 Anima 人设"

        websocket.send_json(
            {
                "v": 2,
                "type": "settings.update",
                "payload": {
                    "expectedRevision": 1,
                    "personaMarkdown": "你是只对 Alice 温柔的月兔。",
                    "maxReplyChars": 8,
                    "replyDelayMs": 20,
                    "voiceId": "sid:3",
                },
            }
        )
        changed = websocket.receive_json()
        assert changed["type"] == "settings.current"
        assert changed["payload"]["updated"] is True
        assert changed["payload"]["revision"] == 2

        started = time.monotonic()
        websocket.send_json(
            {"v": 2, "type": "turn.user_text", "payload": {"text": "介绍一下自己"}}
        )
        phase = websocket.receive_json()
        assert phase["type"] == "reply.phase"
        assert_avatar_intent(websocket.receive_json(), "thinking", generation=phase["generation"])
        assert_avatar_intent(websocket.receive_json(), "speaking", generation=phase["generation"])
        parse_binary_frame(websocket.receive()["bytes"])
        segment = websocket.receive_json()
        assert segment["payload"]["text"] == "12345678"
        assert time.monotonic() - started >= 0.015
        completed = websocket.receive_json()
        assert completed["payload"]["text"] == "12345678"
        assert_avatar_intent(websocket.receive_json(), "idle", generation=phase["generation"])

    assert tts.requests[-1] == SpeechSynthesisRequest(text="12345678", voice_id="sid:3")
    assert any("只对 Alice 温柔" in message["content"] for message in llm.messages)
    assert any("最多 8 个字符" in message["content"] for message in llm.messages)

    with TestClient(app).websocket_connect(url) as websocket:
        websocket.receive_json()
        websocket.send_json({"v": 2, "type": "settings.get", "payload": {}})
        restored = websocket.receive_json()
        assert restored["payload"]["voiceId"] == "sid:3"
        assert restored["payload"]["revision"] == 2


def test_invalid_identity_and_settings_return_actionable_protocol_errors(tmp_path) -> None:
    client = TestClient(make_app(tmp_path / "memory.db"))
    with client.websocket_connect("/v2/realtime?session=../../shared") as websocket:
        error = websocket.receive_json()
        assert error["payload"]["code"] == "invalid_session"

    with client.websocket_connect("/v2/realtime?session=x&user=../../admin") as websocket:
        error = websocket.receive_json()
        assert error["type"] == "error"
        assert error["payload"]["code"] == "invalid_identity"

    with client.websocket_connect("/v2/realtime?session=x&user=alice") as websocket:
        error = websocket.receive_json()
        assert error["payload"]["code"] == "invalid_identity"
        assert "IdentityResolver" in error["payload"]["message"]

    with client.websocket_connect("/v2/realtime?session=x") as websocket:
        websocket.receive_json()
        websocket.send_json(
            {
                "v": 2,
                "type": "settings.update",
                "payload": {"expectedRevision": 1, "maxReplyChars": 7},
            }
        )
        error = websocket.receive_json()
        assert error["type"] == "error"
        assert error["payload"]["code"] == "invalid_settings"


def test_user_databases_and_conversation_history_are_isolated(tmp_path) -> None:
    memory_path = tmp_path / "legacy.db"
    app = create_app(
        AppServices(
            memory_path=memory_path,
            llm=FakeLlm(),
            tts=FakeTts(),
            stable_system_prompt="你是草莓兔兔，回复自然、温暖且简洁。",
            identity_resolver=resolve_client_asserted_identity,
        )
    )
    client = TestClient(app)
    for user in ("alice", "bob"):
        with client.websocket_connect(
            f"/v2/realtime?session=shared-session&user={user}"
        ) as websocket:
            websocket.receive_json()
            websocket.send_json(
                {
                    "v": 2,
                    "type": "turn.user_text",
                    "payload": {"text": f"来自 {user} 的私有对话"},
                }
            )
            phase = websocket.receive_json()
            assert_avatar_intent(websocket.receive_json(), "thinking", generation=phase["generation"])
            for _ in range(2):
                assert_avatar_intent(
                    websocket.receive_json(), "speaking", generation=phase["generation"]
                )
                parse_binary_frame(websocket.receive()["bytes"])
                websocket.receive_json()
            websocket.receive_json()
            assert_avatar_intent(websocket.receive_json(), "idle", generation=phase["generation"])

    layout = app.state.registry.layout
    from veyrasoul.identity import AnimaId, UserId
    from veyrasoul.memory import MemoryStore

    alice_store = MemoryStore(layout.state_database(UserId.parse("alice"), AnimaId.default()))
    bob_store = MemoryStore(layout.state_database(UserId.parse("bob"), AnimaId.default()))
    assert alice_store.db_path != bob_store.db_path
    assert alice_store.recent_turns("shared-session")[0]["user_text"] == (
        "来自 alice 的私有对话"
    )
    assert bob_store.recent_turns("shared-session")[0]["user_text"] == (
        "来自 bob 的私有对话"
    )


def test_anonymous_default_session_keeps_legacy_memory_database(tmp_path) -> None:
    from veyrasoul.memory import MemoryStore

    memory_path = tmp_path / "legacy.db"
    MemoryStore(memory_path).add_turn("old-session", "old-turn", "以前的问题", "以前的回答")
    llm = CapturingLlm()
    app = create_app(
        AppServices(
            memory_path=memory_path,
            llm=llm,
            tts=FakeTts(),
            stable_system_prompt="默认人设",
        )
    )
    with TestClient(app).websocket_connect("/v2/realtime?session=old-session") as websocket:
        ready = websocket.receive_json()
        assert ready["payload"]["anonymous"] is True
        assert ready["payload"]["identityAssurance"] == "anonymous_session_hint"
        websocket.send_json(
            {"v": 2, "type": "turn.user_text", "payload": {"text": "现在呢？"}}
        )
        phase = websocket.receive_json()
        assert_avatar_intent(websocket.receive_json(), "thinking", generation=phase["generation"])
        assert_avatar_intent(websocket.receive_json(), "speaking", generation=phase["generation"])
        parse_binary_frame(websocket.receive()["bytes"])
        websocket.receive_json()
        websocket.receive_json()
        assert_avatar_intent(websocket.receive_json(), "idle", generation=phase["generation"])

    assert any(message["content"] == "以前的问题" for message in llm.messages)
    assert app.state.registry.memory.db_path == memory_path


def test_distinct_anonymous_sessions_use_distinct_owners_and_databases(tmp_path) -> None:
    app = make_app(tmp_path / "legacy.db")
    client = TestClient(app)
    owners: list[str] = []
    for session in ("browser-a", "browser-b"):
        with client.websocket_connect(f"/v2/realtime?session={session}") as websocket:
            ready = websocket.receive_json()
            owners.append(ready["payload"]["userId"])
            websocket.send_json({"v": 2, "type": "settings.get", "payload": {}})
            assert websocket.receive_json()["type"] == "settings.current"

    assert owners[0] != owners[1]
    from veyrasoul.identity import AnimaId, UserId

    layout = app.state.registry.layout
    first = layout.state_database(UserId.parse(owners[0]), AnimaId.default())
    second = layout.state_database(UserId.parse(owners[1]), AnimaId.default())
    assert first != second
    assert first.is_file() and second.is_file()
