"""板端人脸分析：YuNet 检测、SFace 身份特征与 FER+ 情绪。"""

from __future__ import annotations

import sqlite3
import threading
import uuid
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

import cv2
import numpy as np

from .emotion import EmotionResult, FerPlusEmotionRecognizer


MAX_FACES = 5
DEFAULT_IDENTITY_THRESHOLD = 0.42


class FaceAnalysisError(RuntimeError):
    """本地人脸分析无法完成。"""


class FaceEnrollmentError(ValueError):
    """输入不满足身份登记要求。"""


class FaceDetector(Protocol):
    def setInputSize(self, input_size: tuple[int, int]) -> None: ...

    def detect(self, image: np.ndarray) -> tuple[Any, np.ndarray | None]: ...


class FaceRecognizer(Protocol):
    def alignCrop(self, image: np.ndarray, face: np.ndarray) -> np.ndarray: ...

    def feature(self, aligned_face: np.ndarray) -> np.ndarray: ...


@dataclass(frozen=True)
class FaceProfile:
    profile_id: str
    name: str
    similarity: float


@dataclass(frozen=True)
class FaceTrack:
    track_id: int
    crops: tuple[np.ndarray, ...]
    profile_id: str | None
    name: str | None


class FaceProfileStore:
    """只在 ELF2 SQLite 中保存命名身份的归一化特征，不保存原始照片。"""

    def __init__(self, database_path: Path, threshold: float = DEFAULT_IDENTITY_THRESHOLD) -> None:
        self._database_path = database_path
        self._threshold = threshold
        self._lock = threading.Lock()

    def initialize(self) -> None:
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS face_profiles (
                        profile_id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        embedding BLOB NOT NULL,
                        embedding_size INTEGER NOT NULL,
                        created_at TEXT NOT NULL
                    )
                    """
                )

    def enroll(self, name: str, embedding: np.ndarray) -> FaceProfile:
        clean_name = " ".join(str(name).strip().split())
        if not clean_name or len(clean_name) > 40:
            raise FaceEnrollmentError("身份名称长度必须为 1–40 个字符")
        vector = _normalized_embedding(embedding)
        profile_id = uuid.uuid4().hex[:12]
        created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._lock, closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    "INSERT INTO face_profiles VALUES (?, ?, ?, ?, ?)",
                    (profile_id, clean_name, vector.tobytes(), vector.size, created_at),
                )
        return FaceProfile(profile_id, clean_name, 1.0)

    def match(self, embedding: np.ndarray) -> FaceProfile | None:
        vector = _normalized_embedding(embedding)
        best: FaceProfile | None = None
        with self._lock, closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT profile_id, name, embedding, embedding_size FROM face_profiles"
            ).fetchall()
        for profile_id, name, raw_embedding, embedding_size in rows:
            candidate = np.frombuffer(raw_embedding, dtype=np.float32, count=int(embedding_size))
            if candidate.size != vector.size:
                continue
            similarity = float(np.dot(vector, candidate))
            if similarity >= self._threshold and (best is None or similarity > best.similarity):
                best = FaceProfile(str(profile_id), str(name), similarity)
        return best

    def list_profiles(self) -> list[dict[str, str]]:
        with self._lock, closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT profile_id, name, created_at FROM face_profiles ORDER BY created_at"
            ).fetchall()
        return [
            {"profile_id": str(profile_id), "name": str(name), "created_at": str(created_at)}
            for profile_id, name, created_at in rows
        ]

    def delete(self, profile_id: str) -> bool:
        with self._lock, closing(self._connect()) as connection:
            with connection:
                cursor = connection.execute(
                    "DELETE FROM face_profiles WHERE profile_id = ?", (str(profile_id),)
                )
        return cursor.rowcount == 1

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._database_path, timeout=5.0)


class LocalFaceAnalyzer:
    """封装完整人脸链路，并只暴露稳定的 load/analyze/enroll 接口。"""

    def __init__(
        self,
        yunet_model_path: Path,
        sface_model_path: Path,
        emotion_recognizer: FerPlusEmotionRecognizer,
        profile_store: FaceProfileStore,
        detector: FaceDetector | None = None,
        recognizer: FaceRecognizer | None = None,
    ) -> None:
        self._yunet_model_path = yunet_model_path
        self._sface_model_path = sface_model_path
        self._emotion = emotion_recognizer
        self._profiles = profile_store
        self._detector = detector
        self._recognizer = recognizer
        self._lock = threading.Lock()

    def load(self) -> None:
        if self._detector is None:
            if not self._yunet_model_path.is_file():
                raise FaceAnalysisError(f"YuNet 模型不存在：{self._yunet_model_path}")
            self._detector = cv2.FaceDetectorYN_create(
                str(self._yunet_model_path), "", (320, 320), 0.75, 0.3, 5000
            )
        if self._recognizer is None:
            if not self._sface_model_path.is_file():
                raise FaceAnalysisError(f"SFace 模型不存在：{self._sface_model_path}")
            self._recognizer = cv2.FaceRecognizerSF_create(str(self._sface_model_path), "")
        self._profiles.initialize()

    def is_loaded(self) -> bool:
        return self._detector is not None and self._recognizer is not None and self._emotion.is_loaded()

    def analyze(self, image: np.ndarray) -> dict[str, Any]:
        with self._lock:
            faces = self._detect(image)
            records = [self._analyze_face(image, face) for face in faces]
        focus_index = _select_focus_face(records, image.shape[1], image.shape[0])
        return {
            "has_face": bool(records),
            "faces": records,
            "focus_face_index": focus_index,
            "focus_reason": "largest_center_face" if focus_index is not None else "no_face",
            "active_speaker": {
                "status": "unknown",
                "reason": "single_frame_has_no_audio_visual_timing",
            },
        }

    def enroll(self, image: np.ndarray, name: str) -> FaceProfile:
        with self._lock:
            faces = self._detect(image)
            if len(faces) != 1:
                raise FaceEnrollmentError("身份登记画面必须且只能包含一张清晰人脸")
            feature = self._extract_feature(image, faces[0])
            return self._profiles.enroll(name, feature)

    def list_profiles(self) -> list[dict[str, str]]:
        return self._profiles.list_profiles()

    def delete_profile(self, profile_id: str) -> bool:
        return self._profiles.delete(profile_id)

    def track_faces(self, images: list[np.ndarray]) -> list[FaceTrack]:
        """用 SFace 特征关联短片中的人脸，并填补少量漏检帧。"""

        if len(images) < 2:
            return []
        tracks: list[dict[str, Any]] = []
        with self._lock:
            for frame_index, image in enumerate(images):
                observations = [
                    (face, _face_bbox(face), _speaker_face_crop(image, face))
                    for face in self._detect(image)
                ]
                for track in tracks:
                    track["crops"].append(None)
                available = set(range(len(tracks)))
                for face, bbox, crop in observations:
                    match_index = _best_bbox_track(bbox, tracks, available)
                    feature = None
                    if match_index is None:
                        feature = self._extract_feature(image, face)
                        match_index = _best_track(feature, tracks, available)
                    if match_index is None:
                        feature = feature if feature is not None else self._extract_feature(image, face)
                        tracks.append({
                            "embedding": feature,
                            "last_bbox": bbox,
                            "crops": [None] * frame_index + [crop],
                            "detections": 1,
                        })
                        continue
                    track = tracks[match_index]
                    track["crops"][-1] = crop
                    track["last_bbox"] = bbox
                    track["detections"] += 1
                    if frame_index % 8 == 0:
                        feature = feature if feature is not None else self._extract_feature(image, face)
                        track["embedding"] = _normalized_embedding(track["embedding"] + feature)
                    available.remove(match_index)

        results: list[FaceTrack] = []
        for track_id, track in enumerate(tracks):
            if track["detections"] < 2:
                continue
            crops = _fill_missing_crops(track["crops"])
            if not crops:
                continue
            profile = self._profiles.match(track["embedding"])
            results.append(FaceTrack(
                track_id=track_id,
                crops=tuple(crops),
                profile_id=profile.profile_id if profile else None,
                name=profile.name if profile else None,
            ))
        return results

    def _detect(self, image: np.ndarray) -> list[np.ndarray]:
        if self._detector is None:
            raise FaceAnalysisError("YuNet 尚未加载")
        height, width = image.shape[:2]
        self._detector.setInputSize((width, height))
        _, detected = self._detector.detect(image)
        if detected is None:
            return []
        ordered = sorted(
            np.asarray(detected, dtype=np.float32),
            key=lambda face: float(face[2] * face[3]),
            reverse=True,
        )
        return ordered[:MAX_FACES]

    def _analyze_face(self, image: np.ndarray, face: np.ndarray) -> dict[str, Any]:
        x, y, width, height = (int(round(float(value))) for value in face[:4])
        patch = _face_patch(image, x, y, width, height)
        emotion = self._emotion.classify(patch)
        feature = self._extract_feature(image, face)
        profile = self._profiles.match(feature)
        landmarks = [
            [int(round(float(face[index]))), int(round(float(face[index + 1])))]
            for index in range(4, 14, 2)
        ]
        return {
            "bbox": [x, y, width, height],
            "landmarks": landmarks,
            "detector_confidence": round(float(face[14]), 4),
            "emotion": emotion.emotion,
            "emotion_confidence": round(float(emotion.confidence), 4),
            "emotion_scores": _rounded_scores(emotion),
            "profile_id": profile.profile_id if profile else None,
            "name": profile.name if profile else None,
            "identity_similarity": round(profile.similarity, 4) if profile else 0.0,
        }

    def _extract_feature(self, image: np.ndarray, face: np.ndarray) -> np.ndarray:
        if self._recognizer is None:
            raise FaceAnalysisError("SFace 尚未加载")
        aligned = self._recognizer.alignCrop(image, face)
        return _normalized_embedding(self._recognizer.feature(aligned))


def _normalized_embedding(embedding: np.ndarray) -> np.ndarray:
    vector = np.asarray(embedding, dtype=np.float32).reshape(-1)
    norm = float(np.linalg.norm(vector))
    if vector.size == 0 or not np.isfinite(norm) or norm <= 1e-8:
        raise FaceAnalysisError("SFace 返回了无效身份特征")
    return np.ascontiguousarray(vector / norm, dtype=np.float32)


def _face_patch(image: np.ndarray, x: int, y: int, width: int, height: int) -> np.ndarray:
    image_height, image_width = image.shape[:2]
    margin_x, margin_y = max(4, width // 8), max(4, height // 8)
    left, top = max(0, x - margin_x), max(0, y - margin_y)
    right = min(image_width, x + width + margin_x)
    bottom = min(image_height, y + height + margin_y)
    patch = image[top:bottom, left:right]
    if patch.size == 0:
        raise FaceAnalysisError("YuNet 返回了无效人脸框")
    return patch


def _select_focus_face(records: list[dict[str, Any]], frame_width: int, frame_height: int) -> int | None:
    if not records:
        return None
    center_x, center_y = frame_width / 2.0, frame_height / 2.0

    def score(record: dict[str, Any]) -> float:
        x, y, width, height = record["bbox"]
        distance = abs(x + width / 2.0 - center_x) / frame_width
        distance += abs(y + height / 2.0 - center_y) / frame_height
        return float(width * height) * max(0.5, 1.0 - distance * 0.3)

    return max(range(len(records)), key=lambda index: score(records[index]))


def _rounded_scores(result: EmotionResult) -> dict[str, float]:
    return {str(label): round(float(score), 4) for label, score in result.full_scores.items()}


def _speaker_face_crop(image: np.ndarray, face: np.ndarray) -> np.ndarray:
    x, y, width, height = (float(value) for value in face[:4])
    side = max(width, height) * 1.4
    center_x, center_y = x + width / 2.0, y + height / 2.0
    left, top = int(round(center_x - side / 2.0)), int(round(center_y - side / 2.0))
    right, bottom = int(round(center_x + side / 2.0)), int(round(center_y + side / 2.0))
    pad_left, pad_top = max(0, -left), max(0, -top)
    pad_right, pad_bottom = max(0, right - image.shape[1]), max(0, bottom - image.shape[0])
    padded = cv2.copyMakeBorder(
        image,
        pad_top,
        pad_bottom,
        pad_left,
        pad_right,
        cv2.BORDER_CONSTANT,
        value=(110, 110, 110),
    )
    left, right = left + pad_left, right + pad_left
    top, bottom = top + pad_top, bottom + pad_top
    crop = padded[top:bottom, left:right]
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    return cv2.resize(gray, (112, 112), interpolation=cv2.INTER_AREA)


def _best_track(
    feature: np.ndarray, tracks: list[dict[str, Any]], available: set[int]
) -> int | None:
    scored = [
        (float(np.dot(feature, tracks[index]["embedding"])), index)
        for index in available
    ]
    if not scored:
        return None
    similarity, index = max(scored)
    return index if similarity >= 0.35 else None


def _face_bbox(face: np.ndarray) -> tuple[float, float, float, float]:
    x, y, width, height = (float(value) for value in face[:4])
    return (x, y, x + width, y + height)


def _best_bbox_track(
    bbox: tuple[float, float, float, float], tracks: list[dict[str, Any]], available: set[int]
) -> int | None:
    scored = [(_bbox_iou(bbox, tracks[index]["last_bbox"]), index) for index in available]
    if not scored:
        return None
    overlap, index = max(scored)
    return index if overlap >= 0.25 else None


def _bbox_iou(
    first: tuple[float, float, float, float], second: tuple[float, float, float, float]
) -> float:
    x1, y1 = max(first[0], second[0]), max(first[1], second[1])
    x2, y2 = min(first[2], second[2]), min(first[3], second[3])
    intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    first_area = max(0.0, first[2] - first[0]) * max(0.0, first[3] - first[1])
    second_area = max(0.0, second[2] - second[0]) * max(0.0, second[3] - second[1])
    union = first_area + second_area - intersection
    return intersection / union if union > 0 else 0.0


def _fill_missing_crops(crops: list[np.ndarray | None]) -> list[np.ndarray]:
    known = [index for index, crop in enumerate(crops) if crop is not None]
    if not known:
        return []
    return [
        crops[min(known, key=lambda known_index: abs(known_index - index))]
        for index in range(len(crops))
    ]  # type: ignore[list-item]
