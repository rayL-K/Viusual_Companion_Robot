"""语言模型控制客户端 — 双后端。

LlmClient 抽象基类，DeepSeekLlmClient（云端）和 LocalLlmClient（本地 Qwen2.5）。
所有后端输出相同的 Live2DControlPlan 结构。
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_DEEPSEEK_MODEL = "deepseek-v4-flash"
DEFAULT_CONTROL_MAX_TOKENS = 360

_LIVE2D_SYSTEM_PROMPT = (
    "你是虚拟陪伴机器人草莓兔兔的导演。"
    "请只输出一个 JSON 对象，不要 Markdown。"
    "JSON 字段必须包含：text, emotion, expression, motion, actions, speech, parameters。"
    "text 是适合用温柔中文女声朗读的一句话或两句话，默认不超过 70 个汉字。"
    "emotion 从 happy, neutral, shy, surprised, sad, angry, thinking 中选择。"
    "expression 必须从允许表情中选择。motion 必须从允许动作中选择。"
    "actions 是数组，用来控制会持续显示的道具或姿态。"
    "action.name 可选 gaming, microphone, finger_heart, right_hand_up, left_hand_up, heart, blush, question, up, down, left, right。"
    "action.mode 可选 hold, pulse, off。hold 表示一直保持，pulse 表示短时动作，off 表示关闭同组动作。"
    "action.delay_ms 表示延迟多少毫秒后执行，默认 0，范围 0 到 30000。"
    "当用户要求一直拿着、保持、持续展示某个动作时使用 hold；唱歌或说话需要麦克风时使用 microphone hold；玩游戏或拿游戏机时使用 gaming hold。"
    "当用户要求先做 A、几秒后做 B、然后做 C 时，必须把计划拆进 actions，不能只写进 text。"
    "例如\"先举起双手，5 秒后拿游戏机\"应输出 right_hand_up hold、left_hand_up hold、gaming hold delay_ms=5000。"
    "实时天气等事实必须优先使用联网事实字段；没有联网事实或联网失败时，不要编造实时信息。"
    "当前运行上下文.vision 是板端摄像头事实；当用户问画面、人物、环境、物体或表情时，必须优先引用 vision 字段，不要编造风景或不存在的内容。"
    "若 vision.enabled 为 false 或 status 为 stale，应说明当前没有稳定画面，不要猜测。"
    "近期记忆包含 time 和 relative_time，回答记忆或时间问题时必须使用这些具体时间，不要凭聊天顺序猜昨天、前天。"
    "如果用户要求说明你记得什么，要给出具体日期时间或相对时间。"
    "duration_ms 只对 pulse 有效，保持在 300 到 10000。"
    "speech.voice 固定为 female_zh，rate 在 0.85 到 1.15，pitch 在 1.0 到 1.35。"
    "parameters 只能包含 ParamAngleX, ParamAngleY, ParamAngleZ, "
    "ParamBodyAngleX, ParamBodyAngleY, ParamMouthForm，数值保持在合理范围。"
)

_ERROR_REPAIR_PROMPT = (
    "你是 JSON 修复器。只输出一个合法 JSON 对象，不要 Markdown。"
    "必须包含 text, emotion, expression, motion, actions, speech, parameters。"
    "不得解释错误，不得输出多余文本。"
)


@dataclass
class LlmRequest:
    prompt: str
    system_prompt: str = ""
    max_tokens: int = 512


@dataclass
class SpeechControl:
    voice: str = "female_zh"
    rate: float = 1.0
    pitch: float = 1.15


@dataclass
class Live2DActionControl:
    name: str
    mode: str = "pulse"
    duration_ms: int = 2600
    delay_ms: int = 0


@dataclass
class Live2DControlPlan:
    text: str
    emotion: str = "neutral"
    expression: str = ""
    motion: str = ""
    actions: List[Live2DActionControl] = field(default_factory=list)
    speech: SpeechControl = field(default_factory=SpeechControl)
    parameters: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["parameters"] = dict(sorted(data["parameters"].items()))
        return data


class LlmClientError(RuntimeError):
    pass


class LlmResponseFormatError(LlmClientError):
    pass


# ── 共享上下文（减少参数数量） ────────────────────────────────────

@dataclass
class LlmContext:
    """LLM 调用的上下文参数包。"""
    user_prompt: str
    expressions: List[str]
    motions: List[str]
    memory_context: List[Dict[str, Any]] = field(default_factory=list)
    long_term_memory: List[Dict[str, Any]] = field(default_factory=list)
    runtime_context: Dict[str, Any] = field(default_factory=dict)
    web_context: Dict[str, Any] = field(default_factory=lambda: {"enabled": True, "facts": [], "errors": []})


# ── 抽象基类 ──────────────────────────────────────────────────────

class LlmClient(ABC):
    @abstractmethod
    def generate_live2d_control(self, ctx: LlmContext) -> Live2DControlPlan:
        ...


# ── DeepSeek 云端后端 ─────────────────────────────────────────────

class DeepSeekLlmClient(LlmClient):
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout_sec: int = 45,
    ) -> None:
        self.api_key = api_key or os.environ.get("DEEPSEEK_API_KEY", "")
        self.base_url = (base_url or os.environ.get("DEEPSEEK_BASE_URL") or DEFAULT_DEEPSEEK_BASE_URL).rstrip("/")
        self.model = model or os.environ.get("DEEPSEEK_MODEL") or DEFAULT_DEEPSEEK_MODEL
        self.timeout_sec = timeout_sec
        if not self.api_key:
            raise LlmClientError("缺少 DEEPSEEK_API_KEY 环境变量。")

    def generate_live2d_control(self, ctx: LlmContext) -> Live2DControlPlan:
        request = self._build_request(ctx)
        response = self._post_chat_completion(request)
        content = self._extract_content(response)
        return self._parse_or_fallback(content, ctx)

    def _parse_or_fallback(self, content: str, ctx: LlmContext) -> Live2DControlPlan:
        try:
            plan = parse_live2d_control_plan(content, ctx.expressions, ctx.motions)
            return normalize_action_plan_for_user_text(ctx.user_prompt, plan)
        except LlmResponseFormatError as exc:
            print(f"[LLM] 结构化回复解析失败，准备请求 LLM 修复结构：{exc}")
            try:
                repaired = self._repair_control_content(ctx.user_prompt, content, str(exc), ctx.expressions, ctx.motions)
                plan = parse_live2d_control_plan(repaired, ctx.expressions, ctx.motions)
                return normalize_action_plan_for_user_text(ctx.user_prompt, plan)
            except (LlmClientError, LlmResponseFormatError) as e:
                print(f"[LLM] 结构修复失败，已降级为安全控制计划：{e}")
                plan = build_fallback_live2d_control_plan(content, ctx.expressions, ctx.motions)
                return normalize_action_plan_for_user_text(ctx.user_prompt, plan)

    @staticmethod
    def _build_user_content(ctx: LlmContext) -> dict:
        return {
            "用户输入": ctx.user_prompt,
            "当前运行上下文": ctx.runtime_context,
            "联网事实": ctx.web_context,
            "近期记忆": ctx.memory_context[-6:],
            "长期记忆": ctx.long_term_memory[-12:],
            "允许表情": ctx.expressions,
            "允许动作": ctx.motions,
            "输出示例": {
                "text": "主人，我已经准备好继续陪你调试啦。",
                "emotion": "happy",
                "expression": "heart",
                "motion": "scene1",
                "actions": [{"name": "finger_heart", "mode": "pulse", "duration_ms": 2600, "delay_ms": 0}],
                "speech": {"voice": "female_zh", "rate": 1.0, "pitch": 1.18},
                "parameters": {"ParamAngleX": 4, "ParamAngleY": 2, "ParamMouthForm": 0.3},
            },
        }

    def _build_request(self, ctx: LlmContext) -> Dict[str, Any]:
        return {
            "model": self.model,
            "messages": [
                {"role": "system", "content": _LIVE2D_SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(self._build_user_content(ctx), ensure_ascii=False)},
            ],
            "temperature": 0.45,
            "max_tokens": DEFAULT_CONTROL_MAX_TOKENS,
            "response_format": {"type": "json_object"},
        }

    def _repair_control_content(self, user_prompt: str, broken_content: str, parse_error: str, expressions: List[str], motions: List[str]) -> str:
        repair_request = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": _ERROR_REPAIR_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps({
                        "原始用户输入": user_prompt,
                        "解析错误": parse_error,
                        "上一次错误回复": broken_content,
                        "允许表情": expressions,
                        "允许动作": motions,
                        "固定结构": {
                            "text": "可朗读中文回复",
                            "emotion": "happy",
                            "expression": expressions[0] if expressions else "",
                            "motion": motions[0] if motions else "",
                            "actions": [],
                            "speech": {"voice": "female_zh", "rate": 1.0, "pitch": 1.15},
                            "parameters": {"ParamMouthForm": 0.2},
                        },
                    }, ensure_ascii=False),
                },
            ],
            "temperature": 0.1,
            "max_tokens": 500,
            "response_format": {"type": "json_object"},
        }
        response = self._post_chat_completion(repair_request)
        return self._extract_content(response)

    def _post_chat_completion(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            url=self.base_url + "/chat/completions",
            data=body,
            method="POST",
            headers={"Authorization": "Bearer {0}".format(self.api_key), "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_sec) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise LlmClientError("DeepSeek API 返回 HTTP {0}：{1}".format(exc.code, detail)) from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise LlmClientError("DeepSeek API 调用失败：{0}".format(exc)) from exc

    @staticmethod
    def _extract_content(response: Dict[str, Any]) -> str:
        try:
            return str(response["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError) as exc:
            raise LlmClientError("DeepSeek 响应缺少 choices[0].message.content。") from exc


# ── 本地 RKLLM 后端 ──────────────────────────────────────────────

class LocalLlmClient(LlmClient):
    def __init__(self, model_path: str, n_threads: int = 4, max_tokens: int = 600) -> None:
        from visual_companion_robot.integrations.model_runtime import RkllmEngine
        self._engine = RkllmEngine(n_threads=n_threads, max_tokens=max_tokens)
        self._engine.load(model_path)

    def generate_live2d_control(self, ctx: LlmContext) -> Live2DControlPlan:
        prompt = json.dumps({
            "用户输入": ctx.user_prompt,
            "当前运行上下文": ctx.runtime_context,
            "联网事实": ctx.web_context,
            "近期记忆": ctx.memory_context[-6:],
            "长期记忆": ctx.long_term_memory[-12:],
            "允许表情": ctx.expressions,
            "允许动作": ctx.motions,
        }, ensure_ascii=False)

        content = self._engine.generate(prompt=prompt, system_prompt=_LIVE2D_SYSTEM_PROMPT, temperature=0.5)
        try:
            plan = parse_live2d_control_plan(content, ctx.expressions, ctx.motions)
            return normalize_action_plan_for_user_text(ctx.user_prompt, plan)
        except LlmResponseFormatError:
            plan = build_fallback_live2d_control_plan(content, ctx.expressions, ctx.motions)
            return normalize_action_plan_for_user_text(ctx.user_prompt, plan)


# ── 工厂 ──────────────────────────────────────────────────────────

def create_llm_client(backend: str, api_key: str = "", model_path: str = "", base_url: str = DEFAULT_DEEPSEEK_BASE_URL, model: str = DEFAULT_DEEPSEEK_MODEL) -> LlmClient:
    if backend == "local":
        if not model_path:
            raise ValueError("local 后端需要 model_path")
        return LocalLlmClient(model_path=model_path)
    if not api_key:
        api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    return DeepSeekLlmClient(api_key=api_key, base_url=base_url, model=model)


# ── 共享解析工具 ──────────────────────────────────────────────────

def parse_live2d_control_plan(content: str, expressions: List[str], motions: List[str]) -> Live2DControlPlan:
    data = _parse_json_object(content)
    speech_data = data.get("speech") if isinstance(data.get("speech"), dict) else {}
    return Live2DControlPlan(
        text=str(data.get("text") or "我准备好继续陪你测试啦。"),
        emotion=str(data.get("emotion") or "neutral"),
        expression=_pick_allowed(str(data.get("expression", "")), expressions),
        motion=_pick_allowed(str(data.get("motion", "")), motions),
        actions=_sanitize_actions(data.get("actions") if isinstance(data.get("actions"), list) else []),
        speech=SpeechControl(
            voice="female_zh",
            rate=_clamp_float(speech_data.get("rate", 1.0), 0.75, 1.25),
            pitch=_clamp_float(speech_data.get("pitch", 1.15), 0.8, 1.45),
        ),
        parameters=_sanitize_parameters(data.get("parameters") if isinstance(data.get("parameters"), dict) else {}),
    )


def build_fallback_live2d_control_plan(content: str, expressions: List[str], motions: List[str]) -> Live2DControlPlan:
    return Live2DControlPlan(
        text=_extract_fallback_text(content),
        emotion="thinking",
        expression=_pick_allowed("question", expressions),
        motion=_pick_allowed("", motions),
        actions=[],
        speech=SpeechControl(voice="female_zh", rate=1.0, pitch=1.12),
        parameters={"ParamMouthForm": 0.15},
    )


def normalize_action_plan_for_user_text(user_prompt: str, plan: Live2DControlPlan) -> Live2DControlPlan:
    text = str(user_prompt or "")
    actions = list(plan.actions)
    no_props = any(kw in text for kw in ["不要拿", "不拿", "别拿", "不能拿", "不要任何东西"])
    if no_props:
        actions = [a for a in actions if a.name not in {"gaming", "microphone"}]
    if _asks_for_both_hands_up(text):
        actions = _upsert_action(actions, "right_hand_up", "hold", 0)
        actions = _upsert_action(actions, "left_hand_up", "hold", 0)
    if not no_props and _mentions_gaming(text):
        actions = _upsert_action(actions, "gaming", "hold", _extract_delay_ms(text))
    if not no_props and _mentions_microphone(text):
        actions = _upsert_action(actions, "microphone", "hold", _extract_delay_ms(text))
    plan.actions = actions[:4]
    return plan


def _asks_for_both_hands_up(text: str) -> bool:
    return "举" in text and any(kw in text for kw in ["双手", "两只手", "两个手", "双臂"])


def _mentions_gaming(text: str) -> bool:
    return any(kw in text for kw in ["游戏机", "打游戏", "玩游戏"])


def _mentions_microphone(text: str) -> bool:
    return any(kw in text for kw in ["麦克风", "话筒", "唱歌"])


def _upsert_action(actions: List[Live2DActionControl], name: str, mode: str, delay_ms: int) -> List[Live2DActionControl]:
    kept = [a for a in actions if a.name != name]
    kept.append(Live2DActionControl(name=name, mode=mode, duration_ms=2600, delay_ms=delay_ms))
    return kept


def _extract_delay_ms(text: str) -> int:
    match = re.search(r"([0-9]+|[一二两三四五六七八九十]+)\s*(?:秒|s|S)\s*(?:后|以后|之后)", text)
    if not match:
        return 0
    return int(_clamp_float(_chinese_or_int(match.group(1)) * 1000, 0, 30000))


def _chinese_or_int(value: str) -> int:
    if value.isdigit():
        return int(value)
    digits = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    if value == "十":
        return 10
    if value.startswith("十"):
        return 10 + digits.get(value[-1], 0)
    if value.endswith("十"):
        return digits.get(value[0], 1) * 10
    if "十" in value:
        left, right = value.split("十", 1)
        return digits.get(left, 1) * 10 + digits.get(right, 0)
    return digits.get(value, 0)


def _parse_json_object(content: str) -> Dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`").strip()
        if text.startswith("json"):
            text = text[4:].strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise LlmResponseFormatError("LLM 没有返回 JSON 对象。")
    try:
        data = json.loads(text[start: end + 1])
    except json.JSONDecodeError as exc:
        raise LlmResponseFormatError("LLM JSON 无法解析：{0}".format(exc)) from exc
    if not isinstance(data, dict):
        raise LlmResponseFormatError("LLM JSON 顶层必须是对象。")
    return data


def _extract_fallback_text(content: str) -> str:
    text = str(content or "").strip()
    text_match = re.search(r'"text"\s*:\s*"([^"]{1,300})"', text)
    if text_match:
        text = text_match.group(1)
    else:
        text = text.strip("`").strip()
        if text.lower().startswith("json"):
            text = text[4:].strip()
        if text.startswith(("{", "[")):
            text = ""
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        text = "我刚才没有按控制格式组织好回复，但我已经收到你的话了，我们继续测试。"
    if len(text) > 160:
        text = text[:157] + "..."
    return text


def _pick_allowed(value: str, allowed: List[str]) -> str:
    if value in allowed:
        return value
    return allowed[0] if allowed else ""


def _sanitize_parameters(parameters: Dict[str, Any]) -> Dict[str, float]:
    limits = {
        "ParamAngleX": (-25.0, 25.0), "ParamAngleY": (-20.0, 20.0), "ParamAngleZ": (-20.0, 20.0),
        "ParamBodyAngleX": (-15.0, 15.0), "ParamBodyAngleY": (-12.0, 12.0),
        "ParamMouthForm": (-1.0, 1.0), "ParamMouthOpenY": (0.0, 1.0),
    }
    safe: Dict[str, float] = {}
    for key, value in parameters.items():
        if key not in limits:
            continue
        min_v, max_v = limits[key]
        safe[key] = _clamp_float(value, min_v, max_v)
    return safe


def _sanitize_actions(actions: List[Any]) -> List[Live2DActionControl]:
    allowed = {"gaming", "microphone", "finger_heart", "right_hand_up", "left_hand_up", "heart", "blush", "question", "up", "down", "left", "right"}
    sanitized: List[Live2DActionControl] = []
    for item in actions[:4]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "")
        if name not in allowed:
            continue
        mode = str(item.get("mode") or "pulse")
        if mode not in {"hold", "pulse", "off"}:
            mode = "pulse"
        duration_ms = int(_clamp_float(item.get("duration_ms", item.get("durationMs", 2600)), 300, 10000))
        delay_ms = int(_clamp_float(item.get("delay_ms", item.get("delayMs", 0)), 0, 30000))
        sanitized.append(Live2DActionControl(name=name, mode=mode, duration_ms=duration_ms, delay_ms=delay_ms))
    return sanitized


def _clamp_float(value: Any, min_value: float, max_value: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = min_value
    return max(min_value, min(max_value, number))
