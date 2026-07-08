"""VoxCPM.cpp loopback service adapter for the ELF2 board."""

from __future__ import annotations

import json
import mimetypes
import os
import subprocess
import threading
import time
import urllib.error
import urllib.request
import uuid
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterator, Tuple
from urllib.parse import quote, urlparse


class VoxCpmCppError(RuntimeError):
    pass


@dataclass(frozen=True)
class VoxCpmCppConfig:
    endpoint: str = "http://127.0.0.1:8770"
    model: str = "voxcpm-1.5"
    api_key: str = ""
    health_timeout_sec: float = 3.0
    synthesis_timeout_sec: float = 300.0
    auto_start: bool = False
    executable_path: str = "/opt/visual-companion-voxcpm/bin/voxcpm-server"
    model_path: str = "/opt/visual-companion-voxcpm/models/voxcpm1.5-q4_k-audiovae-f16.gguf"
    voice_dir: str = "/var/lib/visual-companion-voxcpm/voices"
    inference_timesteps: int = 4
    threads: int = 4

    @classmethod
    def from_mapping(cls, mapping: Dict[str, Any]) -> "VoxCpmCppConfig":
        endpoint = str(os.environ.get("VOXCPM_CPP_URL") or mapping.get("endpoint") or cls.endpoint).rstrip("/")
        parsed = urlparse(endpoint)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise VoxCpmCppError("VoxCPM.cpp 仅允许连接开发板回环地址。")
        return cls(
            endpoint=endpoint,
            model=str(mapping.get("model") or cls.model),
            api_key=str(os.environ.get("VOXCPM_CPP_API_KEY") or mapping.get("api_key") or ""),
            health_timeout_sec=float(mapping.get("health_timeout_sec") or cls.health_timeout_sec),
            synthesis_timeout_sec=float(mapping.get("synthesis_timeout_sec") or cls.synthesis_timeout_sec),
            auto_start=bool(mapping.get("auto_start", False)),
            executable_path=str(mapping.get("executable_path") or cls.executable_path),
            model_path=str(mapping.get("model_path") or cls.model_path),
            voice_dir=str(mapping.get("voice_dir") or cls.voice_dir),
            inference_timesteps=max(1, min(int(mapping.get("inference_timesteps") or 4), 100)),
            threads=max(1, min(int(mapping.get("threads") or 4), 8)),
        )


