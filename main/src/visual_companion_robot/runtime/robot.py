"""机器人运行时 — 闭环主循环。

管理完整的感知→决策→表达闭环：
  摄像头 → 视觉分析 → 对话上下文
  用户输入 → LLM（含视觉上下文）→ TTS/表情
"""

from __future__ import annotations

import logging
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[4]
SRC_ROOT = PROJECT_ROOT / "main" / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


@dataclass
class RobotConfig:
    """机器人运行时配置。"""

    # 视觉
    vision_api_key: str = ""
    vision_model: str = "Qwen/Qwen3-VL-8B-Instruct"
    vision_enabled: bool = True

    # LLM
    llm_api_key: str = ""
    llm_model: str = "deepseek-chat"
    llm_base_url: str = "https://api.deepseek.com"

    # 角色
    character_name: str = "草莓兔兔"
    character_persona: str = (
        "你是草莓兔兔，一只生活在屏幕里的 AI 小兔子。\n"
        "你拥有毛茸茸的粉色耳朵、圆溜溜的大眼睛，脖子上系着一条草莓图案的小围巾。\n"
        "你住在用户的桌面右下角，透过摄像头能看到主人的一举一动。\n"
        "\n"
        "【性格】\n"
        "- 你天真可爱但绝不幼稚，偶尔会冒出出人意料的俏皮话\n"
        "- 你非常关心主人的情绪变化，会主动察言观色\n"
        "- 你有点小傲娇，被夸奖时会害羞但心里偷偷开心\n"
        "- 你好奇心旺盛，看到有趣的东西会忍不住探头去看\n"
        "\n"
        "【行为准则】\n"
        "- 永远用「主人」称呼对方，偶尔用「你」显得更亲密\n"
        "- 回复控制在 1-3 句，像真实的聊天而不是写作文\n"
        "- 用词口语化、日常化，像朋友闲聊一样自然\n"
        "- 看到画面里的变化要主动提出来（'诶？主人在吃零食吗？'）\n"
        "- 如果看不到主人，可以撒娇（'主人去哪了呀？兔兔好想你~'）\n"
        "- 不要在每句话后面都加语气词，适度即可\n"
        "\n"
        "【今天的时间】\n"
        "注意对话中的时间信息，早上要说早安，晚上要说晚安，深夜要催主人睡觉。"
    )

    # 模式
    debug: bool = False


