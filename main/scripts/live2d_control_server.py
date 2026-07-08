"""Live2D 展示台本地控制服务。

浏览器只连接这个本地服务：
- `/chat`：调用 LLM，返回结构化 Live2D 控制计划。
- `/tts`：调用 sherpa-onnx 或 VoxCPM 后端，返回音频二进制。
- `/asr`：接收本机浏览器采集的 PCM，使用 VAD + SenseVoice 离线识别。

这样 API key、VoxCPM 服务地址和参考音频都留在本地服务侧，不进入前端页面。
"""

from __future__ import annotations

import base64
import binascii
import io
import hmac
import json
import math
import mimetypes
import os
import sys
import threading
import urllib.error
import urllib.request
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, unquote, urlparse


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = PROJECT_ROOT / "main" / "src"
MANIFEST_PATH = PROJECT_ROOT / "main" / "assets" / "live2d" / "Strawberry_Rabbit" / "manifest.json"
TTS_CONFIG_PATH = PROJECT_ROOT / "main" / "config" / "tts_models.json"
LIVE2D_ASSET_ROOT = (PROJECT_ROOT / "main" / "assets" / "live2d").resolve()

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from visual_companion_robot.integrations.llm_client import (
    DeepSeekLlmClient,
    Live2DControlPlan,
    LlmClientError,
    LlmContext,
    LocalLlmClient,
    SpeechControl,
)
from visual_companion_robot.integrations.web_context import build_web_context
from visual_companion_robot.brain.memory import SqliteMemoryStore, current_local_time, extract_explicit_memory_items
from visual_companion_robot.perception.offline_asr_service import OfflineAsrService
from visual_companion_robot.perception.sherpa_onnx_asr import SherpaOnnxASR
from visual_companion_robot.perception.vision_service import (
    BoardVisionService,
    VisionBusyError,
    VisionInputError,
    VisionServiceConfig,
    VisionServiceError,
)
from visual_companion_robot.runtime.realtime_websocket import is_websocket_upgrade, serve_json_websocket
from visual_companion_robot.voice.sherpa_tts import SherpaOnnxTTS
from visual_companion_robot.voice.voxcpm_cpp import VoxCpmCppConfig, VoxCpmCppSynthesizer


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
MAX_TEXT_LENGTH = 500
MAX_REQUEST_BODY_BYTES = 128 * 1024
MAX_ASR_REQUEST_BYTES = 16_000 * 2 * 30
MAX_EMOTION_REQUEST_BYTES = 2 * 1024 * 1024
MAX_VISION_REQUEST_BYTES = 2 * 1024 * 1024
MAX_ACTIVE_SPEAKER_REQUEST_BYTES = 8 * 1024 * 1024
MAX_LIVE2D_ASSET_BYTES = 24 * 1024 * 1024
EMOTION_SERVICE_URL = str(os.environ.get("VISUAL_COMPANION_EMOTION_URL") or "http://127.0.0.1:8766").rstrip("/")
SEMANTIC_VLM_SERVICE_URL = str(os.environ.get("VISUAL_COMPANION_VLM_URL") or "http://127.0.0.1:8767").rstrip("/")
DEFAULT_VISION_MODEL_PATH = PROJECT_ROOT / "main" / "models" / "yolo" / "yolov5s-640-640.rknn"
DEFAULT_POSE_MODEL_PATH = PROJECT_ROOT / "main" / "models" / "pose" / "yolov8n-pose.rknn"
VISION_MODEL_PATH = Path(os.environ.get("VISUAL_COMPANION_VISION_MODEL") or DEFAULT_VISION_MODEL_PATH)
if not VISION_MODEL_PATH.is_absolute():
    VISION_MODEL_PATH = (PROJECT_ROOT / VISION_MODEL_PATH).resolve()
MEMORY_DB_PATH = PROJECT_ROOT / "main" / "data" / "memory.sqlite3"
ASR_MODEL_ROOT = Path(os.environ.get("SHERPA_ONNX_MODEL_ROOT") or PROJECT_ROOT / "main" / "models" / "asr")
if not ASR_MODEL_ROOT.is_absolute():
    ASR_MODEL_ROOT = PROJECT_ROOT / ASR_MODEL_ROOT
ASR_SERVICE = OfflineAsrService(
    engine=SherpaOnnxASR(str(ASR_MODEL_ROOT.resolve()), num_threads=4),
)
SHERPA_TTS_ENGINE = SherpaOnnxTTS(
    str(PROJECT_ROOT / "main" / "models" / "tts" / "matcha-zh-baker"),
    model_id="matcha-zh",
    num_threads=4,
)
SHERPA_TTS_LOCK = threading.Lock()
LLM_LOCK = threading.Lock()
LLM_CLIENT: Optional[DeepSeekLlmClient | LocalLlmClient] = None
DEFAULT_LOCAL_LLM_PATH = PROJECT_ROOT / "main" / "models" / "qwen" / "Qwen2.5-1.5B-Q4_K_M.gguf"
VISION_SERVICE = BoardVisionService(
    VisionServiceConfig(
        model_path=VISION_MODEL_PATH,
        pose_model_path=Path(os.environ.get("VISUAL_COMPANION_POSE_MODEL") or DEFAULT_POSE_MODEL_PATH),
        emotion_service_url=EMOTION_SERVICE_URL,
        semantic_service_url=SEMANTIC_VLM_SERVICE_URL,
        semantic_refresh_seconds=float(os.environ.get("VISUAL_COMPANION_VLM_REFRESH_SECONDS") or 6.0),
        confidence_threshold=float(os.environ.get("VISUAL_COMPANION_VISION_CONFIDENCE") or 0.35),
    )
)


class RequestBodyError(ValueError):
    """客户端请求体不符合本地控制服务协议。"""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


def configured_device_token() -> str:
    """返回板端交互令牌；未配置时保持开发模式兼容。"""

    return str(os.environ.get("VISUAL_COMPANION_DEVICE_TOKEN") or "").strip()


