from __future__ import annotations

import io
import json
import struct
import unittest
from base64 import b64encode
from unittest.mock import patch

from main.scripts import live2d_control_server as _control_server  # 统一测试导入路径。
from visual_companion_robot.runtime.realtime_websocket import JsonWebSocket, websocket_accept_value


def masked_text_frame(payload: dict) -> bytes:
    raw = json.dumps(payload).encode("utf-8")
    mask = b"\x11\x22\x33\x44"
    if len(raw) < 126:
        header = bytes((0x81, 0x80 | len(raw)))
    else:
        header = bytes((0x81, 0x80 | 126)) + struct.pack("!H", len(raw))
    masked = bytes(value ^ mask[index % 4] for index, value in enumerate(raw))
    return header + mask + masked


class RealtimeWebSocketTests(unittest.TestCase):
    def test_known_handshake_value_matches_rfc(self) -> None:
        self.assertEqual(
            websocket_accept_value("dGhlIHNhbXBsZSBub25jZQ=="),
            "s3pPLMBiTxaQ9kYGzzhZRbK+xOo=",
        )

    def test_masked_json_message_is_decoded_and_response_is_unmasked(self) -> None:
        reader = io.BytesIO(masked_text_frame({"id": "v1", "type": "vision"}))
        writer = io.BytesIO()
        connection = JsonWebSocket(reader, writer, 1024)

        self.assertEqual(connection.receive_json(), {"id": "v1", "type": "vision"})
        connection.send_json({"ok": True})

        output = writer.getvalue()
        self.assertEqual(output[0], 0x81)
        self.assertEqual(output[1], len(b'{"ok":true}'))
        self.assertEqual(output[2:], b'{"ok":true}')

    def test_streaming_asr_buffers_chunks_and_decodes_only_at_sentence_end(self) -> None:
        session = _control_server.RealtimeInferenceSession()
        pcm = b"\x01\x00" * 4_800
        result = type("Result", (), {"to_dict": lambda self: {
            "text": "你好",
            "speech_detected": True,
            "speech_ratio": 0.8,
            "duration_ms": 300,
        }})()

        started = session.dispatch({"id": "asr-1", "type": "asr_start", "sample_rate": 16_000})
        chunk = session.dispatch({
            "id": "asr-1",
            "type": "asr_chunk",
            "audio_pcm_base64": b64encode(pcm).decode("ascii"),
        })
        with patch.object(_control_server.ASR_SERVICE, "transcribe_pcm16", return_value=result) as transcribe:
            ended = session.dispatch({"id": "asr-1", "type": "asr_end"})

        self.assertEqual(started, {"id": "asr-1", "type": "asr_started", "ok": True})
        self.assertIsNone(chunk)
        transcribe.assert_called_once_with(pcm)
        self.assertEqual(ended["data"]["text"], "你好")

    def test_streaming_asr_rejects_chunk_without_start(self) -> None:
        session = _control_server.RealtimeInferenceSession()

        result = session.dispatch({
            "id": "missing",
            "type": "asr_chunk",
            "audio_pcm_base64": b64encode(b"\x00\x00").decode("ascii"),
        })

        self.assertFalse(result["ok"])
        self.assertIn("未开始", result["error"])


if __name__ == "__main__":
    unittest.main()
