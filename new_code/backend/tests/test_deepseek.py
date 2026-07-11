import asyncio
import json

import httpx

from veyrasoul.integrations.deepseek import (
    DeepSeekConfig,
    DeepSeekStreamClient,
    build_messages,
    extract_content_delta,
    parse_sse_line,
)


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
