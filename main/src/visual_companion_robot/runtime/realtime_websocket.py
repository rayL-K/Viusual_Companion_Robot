"""为板端实时推理提供最小、受限的 WebSocket JSON 传输层。"""

from __future__ import annotations

import base64
import hashlib
import json
import struct
import threading
from collections.abc import Callable, Mapping
from typing import Any, BinaryIO


WEBSOCKET_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
DEFAULT_MAX_MESSAGE_BYTES = 2 * 1024 * 1024


class WebSocketProtocolError(ValueError):
    """客户端 WebSocket 帧或消息不符合协议。"""


def is_websocket_upgrade(headers: Mapping[str, str]) -> bool:
    connection = str(headers.get("Connection") or "").lower()
    upgrade = str(headers.get("Upgrade") or "").lower()
    return upgrade == "websocket" and "upgrade" in {part.strip() for part in connection.split(",")}


def websocket_accept_value(key: str) -> str:
    raw = hashlib.sha1(f"{key}{WEBSOCKET_GUID}".encode("ascii")).digest()
    return base64.b64encode(raw).decode("ascii")


class JsonWebSocket:
    """拥有单条升级连接，串行读取请求并以线程安全方式发送 JSON。"""

    def __init__(self, reader: BinaryIO, writer: BinaryIO, max_message_bytes: int) -> None:
        self._reader = reader
        self._writer = writer
        self._max_message_bytes = max_message_bytes
        self._write_lock = threading.Lock()
        self._closed = False

    def receive_json(self) -> dict[str, Any] | None:
        payload = self._receive_text()
        if payload is None:
            return None
        try:
            value = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise WebSocketProtocolError("实时消息必须是有效 JSON。") from exc
        if not isinstance(value, dict):
            raise WebSocketProtocolError("实时消息必须是 JSON 对象。")
        return value

    def send_json(self, payload: Mapping[str, Any]) -> None:
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self._send_frame(0x1, raw)

    def close(self, code: int = 1000, reason: str = "") -> None:
        if self._closed:
            return
        reason_bytes = reason.encode("utf-8")[:123]
        try:
            self._send_frame(0x8, struct.pack("!H", code) + reason_bytes)
        finally:
            self._closed = True

    def _receive_text(self) -> str | None:
        fragments: list[bytes] = []
        total = 0
        expected_continuation = False
        while True:
            header = self._read_exact(2)
            if header is None:
                return None
            first, second = header
            final = bool(first & 0x80)
            opcode = first & 0x0F
            if first & 0x70:
                raise WebSocketProtocolError("不支持带扩展位的 WebSocket 帧。")
            masked = bool(second & 0x80)
            if not masked:
                raise WebSocketProtocolError("客户端 WebSocket 帧必须使用掩码。")
            length = second & 0x7F
            if length == 126:
                length = struct.unpack("!H", self._read_required(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", self._read_required(8))[0]
            if length > self._max_message_bytes or total + length > self._max_message_bytes:
                raise WebSocketProtocolError("实时消息超过 2 MiB 限制。")
            mask = self._read_required(4)
            payload = bytearray(self._read_required(length))
            for index in range(length):
                payload[index] ^= mask[index % 4]

            if opcode == 0x8:
                self.close()
                return None
            if opcode == 0x9:
                self._send_frame(0xA, bytes(payload))
                continue
            if opcode == 0xA:
                continue
            if opcode == 0x1:
                if expected_continuation:
                    raise WebSocketProtocolError("上一条分片消息尚未结束。")
                expected_continuation = not final
            elif opcode == 0x0:
                if not expected_continuation:
                    raise WebSocketProtocolError("收到无起始帧的 continuation 消息。")
                expected_continuation = not final
            else:
                raise WebSocketProtocolError("实时通道只接受文本 JSON 消息。")

            fragments.append(bytes(payload))
            total += length
            if final:
                try:
                    return b"".join(fragments).decode("utf-8")
                except UnicodeDecodeError as exc:
                    raise WebSocketProtocolError("实时消息必须使用 UTF-8。") from exc

    def _send_frame(self, opcode: int, payload: bytes) -> None:
        if self._closed and opcode != 0x8:
            return
        length = len(payload)
        if length < 126:
            header = bytes((0x80 | opcode, length))
        elif length <= 0xFFFF:
            header = bytes((0x80 | opcode, 126)) + struct.pack("!H", length)
        else:
            header = bytes((0x80 | opcode, 127)) + struct.pack("!Q", length)
        with self._write_lock:
            self._writer.write(header + payload)
            self._writer.flush()

    def _read_required(self, length: int) -> bytes:
        value = self._read_exact(length)
        if value is None:
            raise WebSocketProtocolError("WebSocket 帧提前结束。")
        return value

    def _read_exact(self, length: int) -> bytes | None:
        if length == 0:
            return b""
        chunks: list[bytes] = []
        remaining = length
        while remaining:
            chunk = self._reader.read(remaining)
            if not chunk:
                return None
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)


def serve_json_websocket(
    handler: Any,
    dispatch: Callable[[dict[str, Any]], Mapping[str, Any] | None],
    *,
    max_message_bytes: int = DEFAULT_MAX_MESSAGE_BYTES,
) -> None:
    """完成升级并持续分发 JSON 请求；请求级错误不会主动断开连接。"""

    key = str(handler.headers.get("Sec-WebSocket-Key") or "").strip()
    version = str(handler.headers.get("Sec-WebSocket-Version") or "").strip()
    if not key or version != "13":
        handler.send_json({"error": "WebSocket 握手参数无效。"}, status=400)
        return

    handler.send_response(101, "Switching Protocols")
    handler.send_header("Upgrade", "websocket")
    handler.send_header("Connection", "Upgrade")
    handler.send_header("Sec-WebSocket-Accept", websocket_accept_value(key))
    handler.end_headers()
    connection = JsonWebSocket(handler.rfile, handler.wfile, max_message_bytes)
    try:
        while True:
            try:
                request = connection.receive_json()
                if request is None:
                    break
                response = dispatch(request)
                if response is not None:
                    connection.send_json(response)
            except WebSocketProtocolError as exc:
                connection.send_json({"ok": False, "error": str(exc)})
    except (BrokenPipeError, ConnectionResetError, OSError):
        pass
    finally:
        connection.close()