class VoxCpmCppSynthesizer:
    def __init__(self, config: VoxCpmCppConfig) -> None:
        self.config = config

    def health(self) -> Dict[str, Any]:
        try:
            status, payload, _ = self._request("GET", "/healthz", timeout=self.config.health_timeout_sec)
            result = json.loads(payload.decode("utf-8")) if payload else {}
            ok = status == 200 and result.get("status") == "ok"
            message = "VoxCPM.cpp 板端服务可用。" if ok else f"VoxCPM.cpp 健康检查异常（HTTP {status}）。"
            return {"ok": ok, "backend": "voxcpm_cpp_local", "base_url": self.config.endpoint, "message": message}
        except (OSError, ValueError, VoxCpmCppError) as exc:
            return {
                "ok": False,
                "backend": "voxcpm_cpp_local",
                "base_url": self.config.endpoint,
                "message": f"VoxCPM.cpp 板端服务不可用：{exc}",
            }

    def prepare(self) -> Dict[str, Any]:
        if not self.config.auto_start:
            return self.health()
        executable = Path(self.config.executable_path)
        model = Path(self.config.model_path)
        voice_dir = Path(self.config.voice_dir)
        missing = [str(path) for path in (executable, model) if not path.is_file()]
        if missing:
            return {
                "ok": False,
                "backend": "voxcpm_cpp_local",
                "base_url": self.config.endpoint,
                "message": f"VoxCPM.cpp 板端文件不完整：{' / '.join(missing)}",
            }
        if not os.access(executable, os.X_OK):
            return {
                "ok": False,
                "backend": "voxcpm_cpp_local",
                "base_url": self.config.endpoint,
                "message": f"VoxCPM.cpp 板端程序不可执行：{executable}",
            }
        try:
            voice_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return {
                "ok": False,
                "backend": "voxcpm_cpp_local",
                "base_url": self.config.endpoint,
                "message": f"VoxCPM.cpp 音色目录不可用：{exc}",
            }
        return {
            "ok": True,
            "backend": "voxcpm_cpp_local",
            "base_url": self.config.endpoint,
            "state": "installed",
            "message": "VoxCPM.cpp 已安装在 ELF2，将在合成时按需启动。",
        }

    def synthesize(
        self,
        text: str,
        rate: float,
        reference_id: str,
        reference_audio_path: str,
        prompt_text: str,
    ) -> Tuple[bytes, str]:
        context = process_manager_for(self.config).session() if self.config.auto_start else nullcontext()
        with context:
            clean_text = str(text or "").strip()
            if not clean_text:
                raise VoxCpmCppError("待合成文本不能为空。")
            voice_id = self._normalize_voice_id(reference_id)
            self.ensure_voice(voice_id, reference_audio_path, prompt_text)
            body = json.dumps(
                {
                    "model": self.config.model,
                    "input": clean_text,
                    "voice": voice_id,
                    "response_format": "wav",
                    "speed": max(0.25, min(float(rate), 4.0)),
                    "stream_format": "audio",
                },
                ensure_ascii=False,
            ).encode("utf-8")
            status, audio, content_type = self._request(
                "POST",
                "/v1/audio/speech",
                body=body,
                content_type="application/json",
                timeout=self.config.synthesis_timeout_sec,
            )
            if status != 200:
                raise VoxCpmCppError(self._http_error("语音合成", status, audio))
            if not audio.startswith(b"RIFF"):
                raise VoxCpmCppError("VoxCPM.cpp 没有返回有效 WAV 音频。")
            return audio, content_type or "audio/wav"

    def ensure_voice(self, voice_id: str, reference_audio_path: str, prompt_text: str) -> None:
        status, payload, _ = self._request(
            "GET",
            f"/v1/voices/{quote(voice_id)}",
            timeout=self.config.health_timeout_sec,
            accepted_http_errors={404},
        )
        if status == 200:
            return
        if status != 404:
            raise VoxCpmCppError(self._http_error("查询参考音色", status, payload))

        audio_path = Path(str(reference_audio_path or ""))
        transcript = str(prompt_text or "").strip()
        if not audio_path.is_file():
            raise VoxCpmCppError(f"参考音频不存在：{audio_path}")
        if not transcript:
            raise VoxCpmCppError("参考音频对应文本不能为空。")
        body, content_type = self._multipart_voice(voice_id, transcript, audio_path)
        status, payload, _ = self._request(
            "POST",
            "/v1/voices",
            body=body,
            content_type=content_type,
            timeout=self.config.synthesis_timeout_sec,
            accepted_http_errors={409},
        )
        if status not in {201, 409}:
            raise VoxCpmCppError(self._http_error("注册参考音色", status, payload))

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: bytes | None = None,
        content_type: str = "",
        timeout: float,
        accepted_http_errors: set[int] | None = None,
    ) -> Tuple[int, bytes, str]:
        headers = {}
        if content_type:
            headers["Content-Type"] = content_type
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        request = urllib.request.Request(self.config.endpoint + path, data=body, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.status, response.read(), response.headers.get("Content-Type") or ""
        except urllib.error.HTTPError as exc:
            payload = exc.read()
            if exc.code in (accepted_http_errors or set()):
                return exc.code, payload, exc.headers.get("Content-Type") or ""
            raise VoxCpmCppError(self._http_error(path, exc.code, payload)) from exc
        except urllib.error.URLError as exc:
            raise VoxCpmCppError(f"无法连接 VoxCPM.cpp 板端服务：{exc.reason}") from exc

    @staticmethod
    def _normalize_voice_id(value: str) -> str:
        voice_id = str(value or "").strip()
        if not voice_id or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for char in voice_id):
            raise VoxCpmCppError("参考音色 ID 只能包含字母、数字、点、下划线和连字符。")
        return voice_id

    @staticmethod
    def _multipart_voice(voice_id: str, transcript: str, audio_path: Path) -> Tuple[bytes, str]:
        boundary = f"----VisualCompanion{uuid.uuid4().hex}"
        chunks: list[bytes] = []
        for name, value in (("id", voice_id), ("text", transcript)):
            chunks.append(
                f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode("utf-8")
            )
        mime = mimetypes.guess_type(audio_path.name)[0] or "application/octet-stream"
        chunks.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="audio"; filename="{audio_path.name}"\r\nContent-Type: {mime}\r\n\r\n'.encode(
                "utf-8"
            )
        )
        chunks.extend((audio_path.read_bytes(), b"\r\n", f"--{boundary}--\r\n".encode("ascii")))
        return b"".join(chunks), f"multipart/form-data; boundary={boundary}"

    @staticmethod
    def _http_error(action: str, status: int, payload: bytes) -> str:
        detail = payload.decode("utf-8", errors="replace")[:500]
        return f"VoxCPM.cpp {action}失败（HTTP {status}）：{detail}"


