"""Live2D 展示台本地控制服务。

浏览器只连接这个本地服务：
- `/chat`：调用 LLM，返回结构化 Live2D 控制计划。
- `/tts`：代理 VoxCPM 公网 API 或本地推理接口，返回音频二进制。

这样 API key、VoxCPM 服务地址和参考音频都留在本地服务侧，不进入前端页面。
"""

from __future__ import annotations

import json
import mimetypes
import os
import sys
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.parse import parse_qs, urlparse


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = PROJECT_ROOT / "main" / "src"
MANIFEST_PATH = PROJECT_ROOT / "main" / "assets" / "live2d" / "Strawberry_Rabbit" / "manifest.json"
TTS_CONFIG_PATH = PROJECT_ROOT / "main" / "config" / "tts_models.json"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from visual_companion_robot.integrations.llm_client import DeepSeekLlmClient, LlmClientError
from visual_companion_robot.integrations.web_context import build_web_context
from visual_companion_robot.brain.memory import SqliteMemoryStore, current_local_time
from visual_companion_robot.voice.voxcpm_local import (
    VoxCpmLocalConfig,
    VoxCpmLocalSynthesizer,
    release_cached_models,
)


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
DEFAULT_VOXCPM_LOCAL_URL = "http://127.0.0.1:7860"
MAX_TEXT_LENGTH = 500
MEMORY_DB_PATH = PROJECT_ROOT / "main" / "data" / "memory.sqlite3"


def clamp(value: float, min_value: float, max_value: float) -> float:
    return max(min_value, min(max_value, value))


def sanitize_vision_context(value: Any) -> Dict[str, Any]:
    """保留浏览器视觉模块上报给 LLM 的小型可信上下文。"""

    if not isinstance(value, dict):
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

    head_pose = value.get("headPose") if isinstance(value.get("headPose"), dict) else {}
    mouth = value.get("mouth") if isinstance(value.get("mouth"), dict) else {}
    eyes = value.get("eyes") if isinstance(value.get("eyes"), dict) else {}
    return {
        "enabled": True,
        "status": str(value.get("status") or "")[:32],
        "has_face": bool(value.get("hasFace")),
        "emotion": str(value.get("emotion") or "neutral")[:32],
        "emotion_source": str(value.get("emotionSource") or "")[:32],
        "emotion_confidence": safe_float(value.get("emotionConfidence"), 0.0, 1.0),
        "emotion_scores": safe_score_map(value.get("fullScores")),
        "head_pose": {
            "angle_x": safe_float(head_pose.get("angleX"), -45.0, 45.0, digits=1),
            "angle_y": safe_float(head_pose.get("angleY"), -45.0, 45.0, digits=1),
            "body_angle_z": safe_float(head_pose.get("bodyAngleZ"), -45.0, 45.0, digits=1),
        },
        "mouth": {
            "smile": safe_float(mouth.get("smile"), 0.0, 1.0),
            "open": safe_float(mouth.get("open"), 0.0, 1.0),
        },
        "eyes": {
            "open": safe_float(eyes.get("open"), 0.0, 1.0),
        },
    }


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

    _, reference_config = select_reference_config(reference_id)
    runtime_config = dict(voice_config)
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


def build_gradio_file_data(server_path: str, source_file: Path) -> Dict[str, Any]:
    """构造 Gradio FileData，供 Space 的文件输入组件使用。"""

    return {
        "path": server_path,
        "orig_name": source_file.name,
        "mime_type": mimetypes.guess_type(str(source_file))[0] or "application/octet-stream",
        "meta": {"_type": "gradio.FileData"},
    }


