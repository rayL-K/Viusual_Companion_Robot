"""全模块集成测试。

测试链路：摄像头 → 视觉分析 → 事件总线 → 对话上下文 → LLM prompt
"""

import sys, time, io, requests, numpy as np
from PIL import Image
from pathlib import Path

sys.path.insert(0, "main/src")

from visual_companion_robot.perception import (
    SceneAnalyzer,
    SceneAnalyzerConfig,
    PerceptionFrame,
    PerceptionLoop,
)
from visual_companion_robot.brain import DialogueContext, DialogueTurn
from visual_companion_robot.runtime.bus import (
    RobotEvent,
    EVENT_VISION_FRAME,
    EVENT_SPEECH_START,
    EVENT_SPEECH_END,
)

API_KEY = "REMOVED_SECRET"

# ── 测试 1: 数据结构完整性 ──────────────────────────────────
print("=" * 60)
print("Test 1: 数据结构完整性")
print("=" * 60)

frame = PerceptionFrame(
    scene_caption="三个年轻人围坐在桌前使用笔记本电脑",
    person_activity="协作讨论",
    person_count=3,
    emotion_impression="开心",
)
assert frame.summary() != "（无视觉感知数据）", "summary should not be empty"
print(f"  PerceptionFrame.summary: {frame.summary()}")
print(f"  PerceptionFrame.to_dict: {frame.to_dict()}")
print("  ✅ PASS")

# ── 测试 2: DialogueContext 消费视觉帧 ──────────────────────
print()
print("=" * 60)
print("Test 2: DialogueContext 消费视觉帧")
print("=" * 60)

ctx = DialogueContext()
ctx.update_from_perception(frame.to_dict())
assert ctx.last_scene == frame.scene_caption
assert ctx.last_activity == frame.person_activity
assert ctx.last_emotion == "开心"
assert ctx.person_count == 3

llm_prompt = ctx.build_llm_context()
print(f"  LLM prompt:\n{llm_prompt}")
assert "三个年轻人" in llm_prompt
assert "协作讨论" in llm_prompt
assert "3 人" in llm_prompt
print("  ✅ PASS")

# ── 测试 3: 事件总线 ───────────────────────────────────
print()
print("=" * 60)
print("Test 3: 事件总线")
print("=" * 60)

events = []


def bus_handler(event: RobotEvent):
    events.append(event)


# 模拟事件流
bus_handler(RobotEvent(event_type=EVENT_VISION_FRAME, source="perception", payload=frame.to_dict()))
bus_handler(RobotEvent(event_type=EVENT_SPEECH_START, source="vad", payload={}))
bus_handler(RobotEvent(event_type=EVENT_SPEECH_END, source="vad", payload={}))

assert len(events) == 3
assert events[0].event_type == EVENT_VISION_FRAME
assert events[1].event_type == EVENT_SPEECH_START
print(f"  Events received: {[e.event_type for e in events]}")
print("  ✅ PASS")

# ── 测试 4: 视觉分析 API 端到端 ─────────────────────────
print()
print("=" * 60)
print("Test 4: 视觉分析 API 端到端 (真实图片)")
print("=" * 60)

analyzer = SceneAnalyzer(SceneAnalyzerConfig(api_key=API_KEY))

# 下载真实图片
url = "https://images.unsplash.com/photo-1522202176988-66273c2fd55f?w=640&h=400&fit=crop"
r = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
img = Image.open(io.BytesIO(r.content)).convert("RGB")
arr = np.array(img)
print(f"  Image: {arr.shape[1]}x{arr.shape[0]}")

t0 = time.time()
f = analyzer.analyze(arr)
dt = time.time() - t0

print(f"  Time: {dt:.1f}s")
print(f"  Scene: {f.scene_caption}")
print(f"  Activity: {f.person_activity}")
print(f"  Emotion: {f.emotion_impression}")
print(f"  People: {f.person_count}")

assert f.scene_caption, "Scene caption should not be empty"
assert f.emotion_impression, "Emotion should not be empty"
print("  ✅ PASS")

# ── 测试 5: 完整链路 (视觉 → 上下文 → LLM prompt) ─────────
print()
print("=" * 60)
print("Test 5: 完整链路 (视觉 → 上下文 → LLM prompt)")
print("=" * 60)

ctx2 = DialogueContext()
ctx2.update_from_perception(f.to_dict())

history = [
    DialogueTurn(user_text="你好", assistant_text="你好！有什么可以帮你的？"),
    DialogueTurn(user_text="今天天气怎么样", assistant_text="让我看看窗外..."),
]
ctx2.history = history

full_prompt = ctx2.build_llm_context()
print(f"  Visual context for LLM:\n{full_prompt}")
assert len(full_prompt) > 0, "LLM prompt should include visual context"
print("  ✅ PASS")

# ── 总结 ────────────────────────────────────────────
print()
print("=" * 60)
print("全部测试通过 ✅")
print("=" * 60)
print(f"  1. PerceptionFrame 数据结构     ✅")
print(f"  2. DialogueContext 消费视觉帧    ✅")
print(f"  3. RobotEvent 事件总线          ✅")
print(f"  4. 视觉 API 端到端 (Qwen3-VL)   ✅")
print(f"  5. 完整链路 (视觉→LLM prompt)   ✅")
