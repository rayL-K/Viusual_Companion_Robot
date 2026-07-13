"""仅供本机浏览器 E2E 使用的确定性模型桩；不会连接或替换开发板 V1。"""

from __future__ import annotations

import asyncio
import io
import math
import os
import struct
import tempfile
import wave
from collections.abc import AsyncIterator
from pathlib import Path

import uvicorn

from veyrasoul.domain.perception import VisualSnapshot
from veyrasoul.orchestration.ports import SpeechSynthesisRequest
from veyrasoul.perception import VisualFrame

from .app import AppServices, create_app


_DEMO_TEMP = tempfile.TemporaryDirectory(prefix="veyrasoul-e2e-")


class DemoLlm:
    async def stream_reply(self, messages: list[dict[str, str]]) -> AsyncIterator[str]:
        prompt = messages[-1]["content"] if messages else ""
        if "慢回复" in prompt:
            await asyncio.sleep(1.2)
            yield "这条过期回复不应该出现在界面里。"
            return
        if "立即打断" in prompt:
            yield "新的回复已经接管。"
            yield "旧一代内容和声音都已失效。"
            return
        yield "我已经听见你啦。"
        yield "现在的画面和声音都在陪伴链路里顺畅流动。"


class DemoTts:
    async def synthesize(self, request: SpeechSynthesisRequest) -> tuple[bytes, str]:
        frequency = 420 + min(len(request.text), 40) * 3
        return _tone_wav(frequency, 0.32), "audio/wav"


class DemoVision:
    async def analyze(self, frame: VisualFrame) -> VisualSnapshot:
        return VisualSnapshot(
            frame_id=f"demo:{frame.sequence}",
            observed_at_ms=frame.observed_at_ms,
            sequence=frame.sequence,
            semantic_caption="一位正在参与视频通话的人出现在室内画面中，状态专注而放松。",
            people=("视频通话参与者",),
            face_emotions={"happy": 0.72, "neutral": 0.28},
            confidence=0.94,
        )


def build_demo_app():
    v2_root = Path(__file__).resolve().parents[4]
    web_dist = Path(os.environ.get("VEYRASOUL_WEB_DIST", v2_root / "web" / "dist"))
    if not (web_dist / "index.html").is_file():
        raise RuntimeError("请先在 new_code/web 执行 npm run build")
    memory_path = Path(_DEMO_TEMP.name) / "memory.db"
    return create_app(
        AppServices(
            memory_path=memory_path,
            llm=DemoLlm(),
            tts=DemoTts(),
            vision=DemoVision(),
            vision_refresh_seconds=0.1,
            stable_system_prompt="你是草莓兔兔的本机 E2E 桩。",
            web_dist=web_dist,
        )
    )


def main() -> None:
    uvicorn.run(
        build_demo_app(),
        host="127.0.0.1",
        port=int(os.environ.get("VEYRASOUL_E2E_PORT", "8875")),
        log_level="warning",
    )


def _tone_wav(frequency: float, duration_seconds: float) -> bytes:
    sample_rate = 16_000
    sample_count = int(sample_rate * duration_seconds)
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        frames = bytearray()
        for index in range(sample_count):
            envelope = min(1.0, index / 240, (sample_count - index) / 240)
            sample = int(math.sin(2 * math.pi * frequency * index / sample_rate) * 8_500 * envelope)
            frames.extend(struct.pack("<h", sample))
        wav.writeframes(frames)
    return output.getvalue()


if __name__ == "__main__":
    main()
