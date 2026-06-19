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
import io
import json
import logging
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Any, Dict

import cv2
import numpy as np

from .emotion import FerPlusEmotionRecognizer

logger = logging.getLogger(__name__)

HOST = "127.0.0.1"
PORT = 8766

_recognizer: FerPlusEmotionRecognizer = None


class EmotionRequestHandler(BaseHTTPRequestHandler):
    """情绪推理 HTTP 处理器。"""

    def do_POST(self) -> None:
        if self.path != "/emotion":
            self._send_json(404, {"error": "not found"})
            return

        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)

        try:
            data = json.loads(body)
            result = self._classify(data)
            self._send_json(200, result)
        except Exception as exc:
            logger.warning("情绪推理失败: %s", exc)
            self._send_json(400, {"error": str(exc)})

    def _classify(self, data: Dict[str, Any]) -> Dict[str, Any]:
        image_b64 = data.get("image", "")
        if not image_b64:
            raise ValueError("缺少 image 字段")

        image_bytes = base64.b64decode(image_b64)
        np_arr = np.frombuffer(image_bytes, dtype=np.uint8)
        face_patch = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)

        if face_patch is None or face_patch.size == 0:
            raise ValueError("图片解码失败")

        result = _recognizer.classify(face_patch)
        return {
            "emotion": result.emotion,
            "confidence": result.confidence,
            "full_scores": result.full_scores,
        }

    def _send_json(self, status: int, data: Dict[str, Any]) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

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
