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

        # 4. 子 LLM 动作分类 + 清理展示文本
        action = classify_action(response_text, self._cfg.llm_api_key)
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
    display_text: str = ""  # 展示文本（去掉动作描述后的纯文本）
    actions: list[str] = field(default_factory=list)


# ── 动作映射表：LLM 输出关键词 → Live2D 动作名 ──────────────────

_ACTION_MAP: dict[str, tuple[str, str]] = {
    # ═══ 正面情绪 ═══
    "开心": ("heart", "pulse"),
    "高兴": ("heart", "pulse"),
    "快乐": ("heart", "pulse"),
    "嘻嘻": ("heart", "pulse"),
    "哈哈": ("heart", "pulse"),
    "笑": ("heart", "pulse"),
    "可爱": ("heart", "pulse"),
    "幸福": ("heart", "pulse"),
    "甜蜜": ("heart", "pulse"),
    "温暖": ("heart", "pulse"),
    "爱心": ("heart", "pulse"),
    "心": ("heart", "pulse"),
    "星星眼": ("star_eyes", "pulse"),
    "闪闪": ("star_eyes", "pulse"),
    "发光": ("star_eyes", "pulse"),
    "惊喜": ("star_eyes", "pulse"),
    "耶": ("star_eyes", "pulse"),
    "花花": ("flowers", "pulse"),
    "花": ("flowers", "pulse"),
    "撒花": ("flowers", "pulse"),
    "庆祝": ("flowers", "pulse"),
    # ═══ 害羞/傲娇 ═══
    "害羞": ("blush", "pulse"),
    "脸红": ("blush", "pulse"),
    "不好意思": ("blush", "pulse"),
    "羞": ("blush", "pulse"),
    "扭捏": ("blush", "pulse"),
    "低头": ("blush", "pulse"),
    "蹭": ("blush", "pulse"),
    "不好意思": ("blush", "pulse"),
    "傲娇": ("blush", "pulse"),
    "哼": ("blush", "pulse"),  # 傲娇式哼
    # ═══ 负面情绪 ═══
    "生气": ("angry", "pulse"),
    "怒": ("angry", "pulse"),
    "讨厌": ("angry", "pulse"),
    "烦": ("angry", "pulse"),
    "气": ("angry", "pulse"),
    "跺脚": ("angry", "pulse"),
    "鼓起腮帮": ("angry", "pulse"),
    "哭": ("cry", "pulse"),
    "难过": ("cry", "pulse"),
    "伤心": ("cry", "pulse"),
    "呜呜": ("cry", "pulse"),
    "泪": ("cry", "pulse"),
    "委屈": ("cry", "pulse"),
    "心疼": ("cry", "pulse"),
    "黑脸": ("shadow_face", "pulse"),
    "无语": ("shadow_face", "pulse"),
    "无奈": ("shadow_face", "pulse"),
    "扶额": ("shadow_face", "pulse"),
    "汗": ("sweat", "pulse"),
    "流汗": ("sweat", "pulse"),
    "尴尬": ("sweat", "pulse"),
    "黑线": ("sweat", "pulse"),
    # ═══ 疑惑/惊讶 ═══
    "疑惑": ("question", "pulse"),
    "问号": ("question", "pulse"),
    "歪头": ("question", "pulse"),
    "不解": ("question", "pulse"),
    "懵": ("question", "pulse"),
    "诶": ("question", "pulse"),
    "晕": ("dizzy", "pulse"),
    "头晕": ("dizzy", "pulse"),
    "眼花": ("dizzy", "pulse"),
    "天旋地转": ("dizzy", "pulse"),
    "着急": ("anxious", "pulse"),
    "急": ("anxious", "pulse"),
    "慌": ("anxious", "pulse"),
    "担心": ("anxious", "pulse"),
    "紧张": ("anxious", "pulse"),
    # ═══ 动作/姿态 ═══
    "挥手": ("scene1", "pulse"),
    "招手": ("scene1", "pulse"),
    "打招呼": ("scene1", "pulse"),
    "蹦": ("scene1", "pulse"),
    "跳": ("scene1", "pulse"),
    "蹦蹦跳跳": ("scene1", "pulse"),
    "雀跃": ("scene1", "pulse"),
    "手舞足蹈": ("scene1", "pulse"),
    "扭": ("scene1", "pulse"),
    "比心": ("finger_heart", "pulse"),
    "比心心": ("finger_heart", "pulse"),
    "笔芯": ("finger_heart", "pulse"),
    "双马尾": ("twin_tail", "hold"),
    "马尾": ("twin_tail", "hold"),
    "举手": ("right_hand_up", "pulse"),
    "抬手": ("right_hand_up", "pulse"),
    "举手手": ("right_hand_up", "pulse"),
    "竖起": ("right_hand_up", "pulse"),
    # ═══ 其他状态 ═══
    "黑化": ("dark_mode", "pulse"),
    "恶魔": ("dark_mode", "pulse"),
    "坏笑": ("dark_mode", "pulse"),
    "腹黑": ("dark_mode", "pulse"),
    # ═══ 新增动作映射 ═══
    "唱歌": ("microphone", "hold"),
    "麦克风": ("microphone", "hold"),
    "游戏": ("gaming", "hold"),
    "打游戏": ("gaming", "hold"),
    "左手": ("left_hand_up", "pulse"),
    "舰长": ("captain", "pulse"),
    "提督": ("admiral", "pulse"),
    "总督": ("governor", "pulse"),
}