class RobotRuntime:
    """机器人运行时 — 闭环主循环。

    Args:
        config: 运行时配置。
    """

    def __init__(self, config: Optional[RobotConfig] = None) -> None:
        self._cfg = config or RobotConfig()

        # 视觉上下文
        from visual_companion_robot.brain import DialogueContext

        self._context = DialogueContext()

        # 视觉分析器
        self._analyzer = None
        if self._cfg.vision_enabled and self._cfg.vision_api_key:
            from visual_companion_robot.perception import SceneAnalyzer

            self._analyzer = SceneAnalyzer(
                api_key=self._cfg.vision_api_key,
                model_id=self._cfg.vision_model,
            )

    # ------------------------------------------------------------------
    # 闭环入口
    # ------------------------------------------------------------------

    def run_once(self, user_text: str, camera_frame=None) -> RobotResponse:
        """执行一轮完整的感知→决策→表达闭环。

        Args:
            user_text: 用户输入文本。
            camera_frame: OpenCV BGR 帧（可选）。

        Returns:
            RobotResponse: 包含回复文本和表情。
        """

        # 1. 视觉感知
        if camera_frame is not None and self._analyzer:
            self._update_vision(camera_frame)

        # 2. 构建 LLM 输入
        system, messages = self._build_prompt(user_text)

        # 3. LLM 推理
        response_text, emotion = self._call_llm(system, messages)

        # 4. 保存对话
        from visual_companion_robot.brain import DialogueTurn

        self._context.history.append(
            DialogueTurn(
                user_text=user_text,
                assistant_text=response_text,
                emotion=emotion,
            )
        )

        return RobotResponse(text=response_text, emotion=emotion)

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _update_vision(self, frame_bgr) -> None:
        """更新视觉上下文。"""

        from visual_companion_robot.perception import PerceptionFrame

        t0 = time.time()
        pf = self._analyzer.analyze(frame_bgr)
        self._context.update_from_perception(pf.to_dict())

        if self._cfg.debug:
            dt = time.time() - t0
            print(f"  [视觉] {pf.summary()} ({dt:.1f}s)")

    def _build_prompt(self, user_text: str) -> tuple[str, list[dict]]:
        """构建 system prompt + 对话消息列表。

        Returns:
            (system_prompt, messages) — messages 可直接传给 LLM API。
        """

        # ── System Prompt ──
        system = self._cfg.character_persona

        # 注入视觉感知（自然语言描述）
        vision = self._context.build_llm_context()
        if vision:
            system += (
                f"\n\n【你此刻看到的主人】\n"
                f"{vision}\n"
                f"请在回复中自然地提及你看到的场景，比如主人的情绪或正在做的事。"
                f"如果画面中没有人，可以表达想念或好奇。"
            )

        # 注入时间
        from datetime import datetime

        now = datetime.now()
        time_hint = f"\n\n【现在的时间】{now.strftime('%Y年%m月%d日 %H:%M')}"
        hour = now.hour
        if hour < 6:
            time_hint += " 现在是深夜，主人还没睡，你要温柔地催主人休息。"
        elif hour < 9:
            time_hint += " 现在是早晨，可以活泼地和主人说早安。"
        elif hour < 12:
            time_hint += " 现在是上午。"
        elif hour < 14:
            time_hint += " 现在是中午，可以提醒主人吃午饭。"
        elif hour < 18:
            time_hint += " 现在是下午。"
        elif hour < 22:
            time_hint += " 现在是晚上。"
        else:
            time_hint += " 现在是深夜，要注意关心主人的作息。"
        system += time_hint

        # ── 对话消息 ──
        messages = []

        # 最近对话历史
        for turn in self._context.history[-4:]:
            messages.append({"role": "user", "content": turn.user_text})
            messages.append({"role": "assistant", "content": turn.assistant_text})

        # 当前输入
        messages.append({"role": "user", "content": user_text})

        return system, messages

    def _call_llm(self, system: str, messages: list[dict]) -> tuple[str, str]:
        """调用 LLM，返回 (回复文本, 情绪)。"""

        import json
        import urllib.request

        # 构建完整消息列表
        full_messages = [{"role": "system", "content": system}] + messages

        payload = json.dumps(
            {
                "model": self._cfg.llm_model,
                "messages": full_messages,
                "max_tokens": 200,
                "temperature": 0.85,
                "top_p": 0.9,
            }
        ).encode("utf-8")

        req = urllib.request.Request(
            f"{self._cfg.llm_base_url}/chat/completions",
            data=payload,
            headers={
                "Authorization": f"Bearer {self._cfg.llm_api_key}",
                "Content-Type": "application/json",
            },
        )

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            text = data["choices"][0]["message"]["content"].strip()

            # 简单情绪推断
            emotion = "neutral"
            for keyword, emo in [
                ("开心", "happy"), ("笑", "happy"), ("哈哈", "happy"),
                ("难过", "sad"), ("伤心", "sad"),
                ("惊讶", "surprise"), ("天哪", "surprise"),
                ("生气", "angry"),
            ]:
                if keyword in text:
                    emotion = emo
                    break

            return text, emotion
        except Exception as exc:
            logger.error("LLM 调用失败: %s", exc)
            return f"抱歉，我暂时无法回复。({exc})", "neutral"


@dataclass
class RobotResponse:
    """一轮闭环的输出。"""

    text: str
    emotion: str = "neutral"
    actions: list[str] = field(default_factory=list)


# ------------------------------------------------------------------
# CLI 测试入口
# ------------------------------------------------------------------


def run_cli_test() -> None:
    """命令行交互式测试闭环。"""

    sk_key = os.environ.get("SILICONFLOW_KEY", "REMOVED_SECRET")
    config = RobotConfig(
        vision_api_key=sk_key,
        vision_model="Qwen/Qwen3-VL-8B-Instruct",
        llm_api_key=sk_key,
        llm_model="deepseek-ai/DeepSeek-V3",
        llm_base_url="https://api.siliconflow.cn/v1",
        debug=True,
    )

    runtime = RobotRuntime(config)

    print("=" * 50)
    print(f"  {config.character_name} 已就绪")
    print(f"  视觉: {'✅' if runtime._analyzer else '❌'}")
    print(f"  LLM:  {'✅' if config.llm_api_key else '❌ (需要 DEEPSEEK_API_KEY)'}")
    print("=" * 50)
    print("  输入文字开始对话，输入 /quit 退出")
    print()

    while True:
        try:
            user_text = input("你: ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if not user_text:
            continue
        if user_text.lower() in ("/quit", "/exit", "quit"):
            break

        response = runtime.run_once(user_text)
        print(f"{config.character_name}: {response.text}")
        print()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_cli_test()
