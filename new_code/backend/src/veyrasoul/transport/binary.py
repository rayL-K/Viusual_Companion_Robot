"""Compact binary framing shared by browser media upload and server audio output."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from enum import IntEnum


MAGIC = b"VSR2"
HEADER = struct.Struct("!4sBBHQQ")
HEADER_BYTES = HEADER.size
MAX_PAYLOAD_BYTES = 2 * 1024 * 1024


class BinaryKind(IntEnum):
    PCM16 = 1
    JPEG = 2
    AUDIO = 3
    AVATAR_VISEME = 4


@dataclass(frozen=True, slots=True)
class BinaryFrame:
    kind: BinaryKind
    flags: int
    sequence: int
    timestamp_ms: int
    payload: bytes


def build_binary_frame(
    kind: BinaryKind,
    sequence: int,
    timestamp_ms: int,
    payload: bytes,
    *,
    flags: int = 0,
) -> bytes:
    if not 0 <= flags <= 255:
        raise ValueError("flags must fit uint8")
    if not 0 <= sequence < 2**64 or not 0 <= timestamp_ms < 2**64:
        raise ValueError("sequence and timestamp must fit uint64")
    body = bytes(payload)
    if len(body) > MAX_PAYLOAD_BYTES:
        raise ValueError("binary payload exceeds 2 MiB")
    return HEADER.pack(MAGIC, int(kind), flags, HEADER_BYTES, sequence, timestamp_ms) + body


def parse_binary_frame(value: bytes) -> BinaryFrame:
    if len(value) < HEADER_BYTES:
        raise ValueError("binary frame is shorter than its header")
    magic, raw_kind, flags, header_bytes, sequence, timestamp_ms = HEADER.unpack_from(value)
    if magic != MAGIC or header_bytes != HEADER_BYTES:
        raise ValueError("binary frame header is invalid")
    try:
        kind = BinaryKind(raw_kind)
    except ValueError as exc:
        raise ValueError(f"unsupported binary frame kind: {raw_kind}") from exc
    payload = value[header_bytes:]
    if len(payload) > MAX_PAYLOAD_BYTES:
        raise ValueError("binary payload exceeds 2 MiB")
    return BinaryFrame(kind, flags, sequence, timestamp_ms, payload)