def classify_action(text: str, api_key: str, base_url: str = "https://api.siliconflow.cn/v1") -> str:
    """动作分类：关键词优先，无匹配时调子 LLM。

    关键词匹配零延迟零成本，覆盖 90% 场景。子 LLM 处理关键词覆盖不到
    的微妙表达（如「把围巾盖在身上假装被子」→ none）。

    Args:
        text: LLM 回复文本。
        api_key: API token。
        base_url: API 基地址。

    Returns:
        Live2D 动作名，无匹配时返回空字符串。
    """

    # 1. 关键词匹配（<1ms，免费）
    kw = _extract_action_by_keyword(text)
    if kw:
        return kw

    # 2. 缓存命中（<1ms）
    if text in _ACTION_CLASSIFY_CACHE:
        return _ACTION_CLASSIFY_CACHE[text]

    # 3. 子 LLM 兜底（~5s，~0.001 元）
    return _classify_action_by_llm(text, api_key, base_url)


def _classify_action_by_llm(text: str, api_key: str, base_url: str = "https://api.siliconflow.cn/v1") -> str:
    """子 LLM 动作分类（关键词未命中时的兜底方案）。"""

    import json
    import urllib.request

    available = [
        # 表情
        "heart", "star_eyes", "flowers", "blush",
        "angry", "cry", "shadow_face", "sweat",
        "question", "dizzy", "anxious", "dark_mode",
        # 手势
        "right_hand_up", "left_hand_up", "finger_heart",
        # 动作
        "scene1", "twin_tail", "microphone", "gaming",
        # 方向
        "up", "down", "left", "right",
        # 轮盘
        "captain", "admiral", "governor",
        # 无
        "none",
    ]

    prompt = (
        "你是一个动作分类器。给定角色的对话回复，判断角色此刻应该播放哪个 Live2D 表情或动作。\n\n"
        "注意：只能从下面列表中选择一个动作名，不要自创。\n\n"
        "=== 可选动作 ===\n"
        "【表情】\n"
        "- heart: 开心、高兴、感到温暖、觉得可爱\n"
        "- star_eyes: 惊喜、兴奋、眼前一亮、星星眼\n"
        "- flowers: 庆祝、撒花、美好的氛围\n"
        "- blush: 害羞、脸红、不好意思、被夸奖、撒娇、蹭蹭\n"
        "- angry: 生气、不满、跺脚、鼓起腮帮\n"
        "- cry: 难过、伤心、哭泣、委屈、心疼、眼泪汪汪\n"
        "- shadow_face: 无语、无奈、黑线、扶额\n"
        "- sweat: 尴尬、流汗、囧\n"
        "- question: 疑惑、歪头、不解、懵、问号\n"
        "- dizzy: 头晕、眼花、被绕晕、天旋地转\n"
        "- anxious: 着急、慌张、担心、紧张\n"
        "- dark_mode: 黑化、坏笑、恶魔、腹黑\n"
        "【手势】\n"
        "- right_hand_up: 右手举起、举手、抬手、竖手指/耳朵\n"
        "- left_hand_up: 左手举起\n"
        "- finger_heart: 比心、笔芯、比心心\n"
        "- microphone: 拿麦克风、唱歌\n"
        "- gaming: 打游戏、玩游戏\n"
        "【动作】\n"
        "- scene1: 蹦跳、挥手、打招呼、活泼、跳舞、雀跃\n"
        "- twin_tail: 双马尾、变身\n"
        "【方向】\n"
        "- up/down/left/right: 方向移动\n"
        "【轮盘】\n"
        "- captain/admiral/governor: 舰长/提督/总督轮盘\n"
        "【无动作】\n"
        "- none: 没有明显表情或动作，只是普通说话\n\n"
        f"角色回复: {text}\n\n"
        "只回复一个动作名，不要解释，不要标点。"
    )

    payload = json.dumps({
        "model": "Qwen/Qwen3-8B",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 10,
        "temperature": 0.0,
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        action = data["choices"][0]["message"]["content"].strip().lower()
        result = action if action in available else ""
        # 写入缓存：下次相同文本直接命中
        if result:
            _ACTION_CLASSIFY_CACHE[text] = result
        return result
    except Exception:
        return _extract_action_by_keyword(text)


# 子 LLM 分类结果缓存，避免重复调用
_ACTION_CLASSIFY_CACHE: dict[str, str] = {}


def _extract_action_by_keyword(text: str) -> str:
    """关键词回退方案（最长匹配优先）。"""

    best = ""
    best_len = 0
    for keyword, (action_name, _mode) in _ACTION_MAP.items():
        if keyword in text and len(keyword) > best_len:
            best = action_name
            best_len = len(keyword)
    return best


def clean_display_text(text: str) -> str:
    """去掉文本中的动作描述括号（全角/半角），得到纯展示文本。"""

    import re

    text = re.sub(r"\([^)]*\)", "", text)
    text = re.sub(r"（[^）]*）", "", text)
    return text.strip()


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