def dispatch_realtime_message(payload: Dict[str, Any]) -> Dict[str, Any]:
    """执行实时通道中的单次推理，保持与现有 HTTP 返回数据一致。"""

    request_id = str(payload.get("id") or "")[:64]
    operation = str(payload.get("type") or "").strip().lower()
    try:
        if operation == "vision":
            result = VISION_SERVICE.analyze(payload.get("image"))
        elif operation == "asr":
            if payload.get("sample_rate") != 16_000:
                raise ValueError("ASR 实时消息必须声明 16000 Hz 采样率。")
            encoded_audio = payload.get("audio_pcm_base64")
            if not isinstance(encoded_audio, str) or not encoded_audio:
                raise ValueError("ASR 实时消息缺少 audio_pcm_base64。")
            try:
                pcm_bytes = base64.b64decode(encoded_audio, validate=True)
            except (binascii.Error, ValueError) as exc:
                raise ValueError("audio_pcm_base64 不是有效 Base64。") from exc
            if not pcm_bytes or len(pcm_bytes) > MAX_ASR_REQUEST_BYTES:
                raise ValueError("ASR 音频必须在 30 秒以内且不能为空。")
            result = {"ok": True, **ASR_SERVICE.transcribe_pcm16(pcm_bytes).to_dict()}
        else:
            raise ValueError("实时通道仅支持 vision 或 asr。")
        return {"id": request_id, "type": operation, "ok": True, "data": result}
    except (ValueError, VisionInputError) as exc:
        return {"id": request_id, "type": operation, "ok": False, "error": str(exc)}
    except VisionBusyError as exc:
        return {"id": request_id, "type": operation, "ok": False, "error": str(exc), "retryable": True}
    except (VisionServiceError, RuntimeError, OSError) as exc:
        return {"id": request_id, "type": operation, "ok": False, "error": str(exc)}