def upload_file_to_gradio(space_url: str, source_file: Path) -> str:
    """上传本地参考音频到 Gradio Space，返回服务端临时路径。"""

    boundary = "----VisualCompanionRobotBoundary"
    content_type = mimetypes.guess_type(str(source_file))[0] or "application/octet-stream"
    header = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="files"; filename="{source_file.name}"\r\n'
        f"Content-Type: {content_type}\r\n\r\n"
    ).encode("utf-8")
    footer = f"\r\n--{boundary}--\r\n".encode("utf-8")
    body = header + source_file.read_bytes() + footer
    request = urllib.request.Request(
        url=f"{space_url}/gradio_api/upload",
        data=body,
        method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        upload_result = json.loads(response.read().decode("utf-8"))
    if isinstance(upload_result, list) and upload_result:
        upload_result = upload_result[0]
    server_path = str(upload_result or "")
    if not server_path:
        raise RuntimeError("Hugging Face Space 参考音频上传失败。")
    return server_path


def build_voxcpm_hf_space_payload(
    text: str,
    rate: float,
    voice_config: Dict[str, Any],
    reference_audio: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    control = str(voice_config.get("control_instruction") or "年轻女性，温柔自然，语气友好").strip()
    if rate >= 1.08 and "语速" not in control:
        control = f"{control}，语速稍快"
    elif rate <= 0.92 and "语速" not in control:
        control = f"{control}，语速稍慢"
    prompt_text = str(voice_config.get("prompt_text") or "").strip()
    use_prompt_text = bool(reference_audio and prompt_text)
    return {
        "data": [
            text,
            "" if use_prompt_text else control,
            reference_audio,
            use_prompt_text,
            prompt_text if use_prompt_text else "",
            float(voice_config.get("cfg_value", 2.0)),
            bool(voice_config.get("do_normalize", True)),
            bool(voice_config.get("denoise", False)),
        ]
    }


def parse_gradio_sse_data(raw_text: str) -> Any:
    last_data = None
    for block in raw_text.split("\n\n"):
        event_name = ""
        data_text = ""
        for line in block.splitlines():
            if line.startswith("event:"):
                event_name = line.split(":", 1)[1].strip()
            if line.startswith("data:"):
                data_text = line.split(":", 1)[1].strip()
        if not data_text:
            continue
        last_data = json.loads(data_text)
        if event_name == "complete":
            return last_data
    if last_data is not None:
        return last_data
    raise RuntimeError("Hugging Face Space 没有返回 Gradio data 事件。")


def resolve_voxcpm_base_url(voice_config: Dict[str, Any]) -> str:
    backend = str(voice_config.get("backend") or "")
    if backend in {"voxcpm_local", "voxcpm_local_gradio"}:
        return str(os.environ.get("VOXCPM_LOCAL_URL") or voice_config.get("endpoint") or DEFAULT_VOXCPM_LOCAL_URL).rstrip("/")
    return str(voice_config.get("space_url") or "https://openbmb-voxcpm-demo.hf.space").rstrip("/")


def probe_voxcpm_backend(voice_config: Dict[str, Any], timeout_sec: int = 5) -> Dict[str, Any]:
    """检查 VoxCPM Gradio 后端是否可访问。

    先尝试 /gradio_api/info 端点，404 时回退探测根 URL。
    网络不可达返回 {"ok": False, ...} 而非抛异常，便于前端展示。
    """

    backend = str(voice_config.get("backend") or "")
    if backend == "voxcpm_project_local":
        config = VoxCpmLocalConfig.from_mapping(voice_config, PROJECT_ROOT)
        return VoxCpmLocalSynthesizer.environment_status(config)

    base_url = resolve_voxcpm_base_url(voice_config)
    if backend not in {"voxcpm_hf_space", "voxcpm_local", "voxcpm_local_gradio"}:
        return {"ok": False, "backend": backend, "base_url": base_url, "message": f"暂不支持的 VoxCPM backend：{backend}"}

    probe_url = f"{base_url}/gradio_api/info"
    try:
        with urllib.request.urlopen(probe_url, timeout=timeout_sec) as response:
            response.read(256)
        return {"ok": True, "backend": backend, "base_url": base_url, "message": "VoxCPM Gradio 服务可访问。"}
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            try:
                with urllib.request.urlopen(base_url, timeout=timeout_sec) as response:
                    response.read(256)
                return {"ok": True, "backend": backend, "base_url": base_url, "message": "VoxCPM Gradio 页面可访问。"}
            except urllib.error.URLError as root_exc:
                return {
                    "ok": False,
                    "backend": backend,
                    "base_url": base_url,
                    "message": f"VoxCPM Gradio 根页面连接失败：{root_exc}",
                }
        return {
            "ok": False,
            "backend": backend,
            "base_url": base_url,
            "message": f"VoxCPM Gradio 服务 HTTP {exc.code}。",
        }
    except urllib.error.URLError as exc:
        hint = "请先启动本地 VoxCPM Gradio 桥接服务。" if backend in {"voxcpm_local", "voxcpm_local_gradio"} else "请稍后重试公网 Space。"
        return {
            "ok": False,
            "backend": backend,
            "base_url": base_url,
            "message": f"无法连接 VoxCPM 服务：{exc.reason}。{hint}",
        }


def ensure_local_gradio_backend_ready(voice_config: Dict[str, Any]) -> None:
    """本地 Gradio 桥接生成前先给出明确可操作的错误。"""

    if voice_config.get("backend") not in {"voxcpm_local", "voxcpm_local_gradio"}:
        return
    health = probe_voxcpm_backend(voice_config)
    if not health["ok"]:
        raise RuntimeError(f"VoxCPM 本地推理服务未就绪：{health['message']}")


def build_voxcpm_gradio_payload(
    text: str,
    rate: float,
    voice_config: Dict[str, Any],
    reference_audio: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """构造 VoxCPM Gradio 队列请求，兼容公网 Space 与本地 app.py。"""

    payload = build_voxcpm_hf_space_payload(text, rate, voice_config, reference_audio=reference_audio)
    if "inference_timesteps" in voice_config:
        payload["data"].append(int(voice_config.get("inference_timesteps") or 10))
    return payload


def synthesize_voxcpm_gradio(text: str, rate: float, voice_config: Dict[str, Any]) -> Tuple[bytes, str]:
    """通过 Gradio API 调用 VoxCPM 合成语音。

    流程：检查后端可用 → 上传参考音频 → 提交队列 → 等待 SSE 完成 → 下载音频。
    整个流程已包裹 try-except，网络/API 错误会抛出 RuntimeError。
    """

    base_url = resolve_voxcpm_base_url(voice_config)
    api_name = str(voice_config.get("api_name") or "generate").strip().strip("/")
    try:
        ensure_local_gradio_backend_ready(voice_config)
        reference_audio = None
        ref_audio_path = str(voice_config.get("ref_audio_path") or "").strip()
        if ref_audio_path:
            ref_audio_file = resolve_existing_path(ref_audio_path, "VoxCPM 参考音频文件")
            server_path = upload_file_to_gradio(base_url, ref_audio_file)
            reference_audio = build_gradio_file_data(server_path, ref_audio_file)
        payload = build_voxcpm_gradio_payload(text, rate, voice_config, reference_audio=reference_audio)
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        submit_request = urllib.request.Request(
            url=f"{base_url}/gradio_api/call/{api_name}",
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(submit_request, timeout=60) as response:
            submit_result = json.loads(response.read().decode("utf-8"))
        event_id = str(submit_result.get("event_id") or "")
        if not event_id:
            raise RuntimeError("VoxCPM Gradio 服务没有返回 event_id。")
        with urllib.request.urlopen(f"{base_url}/gradio_api/call/{api_name}/{event_id}", timeout=180) as response:
            result_data = parse_gradio_sse_data(response.read().decode("utf-8", errors="replace"))
        audio_url = str((result_data[0] or {}).get("url") or "") if isinstance(result_data, list) and result_data else ""
        if not audio_url:
            raise RuntimeError("VoxCPM Gradio 服务没有返回音频 URL。")
        with urllib.request.urlopen(audio_url, timeout=120) as response:
            content_type = response.headers.get("Content-Type") or "audio/mpeg"
            audio = response.read()
            return audio, detect_audio_content_type(audio, content_type)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"VoxCPM Gradio 服务 HTTP {exc.code}：{detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"VoxCPM Gradio 服务连接失败：{exc}") from exc


def synthesize_voxcpm_project_local(text: str, rate: float, voice_config: Dict[str, Any]) -> Tuple[bytes, str]:
    """调用项目内 VoxCPM 本地推理模块。"""

    config = VoxCpmLocalConfig.from_mapping(voice_config, PROJECT_ROOT)
    synthesizer = VoxCpmLocalSynthesizer(config)
    return synthesizer.synthesize(
        text=text,
        rate=rate,
        reference_audio_path=str(voice_config.get("ref_audio_path") or ""),
        prompt_text=str(voice_config.get("prompt_text") or ""),
    )


def synthesize_with_tts_backend(
    text: str,
    rate: float,
    voice_id: str,
    reference_id: str = "",
    prompt_text: Optional[str] = None,
) -> Tuple[bytes, str]:
    selected_voice, voice_config = select_voice_config(voice_id)
    voice_config = build_runtime_voice_config(voice_config, reference_id, prompt_text)
    backend = voice_config.get("backend") or "voxcpm_hf_space"
    if backend == "voxcpm_project_local":
        audio, content_type = synthesize_voxcpm_project_local(text, rate, voice_config)
        print(f"[TTS] voice={selected_voice} backend={backend}")
        return audio, content_type
    if backend in {"voxcpm_hf_space", "voxcpm_local", "voxcpm_local_gradio"}:
        audio, content_type = synthesize_voxcpm_gradio(text, rate, voice_config)
        print(f"[TTS] voice={selected_voice} backend={backend}")
        return audio, content_type
    raise RuntimeError(f"暂不支持的 VoxCPM backend：{backend}")


def activate_tts_runtime(voice_id: str) -> Dict[str, Any]:
    """根据前端选中的语音后端启动或释放本地推理资源。"""

    selected_voice, voice_config = select_voice_config(voice_id)
    backend = str(voice_config.get("backend") or "voxcpm_hf_space")
    if backend == "voxcpm_project_local":
        config = VoxCpmLocalConfig.from_mapping(voice_config, PROJECT_ROOT)
        status = VoxCpmLocalSynthesizer(config).prepare()
        status["voice"] = selected_voice
        status["action"] = "prepare_local_model"
        return status

    released_count = release_cached_models()
    return {
        "ok": True,
        "voice": selected_voice,
        "backend": backend,
        "action": "release_local_model",
        "released_models": released_count,
        "message": "已切换到非项目内本地推理模式，本地 VoxCPM 模型缓存已释放。",
    }


class ControlHandler(BaseHTTPRequestHandler):
    """Live2D 控制服务 HTTP 处理器。

    使用消息分发表（dict dispatch）替代 if/elif 链，参考 Open-LLM-VTuber 的
    WebSocket handler 模式。新增路由只需在分发表中添加一行。
    """

    server_version = "VisualCompanionControl/0.3"

    # ---- GET 路由分发表 ----
    _GET_ROUTES: Dict[str, str] = {
        "/health": "_health",
        "/voices": "_voices",
        "/tts-health": "_tts_health",
        "/reference-audio": "_reference_audio",
    }

    # ---- POST 路由分发表 ----
    _POST_ROUTES: Dict[str, str] = {
        "/chat": "_chat",
        "/tts": "_tts",
        "/tts-runtime": "_tts_runtime",
    }

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_cors_headers()
        self.end_headers()

    def do_GET(self) -> None:
        parsed_url = urlparse(self.path)
        path = parsed_url.path
        handler_name = self._GET_ROUTES.get(path)
        if handler_name:
            getattr(self, f"handle{handler_name}")(parsed_url.query)
        else:
            self.send_json({"error": "Not found"}, status=404)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        handler_name = self._POST_ROUTES.get(path)
        if handler_name:
            getattr(self, f"handle{handler_name}")()
        else:
            self.send_json({"error": "Not found"}, status=404)

    def handle_chat(self) -> None:
        try:
            payload = self.read_json()
            text = str(payload.get("text", "")).strip()
            if not text:
                self.send_json({"error": "text 不能为空。"}, status=400)
                return
            expressions, motions = load_manifest()
            memory_store = SqliteMemoryStore(MEMORY_DB_PATH)
            now = current_local_time()
            memory_context = memory_store.recent_turns(limit=6)
            web_context = build_web_context(text[:MAX_TEXT_LENGTH], now=now)
            client = DeepSeekLlmClient()
            plan = client.generate_live2d_control(
                text[:MAX_TEXT_LENGTH],
                expressions=expressions,
                motions=motions,
                memory_context=[turn.to_prompt_dict(now=now) for turn in memory_context],
                runtime_context={
                    "current_time": now.isoformat(timespec="seconds"),
                    "timezone": now.tzname() or "",
                    "internet_enabled": True,
                    "vision": sanitize_vision_context(payload.get("vision")),
                },
                web_context=web_context,
            )
            rate = payload.get("rate")
            if rate is not None:
                plan.speech.rate = clamp(float(rate), 0.85, 1.35)
            memory_store.append_turn(text[:MAX_TEXT_LENGTH], plan.text)
            self.send_json(plan.to_dict())
        except (LlmClientError, ValueError, RuntimeError, OSError) as exc:
            self.send_json({"error": str(exc)}, status=500)

    def handle_tts(self) -> None:
        try:
            payload = self.read_json()
            text = str(payload.get("text", "")).strip()
            if not text:
                self.send_json({"error": "text 不能为空。"}, status=400)
                return
            rate = float(payload.get("rate") or 1.0)
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
        except (ValueError, RuntimeError, OSError, json.JSONDecodeError) as exc:
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

    def read_json(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(min(length, 128 * 1024))
        return json.loads(raw.decode("utf-8"))

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
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[Control] {self.address_string()} - {format % args}")


def main() -> None:
    host = os.environ.get("LIVE2D_CONTROL_HOST", DEFAULT_HOST)
    port = int(os.environ.get("LIVE2D_CONTROL_PORT", DEFAULT_PORT))
    server = ThreadingHTTPServer((host, port), ControlHandler)
    print(f"Live2D 控制服务已启动：http://{host}:{port}/health")
    server.serve_forever()


if __name__ == "__main__":
    main()