class VoxCpmCppProcessManager:
    """按请求启动 VoxCPM.cpp，并在请求结束后释放约 2.3 GiB 内存。"""

    def __init__(self, config: VoxCpmCppConfig) -> None:
        self.config = config
        self._lock = threading.RLock()
        self._process: subprocess.Popen[bytes] | None = None

    @contextmanager
    def session(self) -> Iterator[None]:
        with self._lock:
            started_here = self._ensure_running()
            try:
                yield
            finally:
                if started_here:
                    self._shutdown()

    def _ensure_running(self) -> bool:
        if self._healthy():
            return False
        executable = Path(self.config.executable_path)
        model = Path(self.config.model_path)
        if not executable.is_file() or not model.is_file():
            raise VoxCpmCppError(f"VoxCPM.cpp 板端文件不完整：{executable} / {model}")
        voice_dir = Path(self.config.voice_dir)
        voice_dir.mkdir(parents=True, exist_ok=True)
        log_path = Path(os.environ.get("VOXCPM_CPP_LOG") or "/tmp/visual-companion-voxcpm.log")
        command = [
            str(executable), "--model-path", str(model), "--model-name", self.config.model,
            "--voice-dir", str(voice_dir), "--host", "127.0.0.1", "--port", str(urlparse(self.config.endpoint).port or 8770),
            "--backend", "cpu", "--threads", str(self.config.threads), "--inference-timesteps", str(self.config.inference_timesteps),
            "--max-queue", "1", "--max-attempts", "1", "--disable-auth",
        ]
        with log_path.open("ab") as log_file:
            self._process = subprocess.Popen(command, stdout=log_file, stderr=subprocess.STDOUT, start_new_session=True)
        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline:
            if self._process.poll() is not None:
                raise VoxCpmCppError(f"VoxCPM.cpp 启动失败，退出码 {self._process.returncode}；日志：{log_path}")
            if self._healthy():
                return True
            time.sleep(0.1)
        self._shutdown()
        raise VoxCpmCppError("VoxCPM.cpp 未在 30 秒内通过健康检查。")

    def _healthy(self) -> bool:
        try:
            with urllib.request.urlopen(self.config.endpoint + "/healthz", timeout=0.8) as response:
                return response.status == 200
        except (OSError, urllib.error.URLError):
            return False

    def _shutdown(self) -> None:
        process, self._process = self._process, None
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


_PROCESS_MANAGERS: Dict[str, VoxCpmCppProcessManager] = {}
_PROCESS_MANAGERS_LOCK = threading.Lock()


def process_manager_for(config: VoxCpmCppConfig) -> VoxCpmCppProcessManager:
    with _PROCESS_MANAGERS_LOCK:
        manager = _PROCESS_MANAGERS.get(config.endpoint)
        if manager is None or manager.config != config:
            manager = VoxCpmCppProcessManager(config)
            _PROCESS_MANAGERS[config.endpoint] = manager
        return manager
