"""语言模型控制客户端。

当前阶段允许临时调用 DeepSeek API 来验证“LLM 控制 Live2D 与语音”的协议。
密钥只从环境变量读取，不能写入配置文件、日志或提交历史。后续替换为
Firefly 本地模型时，仍复用这里定义的结构化控制结果。
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_DEEPSEEK_MODEL = "deepseek-v4-flash"


@dataclass
class LlmRequest:
    """一次语言模型请求。"""

    prompt: str
    system_prompt: str = ""
    max_tokens: int = 512


@dataclass
class SpeechControl:
    """LLM 对语音播报的控制意图。"""

    voice: str = "female_zh"
    rate: float = 1.0
    pitch: float = 1.15


@dataclass
class Live2DActionControl:
    """LLM 对可见动作状态的控制意图。"""

    name: str
    mode: str = "pulse"
    duration_ms: int = 2600
    delay_ms: int = 0


@dataclass
class Live2DControlPlan:
    """LLM 输出的统一控制计划。

    这个结构只表达意图，真正写入 Live2D 前还要经过前端或渲染层的白名单
    和范围裁剪，避免模型直接控制任意参数。
    """

    text: str
    emotion: str = "neutral"
    expression: str = ""
    motion: str = ""
    actions: List[Live2DActionControl] = field(default_factory=list)
    speech: SpeechControl = field(default_factory=SpeechControl)
    parameters: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转换为稳定 JSON。"""

        data = asdict(self)
        data["parameters"] = dict(sorted(data["parameters"].items()))
        return data


class LlmClientError(RuntimeError):
    """LLM 调用或结构化解析失败。"""


class LlmResponseFormatError(LlmClientError):
    """LLM 已返回内容，但内容不符合结构化控制协议。"""


