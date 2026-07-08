"""机器人运行时 — 闭环主循环。

摄像头 → 视觉分析 → 对话上下文 → LLM → TTS/表情。
"""

from __future__ import annotations

import logging
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from visual_companion_robot.integrations.llm_client import LlmClient, LlmClientError

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[4]
SRC_ROOT = PROJECT_ROOT / "main" / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


@dataclass
class RobotConfig:
    """机器人运行时配置。"""

    # 视觉
    vision_enabled: bool = True

    # LLM（云端兜底）
    llm_api_key: str = ""

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

    debug: bool = False


class RobotRuntime:
    """机器人运行时 — 闭环主循环。

    Args:
        config: 运行时配置。
        llm_client: LLM 客户端（云端 DeepSeek 或本地 Qwen2.5）。
        analyzer: 视觉场景分析器（可选）。
    """

    def __init__(
        self,
        config: Optional[RobotConfig] = None,
        llm_client: Optional[LlmClient] = None,
        analyzer=None,
    ) -> None:
        self._cfg = config or RobotConfig()
        self._llm_client = llm_client

        from visual_companion_robot.brain import DialogueContext

        self._context = DialogueContext()
        self._analyzer = analyzer

    # ------------------------------------------------------------------
    # 闭环入口
    # ------------------------------------------------------------------

    def run_once(self, user_text: str, camera_frame=None) -> RobotResponse:
        """执行一轮完整的感知→决策→表达闭环。"""

        # 1. 视觉感知
        if camera_frame is not None and self._analyzer:
            self._update_vision(camera_frame)

        # 2. 构建 LLM 输入
        system, messages = self._build_prompt(user_text)

        # 3. LLM 推理
        response_text, emotion = self._call_llm(system, messages)

        # 4. 动作分类 + 清理展示文本
        action = classify_action(response_text)
        display = clean_display_text(response_text)

        # 5. 保存对话
        from visual_companion_robot.brain import DialogueTurn

        self._context.history.append(
            DialogueTurn(
                user_text=user_text,
                assistant_text=response_text,
                emotion=emotion,
            )
        )

        return RobotResponse(
            text=response_text,
            display_text=display,
            emotion=emotion,
            actions=[action] if action else [],
        )

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _update_vision(self, frame_bgr) -> None:
        from visual_companion_robot.perception import PerceptionFrame

        t0 = time.time()
        pf = self._analyzer.analyze(frame_bgr)
        self._context.update_from_perception(pf.to_dict())

        if self._cfg.debug:
            dt = time.time() - t0
            print(f"  [视觉] {pf.summary()} ({dt:.1f}s)")

    def _build_prompt(self, user_text: str) -> tuple[str, list[dict]]:
        system = self._cfg.character_persona

        vision = self._context.build_llm_context()
        if vision:
            system += (
                f"\n\n【你此刻看到的主人】\n"
                f"{vision}\n"
                f"请在回复中自然地提及你看到的场景，比如主人的情绪或正在做的事。"
                f"如果画面中没有人，可以表达想念或好奇。"
            )

        system += _build_time_hint()

        messages = []
        for turn in self._context.history[-4:]:
            messages.append({"role": "user", "content": turn.user_text})
            messages.append({"role": "assistant", "content": turn.assistant_text})
        messages.append({"role": "user", "content": user_text})

        return system, messages

    def _call_llm(self, system: str, messages: list[dict]) -> tuple[str, str]:
        """调用 LLM，返回 (回复文本, 情绪)。

        优先使用注入的 llm_client（支持本地/云端双后端）。
        无客户端时降级到直接调用 DeepSeek API（向后兼容）。
        """

        if self._llm_client is not None:
            return self._call_via_client(system, messages)

        return self._call_deepseek_direct(system, messages)

    def _call_via_client(self, system: str, messages: list) -> tuple[str, str]:
        try:
            from visual_companion_robot.integrations.llm_client import LlmContext
            user_prompt = messages[-1]["content"] if messages else ""
            ctx = LlmContext(
                user_prompt=user_prompt,
                expressions=[],
                motions=[],
                runtime_context={"system": system, "messages": messages},
            )
            plan = self._llm_client.generate_live2d_control(ctx)
            return plan.text, plan.emotion
        except LlmClientError as exc:
            logger.error("LLM 调用失败: %s", exc)
            return f"抱歉，我暂时无法回复。({exc})", "neutral"

    def _call_deepseek_direct(self, system: str, messages: list) -> tuple[str, str]:
        """直接调用 DeepSeek API（向后兼容）。"""

        import json
        import urllib.request

        full = [{"role": "system", "content": system}] + messages
        payload = json.dumps({
            "model": self._cfg.llm_model if hasattr(self._cfg, "llm_model") else "deepseek-chat",
            "messages": full,
            "max_tokens": 200,
            "temperature": 0.85,
        }).encode("utf-8")

        base_url = getattr(self._cfg, "llm_base_url", "https://api.deepseek.com")
        req = urllib.request.Request(
            f"{base_url}/chat/completions",
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
            emotion = _infer_emotion(text)
            return text, emotion
        except Exception as exc:
            logger.error("LLM 调用失败: %s", exc)
            return f"抱歉，我暂时无法回复。({exc})", "neutral"


@dataclass
class RobotResponse:
    """一轮闭环的输出。"""

    text: str
    emotion: str = "neutral"
    display_text: str = ""
    actions: list[str] = field(default_factory=list)


def _infer_emotion(text: str) -> str:
    for keyword, emo in [
        ("开心", "happy"), ("笑", "happy"), ("哈哈", "happy"),
        ("难过", "sad"), ("伤心", "sad"),
        ("惊讶", "surprise"), ("天哪", "surprise"),
        ("生气", "angry"),
    ]:
        if keyword in text:
            return emo
    return "neutral"


# ── 动作映射表 ───────────────────────────────────────────────────

_ACTION_MAP: dict[str, tuple[str, str]] = {
    "开心": ("heart", "pulse"), "高兴": ("heart", "pulse"), "快乐": ("heart", "pulse"),
    "嘻嘻": ("heart", "pulse"), "哈哈": ("heart", "pulse"), "笑": ("heart", "pulse"),
    "可爱": ("heart", "pulse"), "幸福": ("heart", "pulse"), "甜蜜": ("heart", "pulse"),
    "温暖": ("heart", "pulse"), "爱心": ("heart", "pulse"), "心": ("heart", "pulse"),
    "星星眼": ("star_eyes", "pulse"), "闪闪": ("star_eyes", "pulse"), "发光": ("star_eyes", "pulse"),
    "惊喜": ("star_eyes", "pulse"), "耶": ("star_eyes", "pulse"),
    "花花": ("flowers", "pulse"), "花": ("flowers", "pulse"), "撒花": ("flowers", "pulse"),
    "庆祝": ("flowers", "pulse"),
    "害羞": ("blush", "pulse"), "脸红": ("blush", "pulse"), "不好意思": ("blush", "pulse"),
    "羞": ("blush", "pulse"), "扭捏": ("blush", "pulse"), "低头": ("blush", "pulse"),
    "蹭": ("blush", "pulse"), "傲娇": ("blush", "pulse"), "哼": ("blush", "pulse"),
    "生气": ("angry", "pulse"), "怒": ("angry", "pulse"), "讨厌": ("angry", "pulse"),
    "烦": ("angry", "pulse"), "气": ("angry", "pulse"), "跺脚": ("angry", "pulse"),
    "鼓起腮帮": ("angry", "pulse"),
    "哭": ("cry", "pulse"), "难过": ("cry", "pulse"), "伤心": ("cry", "pulse"),
    "呜呜": ("cry", "pulse"), "泪": ("cry", "pulse"), "委屈": ("cry", "pulse"), "心疼": ("cry", "pulse"),
    "黑脸": ("shadow_face", "pulse"), "无语": ("shadow_face", "pulse"), "无奈": ("shadow_face", "pulse"),
    "扶额": ("shadow_face", "pulse"),
    "汗": ("sweat", "pulse"), "流汗": ("sweat", "pulse"), "尴尬": ("sweat", "pulse"), "黑线": ("sweat", "pulse"),
    "疑惑": ("question", "pulse"), "问号": ("question", "pulse"), "歪头": ("question", "pulse"),
    "不解": ("question", "pulse"), "懵": ("question", "pulse"), "诶": ("question", "pulse"),
    "晕": ("dizzy", "pulse"), "头晕": ("dizzy", "pulse"), "眼花": ("dizzy", "pulse"),
    "天旋地转": ("dizzy", "pulse"),
    "着急": ("anxious", "pulse"), "急": ("anxious", "pulse"), "慌": ("anxious", "pulse"),
    "担心": ("anxious", "pulse"), "紧张": ("anxious", "pulse"),
    "挥手": ("scene1", "pulse"), "招手": ("scene1", "pulse"), "打招呼": ("scene1", "pulse"),
    "蹦": ("scene1", "pulse"), "跳": ("scene1", "pulse"), "蹦蹦跳跳": ("scene1", "pulse"),
    "雀跃": ("scene1", "pulse"), "手舞足蹈": ("scene1", "pulse"), "扭": ("scene1", "pulse"),
    "比心": ("finger_heart", "pulse"), "比心心": ("finger_heart", "pulse"), "笔芯": ("finger_heart", "pulse"),
    "双马尾": ("twin_tail", "hold"), "马尾": ("twin_tail", "hold"),
    "举手": ("right_hand_up", "pulse"), "抬手": ("right_hand_up", "pulse"),
    "举手手": ("right_hand_up", "pulse"), "竖起": ("right_hand_up", "pulse"),
    "黑化": ("dark_mode", "pulse"), "恶魔": ("dark_mode", "pulse"),
    "坏笑": ("dark_mode", "pulse"), "腹黑": ("dark_mode", "pulse"),
    "唱歌": ("microphone", "hold"), "麦克风": ("microphone", "hold"),
    "游戏": ("gaming", "hold"), "打游戏": ("gaming", "hold"),
    "左手": ("left_hand_up", "pulse"),
    "舰长": ("captain", "pulse"), "提督": ("admiral", "pulse"), "总督": ("governor", "pulse"),
}


def classify_action(text: str) -> str:
    """动作分类：关键词优先，本地缓存兜底。

    Args:
        text: LLM 回复文本。

    Returns:
        Live2D 动作名，无匹配时返回空字符串。
    """

    kw = _extract_action_by_keyword(text)
    if kw:
        return kw
    if text in _ACTION_CLASSIFY_CACHE:
        return _ACTION_CLASSIFY_CACHE[text]
    return ""


_ACTION_CLASSIFY_CACHE: dict[str, str] = {}


def _extract_action_by_keyword(text: str) -> str:
    best = ""
    best_len = 0
    for keyword, (action_name, _mode) in _ACTION_MAP.items():
        if keyword in text and len(keyword) > best_len:
            best = action_name
            best_len = len(keyword)
    return best


def clean_display_text(text: str) -> str:
    import re
    text = re.sub(r"\([^)]*\)", "", text)
    text = re.sub(r"（[^）]*）", "", text)
    return text.strip()


def _build_time_hint() -> str:
    from datetime import datetime

    now = datetime.now()
    hint = f"\n\n【现在的时间】{now.strftime('%Y年%m月%d日 %H:%M')}"
    hour = now.hour
    if hour < 6:
        hint += " 现在是深夜，主人还没睡，你要温柔地催主人休息。"
    elif hour < 9:
        hint += " 现在是早晨，可以活泼地和主人说早安。"
    elif hour < 12:
        hint += " 现在是上午。"
    elif hour < 14:
        hint += " 现在是中午，可以提醒主人吃午饭。"
    elif hour < 18:
        hint += " 现在是下午。"
    elif hour < 22:
        hint += " 现在是晚上。"
    else:
        hint += " 现在是深夜，要注意关心主人的作息。"
    return hint


# ── 工具函数（供 export_rknn.py 等外部使用） ──────────────────────

def _get_available_actions() -> list[str]:
    return [
        "heart", "star_eyes", "flowers", "blush",
        "angry", "cry", "shadow_face", "sweat",
        "question", "dizzy", "anxious", "dark_mode",
        "right_hand_up", "left_hand_up", "finger_heart",
        "scene1", "twin_tail", "microphone", "gaming",
        "up", "down", "left", "right",
        "captain", "admiral", "governor",
        "none",
    ]


# ── CLI 测试入口 ─────────────────────────────────────────────────

def run_cli_test() -> None:
    from visual_companion_robot.integrations.llm_client import create_llm_client

    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    llm = create_llm_client(backend="cloud", api_key=api_key)

    config = RobotConfig(
        llm_api_key=api_key,
        debug=True,
    )

    runtime = RobotRuntime(config, llm_client=llm)

    print("=" * 50)
    print(f"  {config.character_name} 已就绪")
    print(f"  LLM: {'✅' if llm else '❌'}")
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
