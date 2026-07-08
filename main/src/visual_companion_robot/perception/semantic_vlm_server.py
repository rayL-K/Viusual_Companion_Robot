"""板端常驻 VLM HTTP 服务；通过受控子进程隔离 RKLLM 运行时。"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import os
import queue
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


LOGGER = logging.getLogger(__name__)
HOST = os.environ.get("VISUAL_COMPANION_VLM_HOST", "127.0.0.1")
PORT = int(os.environ.get("VISUAL_COMPANION_VLM_PORT", "8767"))
WORKER_PATH = Path(os.environ.get("VISUAL_COMPANION_VLM_WORKER", "/opt/visual-companion-vlm/vlm_worker"))
VISION_MODEL_PATH = Path(os.environ.get(
    "VISUAL_COMPANION_VLM_VISION_MODEL",
    "/opt/visual-companion-vlm/models/qwen3-vl-2b-vision_rk3588.rknn",
))
LLM_MODEL_PATH = Path(os.environ.get(
    "VISUAL_COMPANION_VLM_LLM_MODEL",
    "/opt/visual-companion-vlm/models/qwen3-vl-2b-instruct_w8a8_rk3588.rkllm",
))
LIBRARY_PATH = os.environ.get("VISUAL_COMPANION_VLM_LIBRARY_PATH", "/opt/visual-companion-vlm/vendor/aarch64/library")
MAX_IMAGE_BYTES = 1536 * 1024
MAX_REQUEST_BYTES = 2 * 1024 * 1024
RESULT_PREFIX = "VCR_RESULT_BASE64:"
ERROR_PREFIX = "VCR_ERROR_BASE64:"
BACKEND_NAME = os.environ.get("VISUAL_COMPANION_VLM_BACKEND", "rk3588-qwen3-vl-2b-w8a8")
MAX_NEW_TOKENS = int(os.environ.get("VISUAL_COMPANION_VLM_MAX_NEW_TOKENS", "32"))
CONTEXT_LENGTH = int(os.environ.get("VISUAL_COMPANION_VLM_CONTEXT_LENGTH", "512"))


class VlmWorkerError(RuntimeError):
    """VLM 工作进程未能完成语义推理。"""


class PersistentVlmWorker:
    """拥有单个 RKLLM 子进程；一次只允许一张图片进入 NPU。"""

    def __init__(self) -> None:
        self._process: subprocess.Popen[str] | None = None
        self._lines: queue.Queue[str] = queue.Queue()
        self._lock = threading.Lock()

    @property
    def ready(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def start(self) -> None:
        for path in (WORKER_PATH, VISION_MODEL_PATH, LLM_MODEL_PATH):
            if not path.is_file():
                raise VlmWorkerError(f"VLM 文件不存在：{path}")
        environment = os.environ.copy()
        environment["LD_LIBRARY_PATH"] = f"{LIBRARY_PATH}:{environment.get('LD_LIBRARY_PATH', '')}"
        self._process = subprocess.Popen(
            [
                str(WORKER_PATH),
                str(VISION_MODEL_PATH),
                str(LLM_MODEL_PATH),
                str(MAX_NEW_TOKENS),
                str(CONTEXT_LENGTH),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=environment,
        )
        threading.Thread(target=self._read_stdout, name="vlm-worker-output", daemon=True).start()
        self._wait_for("VCR_READY", timeout=45.0)

    def close(self) -> None:
        process = self._process
        self._process = None
        if process is None:
            return
        try:
            if process.stdin:
                process.stdin.write("VCR_EXIT\n")
                process.stdin.flush()
            process.wait(timeout=3)
        except (BrokenPipeError, subprocess.TimeoutExpired):
            process.kill()

    def analyze(self, image_bytes: bytes) -> str:
        with self._lock:
            if not self.ready or self._process is None or self._process.stdin is None:
                raise VlmWorkerError("VLM 工作进程未就绪")
            with tempfile.NamedTemporaryFile(prefix="vcr-vlm-", suffix=".jpg", dir="/dev/shm", delete=False) as image_file:
                image_file.write(image_bytes)
                image_path = Path(image_file.name)
            try:
                self._process.stdin.write(f"{image_path}\n")
                self._process.stdin.flush()
                return self._read_result(timeout=20.0)
            except BrokenPipeError as exc:
                raise VlmWorkerError("VLM 工作进程已退出") from exc
            finally:
                image_path.unlink(missing_ok=True)

    def _read_stdout(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return
        for raw_line in process.stdout:
            line = raw_line.rstrip("\r\n")
            if line:
                self._lines.put(line)

    def _wait_for(self, expected: str, timeout: float) -> None:
        while True:
            try:
                line = self._lines.get(timeout=timeout)
            except queue.Empty as exc:
                raise VlmWorkerError("VLM 模型启动超时") from exc
            if line == expected:
                return
            LOGGER.info("VLM 启动信息：%s", line)

    def _read_result(self, timeout: float) -> str:
        while True:
            try:
                line = self._lines.get(timeout=timeout)
            except queue.Empty as exc:
                raise VlmWorkerError("VLM 推理超时") from exc
            if line.startswith(RESULT_PREFIX):
                return _decode_text(line[len(RESULT_PREFIX):])
            if line.startswith(ERROR_PREFIX):
                raise VlmWorkerError(_decode_text(line[len(ERROR_PREFIX):]))
            LOGGER.info("VLM 推理信息：%s", line)


def _decode_text(encoded: str) -> str:
    try:
        value = base64.b64decode(encoded, validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError) as exc:
        raise VlmWorkerError("VLM 工作进程返回了无效编码") from exc
    return " ".join(value.split())[:400]


def _decode_image(payload: Any) -> bytes:
    if not isinstance(payload, dict) or not isinstance(payload.get("image"), str):
        raise ValueError("请求必须包含 Base64 image 字段")
    try:
        image = base64.b64decode(payload["image"], validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("image 不是有效 Base64") from exc
    if not image or len(image) > MAX_IMAGE_BYTES:
        raise ValueError("图片为空或超过 1.5 MiB")
    return image


class VlmRequestHandler(BaseHTTPRequestHandler):
    worker: PersistentVlmWorker

    def do_GET(self) -> None:  # noqa: N802
        if self.path != "/health":
            self._send_json({"error": "not found"}, 404)
            return
        self._send_json({
            "ok": self.worker.ready,
            "backend": BACKEND_NAME,
            "local": True,
        }, 200 if self.worker.ready else 503)

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/analyze":
            self._send_json({"error": "not found"}, 404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > MAX_REQUEST_BYTES:
                raise ValueError("请求体为空或超过 2 MiB")
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            description = self.worker.analyze(_decode_image(payload))
            self._send_json({
                "ok": True,
                "backend": BACKEND_NAME,
                "semantic_caption": description,
            })
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            self._send_json({"ok": False, "error": str(exc)}, 400)
        except VlmWorkerError as exc:
            self._send_json({"ok": False, "error": str(exc)}, 503)

    def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format_string: str, *args: Any) -> None:
        LOGGER.info("VLM HTTP: " + format_string, *args)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    worker = PersistentVlmWorker()
    worker.start()
    VlmRequestHandler.worker = worker
    server = ThreadingHTTPServer((HOST, PORT), VlmRequestHandler)
    LOGGER.info("本地语义视觉服务已启动：http://%s:%d/health", HOST, PORT)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        worker.close()


if __name__ == "__main__":
    main()
