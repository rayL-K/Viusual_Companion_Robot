"""情绪推理 HTTP 服务 — 接收前端人脸裁剪图，返回 FER+ 情绪分类结果。

端点:
  POST /emotion
    Body: { "image": "<base64_face_crop_jpeg>" }
    Response: { "emotion": "happy", "confidence": 0.92, "full_scores": {...} }

用法:
  python -m visual_companion_robot.perception.emotion_server
"""

from __future__ import annotations

import base64
import json
import logging
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import cv2
import numpy as np

from .emotion import FerPlusEmotionRecognizer

logger = logging.getLogger(__name__)

HOST = "127.0.0.1"
PORT = 8766
MAX_REQUEST_BYTES = 2 * 1024 * 1024

_recognizer: Optional[FerPlusEmotionRecognizer] = None


class EmotionRequestHandler(BaseHTTPRequestHandler):
    """情绪推理 HTTP 处理器。"""

    def do_GET(self) -> None:
        if not self._is_request_origin_allowed():
            self._send_json(403, {"error": "Origin 不允许访问本地情绪服务"})
            return
        if self.path != "/health":
            self._send_json(404, {"error": "not found"})
            return
        self._send_json(
            200,
            {
                "ok": _recognizer is not None and _recognizer.is_loaded(),
                "service": "visual-companion-emotion",
                "backend": "ferplus-onnx",
            },
        )

    def do_POST(self) -> None:
        if not self._is_request_origin_allowed():
            self._send_json(403, {"error": "Origin 不允许访问本地情绪服务"})
            return
        if self.path != "/emotion":
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
        if length > MAX_REQUEST_BYTES:
            self._send_json(413, {"error": "请求体超过 2 MiB 限制"})
            return
        body = self.rfile.read(length)
        if len(body) != length:
            self._send_json(400, {"error": "请求体读取不完整"})
            return

        try:
            data = json.loads(body)
            if not isinstance(data, dict):
                raise ValueError("请求体必须是 JSON 对象")
            result = self._classify(data)
            self._send_json(200, result)
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
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
        if _recognizer is None:
            raise RuntimeError("FER+ 识别器尚未初始化")

        result = _recognizer.classify(face_patch)
        return {
            "emotion": result.emotion,
            "confidence": result.confidence,
            "full_scores": result.full_scores,
        }

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


def start_emotion_server(host: str = HOST, port: int = PORT) -> HTTPServer:
    """启动情绪推理 HTTP 服务。"""

    global _recognizer
    _recognizer = FerPlusEmotionRecognizer()
    _recognizer.load()

    server = HTTPServer((host, port), EmotionRequestHandler)
    logger.info("情绪推理服务已启动: http://%s:%d/emotion", host, port)
    return server


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    server = start_emotion_server()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
