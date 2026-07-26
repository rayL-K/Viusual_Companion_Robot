import asyncio
import json

import httpx
import pytest

from veyrasoul.integrations.deepseek import (
    DeepSeekConfig,
    DeepSeekStreamClient,
    build_messages,
    extract_content_delta,
    parse_sse_line,
)
from veyrasoul.orchestration.prompt import PromptBudget, message_char_count


def test_config_repr_never_exposes_api_key() -> None:
    config = DeepSeekConfig(api_key="deepseek-secret-value")

    assert "deepseek-secret-value" not in repr(config)


def test_sse_delta_parser_ignores_done_and_reads_content() -> None:
    event = parse_sse_line('data: {"choices":[{"delta":{"content":"你好"}}]}')
    assert event is not None
    assert extract_content_delta(event) == "你好"
    assert parse_sse_line("data: [DONE]") is None


def test_dynamic_context_is_after_stable_history() -> None:
    messages = build_messages(
        stable_system_prompt="你是草莓兔兔。",
        history=[{"role": "user", "content": "上一句"}, {"role": "assistant", "content": "上一答"}],
        user_text="你看见什么？",
        visual_context="青年男性戴眼镜，坐在书桌前",
        memory_context=["用户喜欢乌龙茶"],
    )
    assert messages[0] == {"role": "system", "content": "你是草莓兔兔。"}
    assert messages[-1]["role"] == "user"
    assert "青年男性" in messages[-1]["content"]
    assert "乌龙茶" in messages[-1]["content"]


def test_prompt_budget_is_hard_bounded_and_keeps_newest_context() -> None:
    history = [
        {"role": "user", "content": f"第{index}轮问题" + "问" * 70}
        if index % 2 == 0
        else {"role": "assistant", "content": f"第{index}轮回答" + "答" * 70}
        for index in range(20)
    ]
    budget = PromptBudget(
        total_chars=1_300,
        stable_system_chars=100,
        persona_chars=180,
        response_constraint_chars=80,
        history_chars=420,
        history_message_chars=100,
        visual_chars=100,
        memory_chars=100,
        affect_chars=40,
        user_chars=100,
    )

    messages = build_messages(
        stable_system_prompt="稳定规则" * 80,
        persona_prompt="角色人设" * 100,
        response_constraint="自然简短" * 50,
        history=history,
        user_text="现在的问题" * 50,
        visual_context="眼前是书桌和一位戴眼镜的青年" * 30,
        memory_context=["用户喜欢乌龙茶" * 30, "用户在准备演示" * 30],
        affect_context="valence=0.8, trust=0.9" * 20,
        budget=budget,
    )

    assert message_char_count(messages) <= budget.total_chars
    assert messages[0]["role"] == "system"
    assert messages[-1]["role"] == "user"
    assert any("第19轮回答" in item["content"] for item in messages)
    assert all("第0轮问题" not in item["content"] for item in messages)
    assert "<current_context>" in messages[-1]["content"]


def test_prompt_budget_rejects_empty_required_prompts() -> None:
    with pytest.raises(ValueError, match="stable_system_prompt"):
        build_messages(stable_system_prompt=" ", history=[], user_text="你好")
    with pytest.raises(ValueError, match="user_text"):
        build_messages(stable_system_prompt="规则", history=[], user_text=" ")


def test_prompt_budget_stays_bounded_without_optional_persona() -> None:
    budget = PromptBudget(
        total_chars=48,
        stable_system_chars=80,
        persona_chars=10,
        response_constraint_chars=10,
        history_chars=10,
        history_message_chars=10,
        visual_chars=80,
        memory_chars=80,
        affect_chars=10,
        user_chars=80,
    )
    messages = build_messages(
        stable_system_prompt="稳定系统规则" * 20,
        history=[],
        user_text="请回答我现在的问题" * 20,
        visual_context="一位戴眼镜的青年坐在书桌前" * 20,
        memory_context=["用户喜欢乌龙茶" * 20],
        budget=budget,
    )

    assert message_char_count(messages) <= budget.total_chars
    assert messages[0]["role"] == "system"
    assert messages[-1]["role"] == "user"


def test_stream_client_disables_thinking_and_reuses_owned_client() -> None:
    requests: list[dict[str, object]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            headers={"Content-Type": "text/event-stream"},
            content='data: {"choices":[{"delta":{"content":"你好"}}]}\n\ndata: [DONE]\n\n',
        )

    async def scenario() -> None:
        client = DeepSeekStreamClient(
            DeepSeekConfig(api_key="test", max_tokens=96),
            transport=httpx.MockTransport(handler),
        )
        try:
            first = [chunk async for chunk in client.stream_reply([{"role": "user", "content": "一"}])]
            second = [chunk async for chunk in client.stream_reply([{"role": "user", "content": "二"}])]
        finally:
            await client.aclose()
        assert first == second == ["你好"]

    asyncio.run(scenario())
    assert len(requests) == 2
    assert requests[0]["thinking"] == {"type": "disabled"}
    assert requests[0]["max_tokens"] == 96
