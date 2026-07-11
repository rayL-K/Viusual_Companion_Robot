"""访问 ELF2 板内常驻 Qwen3-VL 服务，并转换为统一视觉快照。"""

from __future__ import annotations

import base64
import asyncio
from dataclasses import dataclass
from typing import Any

import httpx

from veyrasoul.domain.perception import VisualSnapshot
from veyrasoul.perception import VisualFrame


@dataclass(frozen=True, slots=True)
class LocalVlmConfig:
    base_url: str = "http://127.0.0.1:8767"
    timeout_seconds: float = 20.0


class LocalVlmClient:
    """拥有可复用 HTTP 连接池；应用退出时必须调用 ``aclose``。"""

    def __init__(
        self,
        config: LocalVlmConfig,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.config = config
        self._client = httpx.AsyncClient(
            base_url=config.base_url.rstrip("/"),
            timeout=httpx.Timeout(config.timeout_seconds),
            transport=transport,
        )
        self._inference_lock = asyncio.Lock()

    async def analyze(self, frame: VisualFrame) -> VisualSnapshot:
        # 板端 RKLLM worker 单实例串行执行；入口锁避免多个会话在 HTTP 层形成隐式长队列。
        async with self._inference_lock:
            response = await self._client.post(
                "/analyze",
                json={"image": base64.b64encode(frame.jpeg).decode("ascii")},
            )
        response.raise_for_status()
        payload = _object_payload(response.json())
        if payload.get("ok") is not True:
            raise RuntimeError(str(payload.get("error") or "板端 VLM 分析失败"))
        caption = " ".join(str(payload.get("semantic_caption") or "").split())[:400]
        if not caption:
            raise RuntimeError("板端 VLM 没有返回语义描述")
        return VisualSnapshot(
            frame_id=f"camera:{frame.sequence}",
            observed_at_ms=frame.observed_at_ms,
            sequence=frame.sequence,
            semantic_caption=caption,
            confidence=1.0,
        )

    async def health(self) -> dict[str, Any]:
        response = await self._client.get("/health")
        response.raise_for_status()
        return _object_payload(response.json())

    async def aclose(self) -> None:
        await self._client.aclose()


def _object_payload(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("板端 VLM 返回值必须是 JSON 对象")
    return value
