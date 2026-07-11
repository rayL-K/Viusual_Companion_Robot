import asyncio

import httpx

from veyrasoul.integrations.local_vlm import LocalVlmClient, LocalVlmConfig
from veyrasoul.perception import VisualFrame


def test_local_vlm_maps_board_response_to_snapshot() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/analyze"
        return httpx.Response(
            200,
            json={
                "ok": True,
                "backend": "rk3588-qwen3-vl-2b-w8a8",
                "semantic_caption": " 一名戴眼镜的青年正在室内专注看向屏幕。 ",
            },
        )

    async def scenario() -> None:
        client = LocalVlmClient(
            LocalVlmConfig(),
            transport=httpx.MockTransport(handler),
        )
        try:
            snapshot = await client.analyze(
                VisualFrame(7, 1234, b"\xff\xd8image\xff\xd9")
            )
        finally:
            await client.aclose()
        assert snapshot.frame_id == "camera:7"
        assert snapshot.observed_at_ms == 1234
        assert snapshot.semantic_caption == "一名戴眼镜的青年正在室内专注看向屏幕。"

    asyncio.run(scenario())
