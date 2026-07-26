from __future__ import annotations

import json
import logging
from io import StringIO

from veyrasoul.telemetry import (
    JsonLogTraceSink,
    ProviderModel,
    TraceAttributes,
    TracePoint,
    TraceProviders,
    TraceStage,
    TurnTrace,
    TurnTraceDimensions,
)


class CapturingSink:
    def __init__(self) -> None:
        self.snapshots = []

    def emit(self, snapshot) -> None:
        self.snapshots.append(snapshot)


class FailingSink:
    def emit(self, snapshot) -> None:
        raise RuntimeError("telemetry backend unavailable")


def test_turn_trace_snapshot_uses_monotonic_time_and_safe_dimensions() -> None:
    ticks = iter((1_000_000_000, 1_020_000_000, 1_050_000_000, 1_080_000_000))
    sink = CapturingSink()
    trace = TurnTrace(
        dimensions=TurnTraceDimensions(
            session_id="session-1",
            turn_id="turn-1",
            generation=7,
            user_id="user-1",
            anima_id="rabbit",
        ),
        providers=TraceProviders(
            asr=ProviderModel("sherpa-onnx", "zipformer"),
            llm=ProviderModel("deepseek", "deepseek-v4-flash"),
            tts=ProviderModel("sherpa-onnx", "matcha-zh-en"),
        ),
        sink=sink,
        clock=lambda: next(ticks),
    )

    trace.mark(TracePoint.CONTEXT_READY)
    trace.mark(
        TracePoint.LLM_REQUEST,
        stage=TraceStage.LLM,
        attributes=TraceAttributes(text_chars=12),
    )
    trace.complete()

    assert len(sink.snapshots) == 1
    payload = sink.snapshots[0].to_dict()
    assert payload["schema"] == "veyrasoul.turn_trace.v1"
    assert payload["dimensions"] == {
        "sessionId": "session-1",
        "turnId": "turn-1",
        "generation": 7,
        "userId": "user-1",
        "animaId": "rabbit",
    }
    assert payload["providers"]["llm"] == {
        "provider": "deepseek",
        "model": "deepseek-v4-flash",
    }
    assert payload["outcome"] == "completed"
    assert [event["name"] for event in payload["points"]] == [
        "context.ready",
        "llm.request",
        "turn.completed",
    ]
    timestamps = [event["monotonicNs"] for event in payload["points"]]
    assert timestamps == sorted(timestamps)
    assert payload["points"][1]["attributes"] == {"textChars": 12}


def test_turn_trace_closes_once_and_sink_failure_never_breaks_turn() -> None:
    trace = TurnTrace(
        dimensions=TurnTraceDimensions(
            session_id="session-1",
            turn_id="turn-1",
            generation=1,
            user_id="user-1",
            anima_id="rabbit",
        ),
        sink=FailingSink(),
    )

    trace.cancel()
    trace.fail(ValueError)
    trace.complete()

    assert trace.snapshot().outcome == "cancelled"
    assert [point.name for point in trace.snapshot().points] == ["turn.cancelled"]


def test_json_log_sink_emits_one_machine_readable_record_without_body_text() -> None:
    output = StringIO()
    logger = logging.getLogger("test.turn_trace.json")
    logger.handlers = []
    logger.propagate = False
    logger.setLevel(logging.INFO)
    logger.addHandler(logging.StreamHandler(output))
    trace = TurnTrace(
        dimensions=TurnTraceDimensions(
            session_id="session-1",
            turn_id="turn-1",
            generation=3,
            user_id="user-1",
            anima_id="rabbit",
        ),
        sink=JsonLogTraceSink(logger, hmac_key=b"t" * 32),
    )

    trace.mark(TracePoint.FIRST_SPEAKABLE_CLAUSE)
    trace.complete()

    record = json.loads(output.getvalue())
    assert record["event"] == "turn_trace"
    assert record["trace"]["outcome"] == "completed"
    serialized = json.dumps(record, ensure_ascii=False)
    dimensions = record["trace"]["dimensions"]
    assert dimensions["sessionId"].startswith("h_")
    assert dimensions["turnId"].startswith("h_")
    assert dimensions["userId"].startswith("h_")
    assert dimensions["animaId"].startswith("h_")
    assert "session-1" not in serialized
    assert "turn-1" not in serialized
    assert "user-1" not in serialized
    assert "rabbit" not in serialized
    assert "full prompt" not in serialized
    assert "body text" not in serialized