class RealtimeInferenceSession:
    """一条 WebSocket 连接的流式 ASR 状态。

    客户端在用户说话时持续上传小块 PCM，句尾只发送很小的
    ``asr_end`` 消息，从而把公网上传时间隐藏在说话过程中。
    """

    def __init__(self) -> None:
        self._asr_request_id = ""
        self._asr_pcm = bytearray()

    def dispatch(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        operation = str(payload.get("type") or "").strip().lower()
        if not operation.startswith("asr_"):
            return dispatch_realtime_message(payload)

        request_id = str(payload.get("id") or "")[:64]
        try:
            if operation == "asr_start":
                if payload.get("sample_rate") != 16_000:
                    raise ValueError("流式 ASR 必须使用 16000 Hz 采样率。")
                self._asr_request_id = request_id
                self._asr_pcm.clear()
                return {"id": request_id, "type": "asr_started", "ok": True}

            if not self._asr_request_id or request_id != self._asr_request_id:
                raise ValueError("流式 ASR 会话未开始或已过期。")

            if operation == "asr_chunk":
                encoded_audio = payload.get("audio_pcm_base64")
                if not isinstance(encoded_audio, str) or not encoded_audio:
                    raise ValueError("ASR 音频块为空。")
                try:
                    chunk = base64.b64decode(encoded_audio, validate=True)
                except (binascii.Error, ValueError) as exc:
                    raise ValueError("ASR 音频块不是有效 Base64。") from exc
                if len(chunk) % 2:
                    raise ValueError("ASR 音频块必须是 16 位 PCM。")
                if len(self._asr_pcm) + len(chunk) > MAX_ASR_REQUEST_BYTES:
                    self._reset_asr()
                    raise ValueError("ASR 流超过 30 秒限制。")
                self._asr_pcm.extend(chunk)
                return None

            if operation == "asr_cancel":
                self._reset_asr()
                return {"id": request_id, "type": "asr_cancelled", "ok": True}

            if operation != "asr_end":
                raise ValueError("未知的流式 ASR 消息。")
            pcm_bytes = bytes(self._asr_pcm)
            self._reset_asr()
            result = ASR_SERVICE.transcribe_pcm16(pcm_bytes)
            return {
                "id": request_id,
                "type": "asr_result",
                "ok": True,
                "data": {"ok": True, **result.to_dict()},
            }
        except (ValueError, RuntimeError, OSError) as exc:
            if operation != "asr_chunk":
                self._reset_asr()
            return {"id": request_id, "type": operation, "ok": False, "error": str(exc)}

    def _reset_asr(self) -> None:
        self._asr_request_id = ""
        self._asr_pcm.clear()


def warm_local_interaction_models() -> None:
    """后台预热常用语音模型，避免第一次交互承担模型加载时间。"""

    try:
        ASR_SERVICE.prepare()
        print("[Warmup] SenseVoice 已预热。")
    except (RuntimeError, OSError) as exc:
        print(f"[Warmup] SenseVoice 预热失败：{exc}")
    try:
        with SHERPA_TTS_LOCK:
            SHERPA_TTS_ENGINE.load()
        print("[Warmup] Matcha TTS 已预热。")
    except (RuntimeError, OSError) as exc:
        print(f"[Warmup] Matcha TTS 预热失败：{exc}")


def local_llm_path() -> Path:
    configured = Path(os.environ.get("VISUAL_COMPANION_LOCAL_LLM") or DEFAULT_LOCAL_LLM_PATH)
    return configured if configured.is_absolute() else (PROJECT_ROOT / configured).resolve()


def llm_environment_status() -> Dict[str, Any]:
    requested = str(os.environ.get("VISUAL_COMPANION_LLM_BACKEND") or "auto").strip().lower()
    cloud_ready = bool(os.environ.get("DEEPSEEK_API_KEY"))
    model_path = local_llm_path()
    local_ready = model_path.is_file()
    selected = "cloud" if requested == "cloud" or (requested == "auto" and cloud_ready) else "local"
    return {
        "backend": selected,
        "requested_backend": requested,
        "ready": cloud_ready if selected == "cloud" else local_ready,
        "model_path": str(model_path) if selected == "local" else "",
    }


def get_llm_client() -> DeepSeekLlmClient | LocalLlmClient:
    """按环境选择云端或板端 LLM，并缓存重量级本地模型。"""

    global LLM_CLIENT
    if LLM_CLIENT is not None:
        return LLM_CLIENT
    status = llm_environment_status()
    if status["backend"] == "cloud":
        LLM_CLIENT = DeepSeekLlmClient()
        return LLM_CLIENT
    model_path = Path(str(status["model_path"]))
    if not model_path.is_file():
        raise LlmClientError(f"本地 LLM 模型不存在：{model_path}")
    LLM_CLIENT = LocalLlmClient(str(model_path), n_threads=6, max_tokens=360)
    return LLM_CLIENT


def resolve_live2d_asset(raw_path: str) -> Path:
    """把 URL 中的 Live2D 相对路径限制在模型资源目录内。"""

    relative_path = unquote(raw_path).replace("\\", "/").lstrip("/")
    if not relative_path or "\x00" in relative_path:
        raise FileNotFoundError("Live2D 资源路径为空。")
    candidate = (LIVE2D_ASSET_ROOT / relative_path).resolve()
    try:
        candidate.relative_to(LIVE2D_ASSET_ROOT)
    except ValueError as exc:
        raise FileNotFoundError("Live2D 资源路径越界。") from exc
    if not candidate.is_file() or candidate.stat().st_size > MAX_LIVE2D_ASSET_BYTES:
        raise FileNotFoundError("Live2D 资源不存在或尺寸超限。")
    return candidate


def clamp(value: float, min_value: float, max_value: float) -> float:
    return max(min_value, min(max_value, value))


def sanitize_vision_context(value: Any) -> Dict[str, Any]:
    """保留板端视觉结果中对对话有用的小型可信上下文。"""

    if not isinstance(value, dict) or value.get("enabled") is False:
        return {"enabled": False}

    def safe_float(raw_value: Any, min_value: float, max_value: float, digits: int = 3) -> float:
        try:
            number = float(raw_value)
        except (TypeError, ValueError):
            number = 0.0
        return round(clamp(number, min_value, max_value), digits)

    def safe_score_map(raw_scores: Any) -> Dict[str, float]:
        if not isinstance(raw_scores, dict):
            return {}
        allowed = {"happy", "sad", "surprise", "angry", "fear", "disgust", "neutral"}
        return {
            key: safe_float(raw_scores.get(key), 0.0, 1.0)
            for key in allowed
            if key in raw_scores
        }

    raw_objects = value.get("objectsDetected", value.get("objects_detected"))
    objects = [str(item)[:48] for item in raw_objects[:12]] if isinstance(raw_objects, list) else []
    has_face = value.get("hasFace", value.get("has_face"))
    emotion_confidence = value.get("emotionConfidence", value.get("confidence"))
    full_scores = value.get("fullScores", value.get("full_scores"))
    focus_face = value.get(
        "focusPerson",
        value.get("focusFace", value.get("focus_face")),
    )
    if not isinstance(focus_face, dict):
        focus_face = {}
    active_speaker = value.get("activeSpeaker", value.get("active_speaker"))
    if not isinstance(active_speaker, dict):
        active_speaker = {}
    raw_actions = value.get("personActions", value.get("person_actions"))
    person_actions = [str(item)[:32] for item in raw_actions[:8]] if isinstance(raw_actions, list) else []
    return {
        "enabled": True,
        "status": str(value.get("status") or "")[:32],
        "timestamp": str(value.get("timestamp") or "")[:40],
        "scene_caption": str(value.get("sceneCaption", value.get("scene_caption")) or "")[:240],
        "semantic_caption": str(value.get("semanticCaption", value.get("semantic_caption")) or "")[:400],
        "semantic_status": str(value.get("semanticStatus", value.get("semantic_status")) or "")[:24],
        "person_activity": str(value.get("personActivity", value.get("person_activity")) or "")[:120],
        "person_count": int(clamp(safe_float(value.get("personCount", value.get("person_count")), 0, 20), 0, 20)),
        "objects_detected": objects,
        "has_face": bool(has_face),
        "emotion": str(value.get("emotion") or "neutral")[:32],
        "emotion_source": "ferplus-onnx",
        "emotion_confidence": safe_float(emotion_confidence, 0.0, 1.0),
        "emotion_scores": safe_score_map(full_scores),
        "focus_person": {
            "name": str(focus_face.get("name") or "")[:40],
            "profile_id": str(
                focus_face.get("profileId", focus_face.get("profile_id")) or ""
            )[:40],
            "identity_similarity": safe_float(
                focus_face.get("identitySimilarity", focus_face.get("identity_similarity")),
                0.0,
                1.0,
            ),
        },
        "active_speaker": {
            "status": str(active_speaker.get("status") or "unknown")[:20],
            "reason": str(active_speaker.get("reason") or "")[:80],
            "name": str(active_speaker.get("name") or "")[:40],
            "profile_id": str(
                active_speaker.get("profileId", active_speaker.get("profile_id")) or ""
            )[:40],
            "confidence": safe_float(active_speaker.get("confidence"), 0.0, 1.0),
        },
        "person_actions": person_actions,
        "body_state": str(value.get("bodyState", value.get("body_state")) or "unknown")[:24],
    }


VISION_QUESTION_KEYWORDS = (
    "看到什么",
    "看到了什么",
    "看见什么",
    "看见了什么",
    "看到的画面",
    "画面是什么",
    "画面里",
    "画面中",
    "摄像头里",
    "镜头里",
    "周围环境",
    "现在环境",
)


OBJECT_NAME_MAP = {
    "person": "",
    "people": "",
    "headphones": "耳机",
    "headphone": "耳机",
    "headset": "耳机",
    "microphone": "麦克风",
    "mic": "麦克风",
    "toothbrush": "牙刷",
    "laptop": "笔记本电脑",
    "cell phone": "手机",
    "phone": "手机",
    "keyboard": "键盘",
    "mouse": "鼠标",
    "chair": "椅子",
    "cup": "杯子",
    "bottle": "水瓶",
}

GENERIC_ACTIVITY_TEXTS = {"画面中有人", "有人", "person", "unknown", "未知"}


def is_visual_description_request(user_text: str) -> bool:
    """判断用户是否在询问当前摄像头画面，命中后必须优先使用板端事实。"""

    text = str(user_text or "").strip()
    if not text:
        return False
    if any(keyword in text for keyword in VISION_QUESTION_KEYWORDS):
        return True
    return ("你" in text and ("看到" in text or "看见" in text) and ("画面" in text or "什么" in text))


def _clean_visual_text(value: Any) -> str:
    return str(value or "").strip().strip("。；;，, ")


def _split_visual_items(value: str) -> List[str]:
    items: List[str] = []
    for separator in ("、", "，", ",", "和", "及"):
        value = value.replace(separator, "、")
    for item in value.split("、"):
        cleaned = _clean_visual_text(item)
        if cleaned:
            items.append(cleaned)
    return items


def _append_unique(items: List[str], value: str) -> None:
    cleaned = _clean_visual_text(value)
    if cleaned and cleaned not in items:
        items.append(cleaned)


def _localized_object_name(value: str) -> str:
    cleaned = _clean_visual_text(value)
    mapped = OBJECT_NAME_MAP.get(cleaned.lower(), cleaned)
    return _clean_visual_text(mapped)


def _semantic_fields(semantic: str) -> Tuple[Dict[str, str], List[str]]:
    fields: Dict[str, str] = {}
    free_clauses: List[str] = []
    for raw_clause in semantic.replace("。", "；").replace(";", "；").split("；"):
        clause = _clean_visual_text(raw_clause)
        if not clause:
            continue
        if "：" in clause:
            key, value = clause.split("：", 1)
        elif ":" in clause:
            key, value = clause.split(":", 1)
        else:
            free_clauses.append(clause)
            continue
        fields[_clean_visual_text(key)] = _clean_visual_text(value)
    return fields, free_clauses


def _polish_visual_description(
    semantic: str,
    scene: str,
    activity: str,
    objects: List[str],
    person_count: int,
) -> str:
    fields, free_clauses = _semantic_fields(semantic)
    subject = fields.get("人物", "")
    appearance = fields.get("外观和表情") or fields.get("外观") or fields.get("表情") or ""
    action = fields.get("动作") or _clean_visual_text(activity)
    environment = fields.get("环境", "")

    object_names: List[str] = []
    for value in _split_visual_items(fields.get("物体", "")):
        _append_unique(object_names, value)
    for value in objects[:8]:
        _append_unique(object_names, _localized_object_name(value))

    clauses: List[str] = []
    for clause in free_clauses:
        _append_unique(clauses, clause)

    if subject:
        person_phrase = f"一位{subject}" if person_count == 1 and not subject.startswith(("一", "1")) else subject
        if appearance:
            person_phrase += f"，{appearance}"
        if action and action not in GENERIC_ACTIVITY_TEXTS and action not in person_phrase:
            person_phrase += f"，正在{action}" if len(action) <= 8 and not action.startswith(("正在", "人物")) else f"，{action}"
        _append_unique(clauses, person_phrase)
    elif person_count > 0:
        _append_unique(clauses, f"画面中有{person_count}人")

    if environment:
        _append_unique(clauses, f"环境是{environment}")

    if object_names:
        _append_unique(clauses, "画面里还能看到" + "、".join(object_names[:6]))

    if not clauses and scene:
        _append_unique(clauses, scene)
    return "；".join(clauses)


def _pick_allowed(preferences: List[str], allowed: List[str]) -> str:
    for item in preferences:
        if item in allowed:
            return item
    return allowed[0] if allowed else ""


def build_direct_vision_control_plan(
    user_text: str,
    vision_context: Dict[str, Any],
    expressions: List[str],
    motions: List[str],
) -> Optional[Live2DControlPlan]:
    """视觉询问走板端事实直答，避免 LLM 在摄像头问题上编造画面。"""

    if not is_visual_description_request(user_text):
        return None

    expression = _pick_allowed(["question", "heart", "blush"], expressions)
    motion = _pick_allowed(["captain", "scene1", "idle"], motions)
    speech = SpeechControl(rate=1.0, pitch=1.12)
    parameters = {"ParamMouthForm": 0.2}

    if not vision_context.get("enabled") or vision_context.get("status") == "stale":
        return Live2DControlPlan(
            text="主人，我现在还没有拿到稳定的摄像头画面；请先确认摄像头已经打开并等我完成一次视觉更新。",
            emotion="thinking",
            expression=expression,
            motion=motion,
            speech=speech,
            parameters=parameters,
        )

    semantic = str(vision_context.get("semantic_caption") or "").strip()
    scene = str(vision_context.get("scene_caption") or "").strip()
    activity = str(vision_context.get("person_activity") or "").strip()
    objects = [str(item).strip() for item in vision_context.get("objects_detected") or [] if str(item).strip()]
    person_count = int(vision_context.get("person_count") or 0)

    details = _polish_visual_description(semantic, scene, activity, objects, person_count)
    if not details:
        text = "主人，我拿到了摄像头画面，但当前结构化视觉结果还不够明确；请稍等下一帧更新。"
    else:
        text = "主人，我看到" + details + "。"
    return Live2DControlPlan(
        text=text[:220],
        emotion="thinking",
        expression=expression,
        motion=motion,
        speech=speech,
        parameters=parameters,
    )


def load_manifest() -> Tuple[list[str], list[str]]:
    with MANIFEST_PATH.open("r", encoding="utf-8") as handle:
        manifest = json.load(handle)
    expressions = list((manifest.get("expressions") or {}).keys())
    motions = list((manifest.get("motions") or {}).keys())
    if not expressions or not motions:
        raise RuntimeError("Live2D manifest 缺少 expressions 或 motions。")
    return expressions, motions


def load_tts_config() -> Dict[str, Any]:
    if not TTS_CONFIG_PATH.exists():
        raise RuntimeError(f"缺少 TTS 配置文件：{TTS_CONFIG_PATH}")
    with TTS_CONFIG_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def public_tts_config() -> Dict[str, Any]:
    """返回前端需要的音色元数据，避免暴露板端模型路径和内部端点。"""

    config = load_tts_config()
    public_models: Dict[str, Dict[str, Any]] = {}
    for voice_id, raw_voice in (config.get("models") or {}).items():
        if not isinstance(raw_voice, dict):
            continue
        public_models[str(voice_id)] = {
            key: raw_voice[key]
            for key in ("display_name", "description", "backend")
            if key in raw_voice
        }
    public_references: Dict[str, Dict[str, Any]] = {}
    for reference_id, raw_reference in (config.get("references") or {}).items():
        if not isinstance(raw_reference, dict):
            continue
        public_references[str(reference_id)] = {
            key: raw_reference[key]
            for key in ("display_name", "prompt_text", "content_type")
            if key in raw_reference
        }
    return {
        "active": config.get("active"),
        "active_reference": config.get("active_reference"),
        "models": public_models,
        "references": public_references,
    }


def proxy_emotion_request(method: str, path: str, body: bytes = b"") -> Tuple[int, bytes, str]:
    """通过本机回环地址调用 FER+ 服务，对公网仅暴露统一网关。"""

    headers = {"Content-Type": "application/json"} if body else {}
    request = urllib.request.Request(
        f"{EMOTION_SERVICE_URL}{path}",
        data=body if body else None,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status, response.read(), response.headers.get("Content-Type") or "application/json"
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), exc.headers.get("Content-Type") or "application/json"
    except urllib.error.URLError as exc:
        raise RuntimeError(f"FER+ 服务不可用：{exc.reason}") from exc


def select_voice_config(voice_id: str) -> Tuple[str, Dict[str, Any]]:
    config = load_tts_config()
    models = config.get("models") or {}
    active = voice_id or config.get("active")
    if not active:
        raise RuntimeError("TTS 配置缺少 active 音色。")
    voice_config = models.get(active)
    if not isinstance(voice_config, dict):
        raise RuntimeError(f"TTS 音色未配置：{active}")
    return active, voice_config


def select_reference_config(reference_id: str) -> Tuple[str, Dict[str, Any]]:
    """读取参考音频配置，供 VoxCPM 推理使用。"""

    config = load_tts_config()
    references = config.get("references") or {}
    active = reference_id or config.get("active_reference")
    if not active:
        raise RuntimeError("TTS 配置缺少 active_reference。")
    reference_config = references.get(active)
    if not isinstance(reference_config, dict):
        raise RuntimeError(f"TTS 参考音频未配置：{active}")
    return active, reference_config


def build_runtime_voice_config(
    voice_config: Dict[str, Any],
    reference_id: str,
    prompt_text: Optional[str],
) -> Dict[str, Any]:
    """把用户选择的参考音频和可编辑文本合并到当前 TTS 后端配置。"""

    runtime_config = dict(voice_config)
    if runtime_config.get("backend") == "sherpa_onnx":
        return runtime_config
    selected_reference, reference_config = select_reference_config(reference_id)
    runtime_config["reference_id"] = selected_reference
    runtime_config["ref_audio_path"] = reference_config.get("audio_path", "")
    selected_prompt = reference_config.get("prompt_text") if prompt_text is None else prompt_text
    runtime_config["prompt_text"] = str(selected_prompt or "").strip()
    return runtime_config


def resolve_existing_path(raw_path: str, label: str) -> Path:
    path_text = str(raw_path or "").strip()
    if not path_text:
        raise RuntimeError(f"VoxCPM 缺少{label}配置。")
    path = Path(path_text)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    path = path.resolve()
    if not path.exists():
        raise RuntimeError(f"{label}不存在：{path_text}")
    return path


def detect_audio_content_type(audio: bytes, fallback: str) -> str:
    """按文件头修正音频 MIME，避免浏览器因错误类型拒播。"""

    if audio.startswith(b"RIFF") and audio[8:12] == b"WAVE":
        return "audio/wav"
    if audio.startswith(b"ID3") or audio[:2] in {b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"}:
        return "audio/mpeg"
    return fallback or "application/octet-stream"


def probe_voxcpm_backend(voice_config: Dict[str, Any]) -> Dict[str, Any]:
    """检查当前可选的板端 TTS 后端。"""

    backend = str(voice_config.get("backend") or "")
    if backend == "sherpa_onnx":
        return SHERPA_TTS_ENGINE.environment_status()
    if backend == "voxcpm_cpp_local":
        try:
            return VoxCpmCppSynthesizer(VoxCpmCppConfig.from_mapping(voice_config)).prepare()
        except Exception as exc:
            return {"ok": False, "backend": backend, "message": str(exc)}
    return {"ok": False, "backend": backend, "message": f"暂不支持的 TTS backend：{backend}"}


def synthesize_voxcpm_cpp(text: str, rate: float, voice_config: Dict[str, Any]) -> Tuple[bytes, str]:
    """调用 ELF2 回环地址上的 VoxCPM.cpp 量化服务。"""

    with SHERPA_TTS_LOCK:
        SHERPA_TTS_ENGINE.release()
    ref_audio = resolve_existing_path(str(voice_config.get("ref_audio_path") or ""), "VoxCPM 参考音频文件")
    synthesizer = VoxCpmCppSynthesizer(VoxCpmCppConfig.from_mapping(voice_config))
    return synthesizer.synthesize(
        text=text,
        rate=rate,
        reference_id=str(voice_config.get("reference_id") or ""),
        reference_audio_path=str(ref_audio),
        prompt_text=str(voice_config.get("prompt_text") or ""),
    )


def synthesize_sherpa_onnx(text: str, rate: float, voice_config: Dict[str, Any]) -> Tuple[bytes, str]:
    """使用缓存的 Matcha/Vocos 本地模型并返回 WAV。"""

    with SHERPA_TTS_LOCK:
        SHERPA_TTS_ENGINE.load()
        samples, sample_rate = SHERPA_TTS_ENGINE.synthesize(
            text,
            sid=int(voice_config.get("speaker_id") or 0),
            speed=clamp(float(rate), 0.85, 1.35),
        )
    pcm = (samples.clip(-1.0, 1.0) * 32767.0).astype("<i2").tobytes()
    output = io.BytesIO()
    with wave.open(output, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm)
    return output.getvalue(), "audio/wav"


def synthesize_with_tts_backend(
    text: str,
    rate: float,
    voice_id: str,
    reference_id: str = "",
    prompt_text: Optional[str] = None,
) -> Tuple[bytes, str]:
    selected_voice, voice_config = select_voice_config(voice_id)
    voice_config = build_runtime_voice_config(voice_config, reference_id, prompt_text)
    backend = voice_config.get("backend") or "sherpa_onnx"
    if backend == "sherpa_onnx":
        audio, content_type = synthesize_sherpa_onnx(text, rate, voice_config)
        print(f"[TTS] voice={selected_voice} backend={backend}")
        return audio, content_type
    if backend == "voxcpm_cpp_local":
        audio, content_type = synthesize_voxcpm_cpp(text, rate, voice_config)
        print(f"[TTS] voice={selected_voice} backend={backend}")
        return audio, content_type
    raise RuntimeError(f"暂不支持的 TTS backend：{backend}")


def activate_tts_runtime(voice_id: str) -> Dict[str, Any]:
    """根据前端选中的语音后端启动或释放本地推理资源。"""

    selected_voice, voice_config = select_voice_config(voice_id)
    backend = str(voice_config.get("backend") or "sherpa_onnx")
    if backend == "sherpa_onnx":
        with SHERPA_TTS_LOCK:
            SHERPA_TTS_ENGINE.load()
            status = SHERPA_TTS_ENGINE.environment_status()
        status.update({"voice": selected_voice, "action": "prepare_local_model"})
        return status
    if backend == "voxcpm_cpp_local":
        try:
            status = VoxCpmCppSynthesizer(VoxCpmCppConfig.from_mapping(voice_config)).prepare()
        except Exception as exc:
            status = {"ok": False, "backend": backend, "message": str(exc)}
        status.update({"voice": selected_voice, "action": "prepare_board_runtime"})
        if not status.get("ok"):
            return status
        with SHERPA_TTS_LOCK:
            status["released_sherpa"] = SHERPA_TTS_ENGINE.release()
        return status
    raise RuntimeError(f"暂不支持的 TTS backend：{backend}")


class ControlHandler(BaseHTTPRequestHandler):
    """Live2D 控制服务 HTTP 处理器。

    使用消息分发表（dict dispatch）替代 if/elif 链，参考 Open-LLM-VTuber 的
    WebSocket handler 模式。新增路由只需在分发表中添加一行。
    """

    server_version = "VisualCompanionControl/0.7"

    # ---- GET 路由分发表 ----
    _GET_ROUTES: Dict[str, str] = {
        "/health": "handle_health",
        "/voices": "handle_voices",
        "/tts-health": "handle_tts_health",
        "/asr-health": "handle_asr_health",
        "/emotion-health": "handle_emotion_health",
        "/face-profiles": "handle_face_profiles",
        "/vision-health": "handle_vision_health",
        "/reference-audio": "handle_reference_audio",
    }

    # ---- POST 路由分发表 ----
    _POST_ROUTES: Dict[str, str] = {
        "/chat": "handle_chat",
        "/tts": "handle_tts",
        "/tts-runtime": "handle_tts_runtime",
        "/asr": "handle_asr",
        "/emotion": "handle_emotion",
        "/face-enroll": "handle_face_enroll",
        "/active-speaker": "handle_active_speaker",
        "/vision": "handle_vision",
    }

    def do_OPTIONS(self) -> None:
        if not self.is_request_origin_allowed():
            self.send_json({"error": "Origin 不允许访问本地控制服务。"}, status=403)
            return
        self.send_response(204)
        self.send_cors_headers()
        self.end_headers()

    def do_GET(self) -> None:
        if not self.is_request_origin_allowed():
            self.send_json({"error": "Origin 不允许访问本地控制服务。"}, status=403)
            return
        parsed_url = urlparse(self.path)
        path = parsed_url.path
        if path == "/realtime":
            if not self.is_device_authenticated():
                self.send_json({"error": "设备令牌无效。"}, status=401)
                return
            if not is_websocket_upgrade(self.headers):
                self.send_json({"error": "实时接口需要 WebSocket Upgrade。"}, status=426)
                return
            serve_json_websocket(self, RealtimeInferenceSession().dispatch)
            return
        if path.startswith("/live2d/"):
            self.handle_live2d_asset(path.removeprefix("/live2d/"))
            return
        handler_name = self._GET_ROUTES.get(path)
        if handler_name:
            if path in {"/reference-audio", "/face-profiles"} and not self.is_device_authenticated():
                self.send_json({"error": "设备令牌无效。"}, status=401)
                return
            getattr(self, handler_name)(parsed_url.query)
        else:
            self.send_json({"error": "Not found"}, status=404)

    def do_POST(self) -> None:
        if not self.is_request_origin_allowed():
            self.send_json({"error": "Origin 不允许访问本地控制服务。"}, status=403)
            return
        path = urlparse(self.path).path
        handler_name = self._POST_ROUTES.get(path)
        if handler_name:
            if not self.is_device_authenticated():
                self.send_json({"error": "设备令牌无效。"}, status=401)
                return
            try:
                getattr(self, handler_name)()
            except RequestBodyError as exc:
                self.send_json({"error": str(exc)}, status=exc.status)
        else:
            self.send_json({"error": "Not found"}, status=404)

    def handle_health(self, _raw_query: str) -> None:
        self.send_json(
            {
                "ok": True,
                "service": "visual-companion-control",
                "version": self.server_version,
                "authentication_required": bool(configured_device_token()),
                "llm": llm_environment_status(),
            }
        )

    def handle_live2d_asset(self, relative_path: str) -> None:
        try:
            asset_path = resolve_live2d_asset(relative_path)
            content_type = mimetypes.guess_type(str(asset_path))[0] or "application/octet-stream"
            size = asset_path.stat().st_size
            self.send_response(200)
            self.send_cors_headers()
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(size))
            self.send_header("Cache-Control", "public, max-age=3600")
            self.end_headers()
            with asset_path.open("rb") as handle:
                while chunk := handle.read(64 * 1024):
                    self.wfile.write(chunk)
        except (FileNotFoundError, OSError):
            self.send_json({"error": "Live2D 资源不存在。"}, status=404)

    def handle_voices(self, _raw_query: str) -> None:
        try:
            self.send_json(public_tts_config())
        except (OSError, RuntimeError, json.JSONDecodeError) as exc:
            self.send_json({"error": str(exc)}, status=500)

    def handle_asr_health(self, _raw_query: str) -> None:
        self.send_json(ASR_SERVICE.health())

    def handle_emotion_health(self, _raw_query: str) -> None:
        self.proxy_emotion("GET", "/health")

    def handle_face_profiles(self, _raw_query: str) -> None:
        self.proxy_emotion("GET", "/face-profiles")

    def handle_vision_health(self, _raw_query: str) -> None:
        try:
            self.send_json(VISION_SERVICE.health())
        except VisionServiceError as exc:
            self.send_json({"ok": False, "error": str(exc)}, status=503)

    def handle_emotion(self) -> None:
        content_type = str(self.headers.get("Content-Type") or "").lower()
        if not content_type.startswith("application/json"):
            raise RequestBodyError("情绪识别请求必须使用 application/json 内容类型。")
        body = self.read_request_body(MAX_EMOTION_REQUEST_BYTES, "2 MiB")
        self.proxy_emotion("POST", "/emotion", body)

    def handle_face_enroll(self) -> None:
        content_type = str(self.headers.get("Content-Type") or "").lower()
        if not content_type.startswith("application/json"):
            raise RequestBodyError("身份登记请求必须使用 application/json 内容类型。")
        body = self.read_request_body(MAX_EMOTION_REQUEST_BYTES, "2 MiB")
        self.proxy_emotion("POST", "/face-enroll", body)

    def handle_active_speaker(self) -> None:
        content_type = str(self.headers.get("Content-Type") or "").lower()
        if not content_type.startswith("application/json"):
            raise RequestBodyError("主动说话人请求必须使用 application/json 内容类型。")
        body = self.read_request_body(MAX_ACTIVE_SPEAKER_REQUEST_BYTES, "8 MiB")
        self.proxy_emotion("POST", "/active-speaker", body)

    def handle_vision(self) -> None:
        content_type = str(self.headers.get("Content-Type") or "").lower()
        if not content_type.startswith("application/json"):
            raise RequestBodyError("视觉请求必须使用 application/json 内容类型。")
        payload = self.read_json(MAX_VISION_REQUEST_BYTES, "2 MiB")
        try:
            self.send_json(VISION_SERVICE.analyze(payload.get("image")))
        except VisionInputError as exc:
            self.send_json({"error": str(exc)}, status=400)
        except VisionBusyError as exc:
            self.send_json({"error": str(exc)}, status=429)
        except VisionServiceError as exc:
            self.send_json({"error": str(exc)}, status=503)

    def proxy_emotion(self, method: str, path: str, body: bytes = b"") -> None:
        try:
            status, payload, content_type = proxy_emotion_request(method, path, body)
            self.send_response(status)
            self.send_cors_headers()
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)
        except RuntimeError as exc:
            self.send_json({"error": str(exc)}, status=503)

    def handle_chat(self) -> None:
        try:
            payload = self.read_json()
            text = str(payload.get("text", "")).strip()
            if not text:
                self.send_json({"error": "text 不能为空。"}, status=400)
                return
            requested_rate = payload.get("rate")
            parsed_rate = None if requested_rate is None else self.parse_number(requested_rate, "rate")
            expressions, motions = load_manifest()
            memory_store = SqliteMemoryStore(MEMORY_DB_PATH)
            for memory_item in extract_explicit_memory_items(text):
                memory_store.add_item(memory_item)
            now = current_local_time()
            memory_context = memory_store.recent_turns(limit=6)
            long_term_memory = memory_store.recent_items(limit=12)
            vision_context = sanitize_vision_context(payload.get("vision"))
            direct_plan = build_direct_vision_control_plan(
                text[:MAX_TEXT_LENGTH],
                vision_context,
                expressions,
                motions,
            )
            if direct_plan is not None:
                if parsed_rate is not None:
                    direct_plan.speech.rate = clamp(parsed_rate, 0.85, 1.35)
                memory_store.append_turn(text[:MAX_TEXT_LENGTH], direct_plan.text)
                self.send_json(direct_plan.to_dict())
                return
            web_context = build_web_context(text[:MAX_TEXT_LENGTH], now=now)
            context = LlmContext(
                user_prompt=text[:MAX_TEXT_LENGTH],
                expressions=expressions,
                motions=motions,
                memory_context=[turn.to_prompt_dict(now=now) for turn in memory_context],
                long_term_memory=[item.to_prompt_dict() for item in long_term_memory],
                runtime_context={
                    "current_time": now.isoformat(timespec="seconds"),
                    "timezone": now.tzname() or "",
                    "internet_enabled": True,
                    "vision": vision_context,
                },
                web_context=web_context,
            )
            with LLM_LOCK:
                plan = get_llm_client().generate_live2d_control(context)
            if parsed_rate is not None:
                plan.speech.rate = clamp(parsed_rate, 0.85, 1.35)
            memory_store.append_turn(text[:MAX_TEXT_LENGTH], plan.text)
            self.send_json(plan.to_dict())
        except (LlmClientError, RuntimeError, OSError) as exc:
            self.send_json({"error": str(exc)}, status=500)

    def handle_tts(self) -> None:
        try:
            payload = self.read_json()
            text = str(payload.get("text", "")).strip()
            if not text:
                self.send_json({"error": "text 不能为空。"}, status=400)
                return
            rate = self.parse_number(payload.get("rate") or 1.0, "rate")
            voice = str(payload.get("voice") or "")
            reference = str(payload.get("reference") or "")
            prompt_text_payload = payload.get("promptText", payload.get("prompt_text"))
            prompt_text = None if prompt_text_payload is None else str(prompt_text_payload)
            audio, content_type = synthesize_with_tts_backend(text[:MAX_TEXT_LENGTH], rate, voice, reference, prompt_text)
            if not audio:
                self.send_json({"error": "TTS 后端返回了空音频。"}, status=502)
                return
            self.send_response(200)
            self.send_cors_headers()
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(audio)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(audio)
        except (RuntimeError, OSError) as exc:
            self.send_json({"error": str(exc)}, status=500)

    def handle_reference_audio(self, raw_query: str) -> None:
        try:
            query = parse_qs(raw_query)
            reference_id = str((query.get("id") or [""])[0])
            _, reference_config = select_reference_config(reference_id)
            audio_file = resolve_existing_path(reference_config.get("audio_path", ""), "参考音频文件")
            audio = audio_file.read_bytes()
            content_type = detect_audio_content_type(
                audio,
                str(reference_config.get("content_type") or mimetypes.guess_type(str(audio_file))[0] or "audio/mpeg"),
            )
            self.send_response(200)
            self.send_cors_headers()
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(audio)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(audio)
        except (RuntimeError, OSError) as exc:
            self.send_json({"error": str(exc)}, status=404)

    def handle_tts_health(self, raw_query: str) -> None:
        query = parse_qs(raw_query)
        voice_id = str((query.get("voice") or [""])[0])
        try:
            selected_voice, voice_config = select_voice_config(voice_id)
            health = probe_voxcpm_backend(voice_config)
            health["voice"] = selected_voice
            self.send_json(health)
        except (RuntimeError, OSError) as exc:
            self.send_json({"ok": False, "error": str(exc)}, status=200)

    def handle_tts_runtime(self) -> None:
        try:
            payload = self.read_json()
            voice_id = str(payload.get("voice") or "")
            self.send_json(activate_tts_runtime(voice_id))
        except (RuntimeError, OSError) as exc:
            self.send_json({"ok": False, "error": str(exc)}, status=200)

    def handle_asr(self) -> None:
        content_type = str(self.headers.get("Content-Type") or "").lower()
        if not content_type.startswith("audio/pcm"):
            raise RequestBodyError("ASR 请求必须使用 audio/pcm 内容类型。")
        if "rate=16000" not in content_type.replace(" ", ""):
            raise RequestBodyError("ASR 请求必须声明 16000 Hz 采样率。")
        pcm_bytes = self.read_request_body(MAX_ASR_REQUEST_BYTES, "30 秒音频")
        try:
            result = ASR_SERVICE.transcribe_pcm16(pcm_bytes)
            self.send_json({"ok": True, **result.to_dict()})
        except ValueError as exc:
            raise RequestBodyError(str(exc)) from exc
        except (RuntimeError, OSError) as exc:
            self.send_json({"ok": False, "error": str(exc)}, status=503)

    def read_json(
        self,
        max_bytes: int = MAX_REQUEST_BODY_BYTES,
        limit_label: str = "128 KiB",
    ) -> Dict[str, Any]:
        raw = self.read_request_body(max_bytes, limit_label)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RequestBodyError("请求体必须是有效的 UTF-8 JSON 对象。") from exc
        if not isinstance(payload, dict):
            raise RequestBodyError("请求体必须是 JSON 对象。")
        return payload

    def read_request_body(self, max_bytes: int, limit_label: str) -> bytes:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError as exc:
            raise RequestBodyError("Content-Length 无效。") from exc
        if length <= 0:
            raise RequestBodyError("请求体不能为空。")
        if length > max_bytes:
            raise RequestBodyError(f"请求体超过 {limit_label} 限制。", status=413)

        raw = self.rfile.read(length)
        if len(raw) != length:
            raise RequestBodyError("请求体读取不完整。")
        return raw

    @staticmethod
    def parse_number(value: Any, field_name: str) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise RequestBodyError(f"{field_name} 必须是数字。") from exc
        if not math.isfinite(number):
            raise RequestBodyError(f"{field_name} 必须是有限数字。")
        return number

    def send_json(self, payload: Dict[str, Any], status: int = 200) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_cors_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def send_cors_headers(self) -> None:
        origin = str(self.headers.get("Origin") or "").strip()
        if origin and self.is_request_origin_allowed():
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Device-Token")

    def is_request_origin_allowed(self) -> bool:
        origin = str(self.headers.get("Origin") or "").strip()
        if not origin:
            return True
        parsed = urlparse(origin)
        hostname = str(parsed.hostname or "").lower()
        if parsed.scheme in {"http", "https"} and hostname in {"127.0.0.1", "localhost", "::1"}:
            return True
        public_host = str(os.environ.get("VISUAL_COMPANION_PUBLIC_HOST") or "robot.veyralux.org").lower()
        return parsed.scheme == "https" and hostname in {"servicewechat.com", public_host}

    def is_device_authenticated(self) -> bool:
        expected = configured_device_token()
        if not expected:
            return True
        supplied = str(self.headers.get("X-Device-Token") or "")
        return hmac.compare_digest(supplied, expected)

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[Control] {self.address_string()} - {format % args}")


def main() -> None:
    host = os.environ.get("LIVE2D_CONTROL_HOST", DEFAULT_HOST)
    port = int(os.environ.get("LIVE2D_CONTROL_PORT", DEFAULT_PORT))
    VISION_SERVICE.load()
    server = ThreadingHTTPServer((host, port), ControlHandler)
    threading.Thread(target=warm_local_interaction_models, name="speech-model-warmup", daemon=True).start()
    print(f"Live2D 控制服务已启动：http://{host}:{port}/health")
    try:
        server.serve_forever()
    finally:
        server.server_close()
        VISION_SERVICE.close()


if __name__ == "__main__":
    main()