class DeepSeekLlmClient:
    """DeepSeek OpenAI 兼容接口客户端。"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout_sec: int = 45,
    ) -> None:
        """初始化 DeepSeek 客户端，API key 优先从环境变量读取。

        Args:
            api_key: DeepSeek API 密钥，默认读取 DEEPSEEK_API_KEY。
            base_url: API 基地址，默认读取 DEEPSEEK_BASE_URL。
            model: 模型名，默认读取 DEEPSEEK_MODEL。
            timeout_sec: HTTP 请求超时秒数。
        """
        self.api_key = api_key or os.environ.get("DEEPSEEK_API_KEY", "")
        self.base_url = (base_url or os.environ.get("DEEPSEEK_BASE_URL") or DEFAULT_DEEPSEEK_BASE_URL).rstrip("/")
        self.model = model or os.environ.get("DEEPSEEK_MODEL") or DEFAULT_DEEPSEEK_MODEL
        self.timeout_sec = timeout_sec
        if not self.api_key:
            raise LlmClientError("缺少 DEEPSEEK_API_KEY 环境变量。")

    def generate_live2d_control(
        self,
        user_prompt: str,
        expressions: List[str],
        motions: List[str],
        memory_context: Optional[List[Dict[str, Any]]] = None,
        runtime_context: Optional[Dict[str, Any]] = None,
        web_context: Optional[Dict[str, Any]] = None,
    ) -> Live2DControlPlan:
        """生成可被 Live2D 展示页消费的控制计划。"""

        request = self._build_request(
            user_prompt,
            expressions,
            motions,
            memory_context or [],
            runtime_context or {},
            web_context or {"enabled": True, "facts": [], "errors": []},
        )
        response = self._post_chat_completion(request)
        content = self._extract_content(response)
        try:
            plan = parse_live2d_control_plan(content, expressions=expressions, motions=motions)
            return normalize_action_plan_for_user_text(user_prompt, plan)
        except LlmResponseFormatError as exc:
            print(f"[LLM] 结构化回复解析失败，准备请求 LLM 修复结构：{exc}")
            try:
                repaired_content = self._repair_control_content(
                    user_prompt=user_prompt,
                    broken_content=content,
                    parse_error=str(exc),
                    expressions=expressions,
                    motions=motions,
                )
            except LlmClientError as repair_request_exc:
                print(f"[LLM] 结构修复请求失败，已降级为安全控制计划：{repair_request_exc}")
                plan = build_fallback_live2d_control_plan(content, expressions=expressions, motions=motions)
                return normalize_action_plan_for_user_text(user_prompt, plan)
            try:
                plan = parse_live2d_control_plan(repaired_content, expressions=expressions, motions=motions)
                return normalize_action_plan_for_user_text(user_prompt, plan)
            except LlmResponseFormatError as repair_exc:
                print(f"[LLM] 结构修复仍失败，已降级为安全控制计划：{repair_exc}")
                plan = build_fallback_live2d_control_plan(content, expressions=expressions, motions=motions)
                return normalize_action_plan_for_user_text(user_prompt, plan)

    def _build_request(
        self,
        user_prompt: str,
        expressions: List[str],
        motions: List[str],
        memory_context: List[Dict[str, Any]],
        runtime_context: Dict[str, Any],
        web_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """构造 DeepSeek Chat Completions 请求。"""

        system_prompt = (
            "你是虚拟陪伴机器人草莓兔兔的导演。"
            "请只输出一个 JSON 对象，不要 Markdown。"
            "JSON 字段必须包含：text, emotion, expression, motion, actions, speech, parameters。"
            "text 是适合用温柔中文女声朗读的一句话或两句话。"
            "emotion 从 happy, neutral, shy, surprised, sad, angry, thinking 中选择。"
            "expression 必须从允许表情中选择。motion 必须从允许动作中选择。"
            "actions 是数组，用来控制会持续显示的道具或姿态。"
            "action.name 可选 gaming, microphone, finger_heart, right_hand_up, left_hand_up, heart, blush, question, up, down, left, right。"
            "action.mode 可选 hold, pulse, off。hold 表示一直保持，pulse 表示短时动作，off 表示关闭同组动作。"
            "action.delay_ms 表示延迟多少毫秒后执行，默认 0，范围 0 到 30000。"
            "当用户要求一直拿着、保持、持续展示某个动作时使用 hold；唱歌或说话需要麦克风时使用 microphone hold；玩游戏或拿游戏机时使用 gaming hold。"
            "当用户要求先做 A、几秒后做 B、然后做 C 时，必须把计划拆进 actions，不能只写进 text。"
            "例如“先举起双手，5 秒后拿游戏机”应输出 right_hand_up hold、left_hand_up hold、gaming hold delay_ms=5000。"
            "实时天气等事实必须优先使用联网事实字段；没有联网事实或联网失败时，不要编造实时信息。"
            "近期记忆包含 time 和 relative_time，回答记忆或时间问题时必须使用这些具体时间，不要凭聊天顺序猜昨天、前天。"
            "如果用户要求说明你记得什么，要给出具体日期时间或相对时间。"
            "duration_ms 只对 pulse 有效，保持在 300 到 10000。"
            "speech.voice 固定为 female_zh，rate 在 0.85 到 1.15，pitch 在 1.0 到 1.35。"
            "parameters 只能包含 ParamAngleX, ParamAngleY, ParamAngleZ, "
            "ParamBodyAngleX, ParamBodyAngleY, ParamMouthForm，数值保持在合理范围。"
        )
        user_content = {
            "用户输入": user_prompt,
            "当前运行上下文": runtime_context,
            "联网事实": web_context,
            "近期记忆": memory_context[-6:],
            "允许表情": expressions,
            "允许动作": motions,
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
        return {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_content, ensure_ascii=False)},
            ],
            "temperature": 0.7,
            "max_tokens": 700,
            "response_format": {"type": "json_object"},
        }

    def _repair_control_content(
        self,
        user_prompt: str,
        broken_content: str,
        parse_error: str,
        expressions: List[str],
        motions: List[str],
    ) -> str:
        """请求 LLM 把非标准回复修复成控制协议 JSON。"""

        repair_request = self._build_repair_request(
            user_prompt=user_prompt,
            broken_content=broken_content,
            parse_error=parse_error,
            expressions=expressions,
            motions=motions,
        )
        response = self._post_chat_completion(repair_request)
        return self._extract_content(response)

    def _build_repair_request(
        self,
        user_prompt: str,
        broken_content: str,
        parse_error: str,
        expressions: List[str],
        motions: List[str],
    ) -> Dict[str, Any]:
        """构造一次严格的结构修复请求。"""

        return {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是 JSON 修复器。只输出一个合法 JSON 对象，不要 Markdown。"
                        "必须包含 text, emotion, expression, motion, actions, speech, parameters。"
                        "不得解释错误，不得输出多余文本。"
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
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
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            "temperature": 0.1,
            "max_tokens": 500,
            "response_format": {"type": "json_object"},
        }

    def _post_chat_completion(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """调用 DeepSeek API。"""

        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            url=self.base_url + "/chat/completions",
            data=body,
            method="POST",
            headers={
                "Authorization": "Bearer {0}".format(self.api_key),
                "Content-Type": "application/json",
            },
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
        """从 OpenAI 兼容响应中取出消息内容。"""

        try:
            return str(response["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError) as exc:
            raise LlmClientError("DeepSeek 响应缺少 choices[0].message.content。") from exc


def parse_live2d_control_plan(content: str, expressions: List[str], motions: List[str]) -> Live2DControlPlan:
    """解析并裁剪 LLM 返回的控制 JSON。"""

    data = _parse_json_object(content)
    expression = _pick_allowed(str(data.get("expression", "")), expressions)
    motion = _pick_allowed(str(data.get("motion", "")), motions)
    actions_data = data.get("actions") if isinstance(data.get("actions"), list) else []
    speech_data = data.get("speech") if isinstance(data.get("speech"), dict) else {}
    parameters_data = data.get("parameters") if isinstance(data.get("parameters"), dict) else {}

    return Live2DControlPlan(
        text=str(data.get("text") or "我准备好继续陪你测试啦。"),
        emotion=str(data.get("emotion") or "neutral"),
        expression=expression,
        motion=motion,
        actions=_sanitize_actions(actions_data),
        speech=SpeechControl(
            voice="female_zh",
            rate=_clamp_float(speech_data.get("rate", 1.0), 0.75, 1.25),
            pitch=_clamp_float(speech_data.get("pitch", 1.15), 0.8, 1.45),
        ),
        parameters=_sanitize_parameters(parameters_data),
    )


def build_fallback_live2d_control_plan(
    content: str,
    expressions: List[str],
    motions: List[str],
) -> Live2DControlPlan:
    """把非结构化 LLM 文本降级成仍可播报的安全控制计划。"""

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
    """用确定性规则补齐 LLM 容易漏掉的时间动作计划。"""

    text = str(user_prompt or "")
    actions = list(plan.actions)
    no_props = any(keyword in text for keyword in ["不要拿", "不拿", "别拿", "不能拿", "不要任何东西"])
    if no_props:
        actions = [action for action in actions if action.name not in {"gaming", "microphone"}]

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
    return "举" in text and any(keyword in text for keyword in ["双手", "两只手", "两个手", "双臂"])


def _mentions_gaming(text: str) -> bool:
    return any(keyword in text for keyword in ["游戏机", "打游戏", "玩游戏"])


def _mentions_microphone(text: str) -> bool:
    return any(keyword in text for keyword in ["麦克风", "话筒", "唱歌"])


def _upsert_action(
    actions: List[Live2DActionControl],
    name: str,
    mode: str,
    delay_ms: int,
) -> List[Live2DActionControl]:
    kept = [action for action in actions if action.name != name]
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
    """允许模型偶尔包一层文本，但最终必须能取出 JSON 对象。"""

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
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise LlmResponseFormatError("LLM JSON 无法解析：{0}".format(exc)) from exc
    if not isinstance(data, dict):
        raise LlmResponseFormatError("LLM JSON 顶层必须是对象。")
    return data


def _extract_fallback_text(content: str) -> str:
    """从非标准回复里尽量取出适合 TTS 播报的文本。"""

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
    """选择白名单内的值。"""

    if value in allowed:
        return value
    return allowed[0] if allowed else ""


def _sanitize_parameters(parameters: Dict[str, Any]) -> Dict[str, float]:
    """只保留 Live2D 展示页开放的安全参数。"""

    limits = {
        "ParamAngleX": (-25.0, 25.0),
        "ParamAngleY": (-20.0, 20.0),
        "ParamAngleZ": (-20.0, 20.0),
        "ParamBodyAngleX": (-15.0, 15.0),
        "ParamBodyAngleY": (-12.0, 12.0),
        "ParamMouthForm": (-1.0, 1.0),
        "ParamMouthOpenY": (0.0, 1.0),
    }
    safe: Dict[str, float] = {}
    for key, value in parameters.items():
        if key not in limits:
            continue
        min_value, max_value = limits[key]
        safe[key] = _clamp_float(value, min_value, max_value)
    return safe


def _sanitize_actions(actions: List[Any]) -> List[Live2DActionControl]:
    """裁剪 LLM 返回的动作状态控制。"""

    allowed = {
        "gaming",
        "microphone",
        "finger_heart",
        "right_hand_up",
        "left_hand_up",
        "heart",
        "blush",
        "question",
        "up",
        "down",
        "left",
        "right",
    }
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
    """读取并裁剪浮点数。"""

    try:
        number = float(value)
    except (TypeError, ValueError):
        number = min_value
    return max(min_value, min(max_value, number))
