"""本地人脸 HTTP 服务 — YuNet + SFace + FER+。

端点:
  POST /emotion
    Body: { "image": "<base64_face_crop_jpeg>" }
    Response: { "emotion": "happy", "confidence": 0.92, "full_scores": {...} }

用法:
  python -m visual_companion_robot.perception.emotion_server
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import cv2
import numpy as np

from .emotion import FerPlusEmotionRecognizer
from .active_speaker import (
    ActiveSpeakerBusyError,
    ActiveSpeakerInputError,
    ActiveSpeakerRecognizer,
)
from .face_analysis import FaceEnrollmentError, FaceProfileStore, LocalFaceAnalyzer

logger = logging.getLogger(__name__)

HOST = os.environ.get("VISUAL_COMPANION_EMOTION_HOST", "127.0.0.1")
PORT = int(os.environ.get("VISUAL_COMPANION_EMOTION_PORT", "8766"))
MAX_IMAGE_REQUEST_BYTES = 2 * 1024 * 1024
MAX_ACTIVE_SPEAKER_REQUEST_BYTES = 8 * 1024 * 1024

_recognizer: Optional[FerPlusEmotionRecognizer] = None
_face_analyzer: Optional[LocalFaceAnalyzer] = None
_active_speaker: Optional[ActiveSpeakerRecognizer] = None
_active_speaker_request_lock = threading.Lock()

PROJECT_ROOT = Path(__file__).resolve().parents[4]
YUNET_MODEL_PATH = Path(
    os.environ.get("VISUAL_COMPANION_YUNET_MODEL")
    or PROJECT_ROOT / "main" / "models" / "face" / "yunet.onnx"
)
SFACE_MODEL_PATH = Path(
    os.environ.get("VISUAL_COMPANION_SFACE_MODEL")
    or PROJECT_ROOT / "main" / "models" / "face" / "sface.onnx"
)
FACE_PROFILE_DB_PATH = Path(
    os.environ.get("VISUAL_COMPANION_FACE_PROFILE_DB")
    or PROJECT_ROOT / "main" / "data" / "face_profiles.sqlite3"
)
ACTIVE_SPEAKER_MODEL_PATH = Path(
    os.environ.get("VISUAL_COMPANION_ACTIVE_SPEAKER_MODEL")
    or PROJECT_ROOT / "main" / "models" / "active_speaker" / "light-asd-ava.onnx"
)


class EmotionRequestHandler(BaseHTTPRequestHandler):
    """情绪推理 HTTP 处理器。"""

    def do_GET(self) -> None:
        if not self._is_request_origin_allowed():
            self._send_json(403, {"error": "Origin 不允许访问本地情绪服务"})
            return
        if self.path == "/face-profiles":
            if _face_analyzer is None:
                self._send_json(503, {"error": "本地人脸分析器尚未初始化"})
                return
            self._send_json(200, {"profiles": _face_analyzer.list_profiles()})
            return
        if self.path != "/health":
            self._send_json(404, {"error": "not found"})
            return
        self._send_json(
            200,
            {
                "ok": (
                    _face_analyzer is not None
                    and _face_analyzer.is_loaded()
                    and _active_speaker is not None
                    and _active_speaker.is_loaded()
                ),
                "service": "visual-companion-emotion",
                "backend": "yunet-sface-ferplus-local",
                "face_detector": "opencv-yunet",
                "face_identity": "opencv-sface",
                "emotion": "ferplus-onnx",
                "active_speaker": "light-asd-onnx",
            },
        )

    def do_POST(self) -> None:
        if not self._is_request_origin_allowed():
            self._send_json(403, {"error": "Origin 不允许访问本地情绪服务"})
            return
        if self.path not in {"/emotion", "/face-enroll", "/active-speaker"}:
            self._send_json(404, {"error": "not found"})
            return

        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            self._send_json(400, {"error": "Content-Length 无效"})
            return
        if length <= 0:
            self._send_json(400, {"error": "请求体不能为空"})
            return
        max_bytes = (
            MAX_ACTIVE_SPEAKER_REQUEST_BYTES
            if self.path == "/active-speaker"
            else MAX_IMAGE_REQUEST_BYTES
        )
        if length > max_bytes:
            self._send_json(413, {"error": f"请求体超过 {max_bytes // 1024 // 1024} MiB 限制"})
            return
        body = self.rfile.read(length)
        if len(body) != length:
            self._send_json(400, {"error": "请求体读取不完整"})
            return

        try:
            data = json.loads(body)
            if not isinstance(data, dict):
                raise ValueError("请求体必须是 JSON 对象")
            if self.path == "/face-enroll":
                result = self._enroll(data)
            elif self.path == "/active-speaker":
                result = self._classify_active_speaker(data)
            else:
                result = self._classify(data)
            self._send_json(200, result)
        except (ValueError, ActiveSpeakerInputError) as exc:
            self._send_json(400, {"error": str(exc)})
        except ActiveSpeakerBusyError as exc:
            self._send_json(429, {"error": str(exc)})
        except binascii.Error:
            self._send_json(400, {"error": "Base64 数据无效"})
        except Exception as exc:
            logger.exception("FER+ 情绪推理失败")
            self._send_json(500, {"error": str(exc)})

    def _classify(self, data: Dict[str, Any]) -> Dict[str, Any]:
        image_b64 = data.get("image", "")
        if not image_b64:
            raise ValueError("缺少 image 字段")

        image_bytes = base64.b64decode(image_b64, validate=True)
        np_arr = np.frombuffer(image_bytes, dtype=np.uint8)
        face_patch = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)

        if face_patch is None or face_patch.size == 0:
            raise ValueError("图片解码失败")
        if _face_analyzer is None:
            raise RuntimeError("本地人脸分析器尚未初始化")

        result = _face_analyzer.analyze(face_patch)
        focus_index = result["focus_face_index"]
        if focus_index is None:
            return {
                "has_face": False,
                "emotion": "neutral",
                "confidence": 0.0,
                "full_scores": {"neutral": 1.0},
                **result,
            }
        focus = result["faces"][focus_index]
        return {
            "has_face": True,
            "emotion": focus["emotion"],
            "confidence": focus["emotion_confidence"],
            "full_scores": focus["emotion_scores"],
            **result,
        }

    def _enroll(self, data: Dict[str, Any]) -> Dict[str, Any]:
        image = self._decode_image(data.get("image", ""))
        if _face_analyzer is None:
            raise RuntimeError("本地人脸分析器尚未初始化")
        try:
            profile = _face_analyzer.enroll(image, str(data.get("name") or ""))
        except FaceEnrollmentError:
            raise
        return {
            "ok": True,
            "profile_id": profile.profile_id,
            "name": profile.name,
            "stored": "embedding_only",
        }

    def _classify_active_speaker(self, data: Dict[str, Any]) -> Dict[str, Any]:
        if _face_analyzer is None or _active_speaker is None:
            raise RuntimeError("本地主动说话人服务尚未初始化")
        if int(data.get("sample_rate") or 0) != 16_000:
            raise ValueError("主动说话人音频必须是 16 kHz PCM16")
        raw_audio = data.get("audio_pcm_base64")
        if not isinstance(raw_audio, str) or not raw_audio:
            raise ValueError("缺少 audio_pcm_base64")
        audio_bytes = base64.b64decode(raw_audio, validate=True)
        if len(audio_bytes) % 2 or len(audio_bytes) > 16_000 * 2 * 20:
            raise ValueError("PCM16 音频长度无效")
        frames = data.get("frames")
        if not isinstance(frames, list) or not 4 <= len(frames) <= 40:
            raise ValueError("主动说话人需要 4–40 帧同步画面")
        if not _active_speaker_request_lock.acquire(blocking=False):
            raise ActiveSpeakerBusyError("主动说话人服务繁忙，请稍后重试")
        try:
            images = []
            for frame in frames:
                if not isinstance(frame, dict):
                    raise ValueError("frames 中的每一项必须是对象")
                images.append(self._decode_image(frame.get("image", "")))
            tracks = _face_analyzer.track_faces(images)
            result = _active_speaker.analyze(np.frombuffer(audio_bytes, dtype="<i2"), tracks)
        finally:
            _active_speaker_request_lock.release()
        return {
            "ok": True,
            "backend": "elf2-local-light-asd",
            "frame_count": len(images),
            "track_count": len(tracks),
            **result,
        }

    @staticmethod
    def _decode_image(image_b64: str) -> np.ndarray:
        if not image_b64:
            raise ValueError("缺少 image 字段")
        image_bytes = base64.b64decode(image_b64, validate=True)
        image = cv2.imdecode(np.frombuffer(image_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None or image.size == 0:
            raise ValueError("图片解码失败")
        return image

    def _send_json(self, status: int, data: Dict[str, Any]) -> None:
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        origin = str(self.headers.get("Origin") or "").strip()
        if origin and self._is_request_origin_allowed():
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.end_headers()
        self.wfile.write(payload)

    def do_OPTIONS(self) -> None:
        if not self._is_request_origin_allowed():
            self._send_json(403, {"error": "Origin 不允许访问本地情绪服务"})
            return
        self.send_response(204)
        origin = str(self.headers.get("Origin") or "").strip()
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _is_request_origin_allowed(self) -> bool:
        origin = str(self.headers.get("Origin") or "").strip()
        if not origin:
            return True
        parsed = urlparse(origin)
        return parsed.scheme in {"http", "https"} and parsed.hostname in {"127.0.0.1", "localhost", "::1"}

    def log_message(self, fmt, *args) -> None:
        logger.debug(fmt, *args)


def start_emotion_server(host: str = HOST, port: int = PORT) -> ThreadingHTTPServer:
    """启动情绪推理 HTTP 服务。"""

    global _recognizer, _face_analyzer, _active_speaker
    _recognizer = FerPlusEmotionRecognizer()
    _recognizer.load()
    _face_analyzer = LocalFaceAnalyzer(
        YUNET_MODEL_PATH,
        SFACE_MODEL_PATH,
        _recognizer,
        FaceProfileStore(FACE_PROFILE_DB_PATH),
    )
    _face_analyzer.load()
    _active_speaker = ActiveSpeakerRecognizer(ACTIVE_SPEAKER_MODEL_PATH)
    _active_speaker.load()

    server = ThreadingHTTPServer((host, port), EmotionRequestHandler)
    logger.info("情绪推理服务已启动: http://%s:%d/emotion", host, port)
    return server


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    server = start_emotion_server()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
