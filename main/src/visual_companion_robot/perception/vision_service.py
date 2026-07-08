"""统一板端视觉模块：严格校验图像并组合 RKNN 场景与本机 FER+ 结果。"""

from __future__ import annotations

import base64
import binascii
import json
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol

import cv2
import numpy as np

from .scene_analyzer import SceneAnalyzer, SceneAnalyzerConfig
from .pose import PoseEstimator, PosePerson


MAX_DECODED_IMAGE_BYTES = 1536 * 1024
MAX_IMAGE_PIXELS = 12_000_000
INFERENCE_LOCK_TIMEOUT_SECONDS = 5.0
SEMANTIC_MAX_AGE_SECONDS = 12.0
SEMANTIC_FRAME_DISTANCE_LIMIT = 48.0
SEMANTIC_CHANGED_SCENE_MIN_INTERVAL_SECONDS = 1.0
HUMAN_CLAIM_TERMS = (
    "人", "男子", "女子", "男孩", "女孩", "男士", "女士", "人物", "孩子", "儿童", "老人", "青年", "中年",
    "宇航员", "顾客", "游客", "行人", "说话者", "说话人",
)
HUMAN_NEGATION_TERMS = (
    "无人", "没有人", "未见人", "未发现人", "未检测到人", "没有明显人物", "无明显人物", "未见人物",
)
ANIMAL_CLAIM_TERMS = {
    "cat": ("猫",),
    "dog": ("狗", "犬"),
}


class VisionServiceError(RuntimeError):
    """板端视觉模块无法完成请求。"""


class VisionInputError(ValueError):
    """客户端图像不符合视觉接口契约。"""


class VisionBusyError(VisionServiceError):
    """上一帧仍在推理，当前帧不能进入 NPU。"""


class EmotionProvider(Protocol):
    def health(self) -> Mapping[str, Any]: ...

    def classify(self, image_base64: str) -> Mapping[str, Any]: ...


class SemanticProvider(Protocol):
    def health(self) -> Mapping[str, Any]: ...

    def describe(self, image_base64: str) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class VisionServiceConfig:
    model_path: Path
    pose_model_path: Path | None = None
    emotion_service_url: str = "http://127.0.0.1:8766"
    semantic_service_url: str | None = None
    semantic_refresh_seconds: float = 6.0
    confidence_threshold: float = 0.5


class HttpEmotionProvider:
    """通过板内回环地址访问 FER+，不向客户端暴露第二个端口。"""

    def __init__(self, base_url: str, timeout_seconds: float = 20.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds

    def health(self) -> Mapping[str, Any]:
        return self._request("GET", "/health")

    def classify(self, image_base64: str) -> Mapping[str, Any]:
        body = json.dumps({"image": image_base64}, separators=(",", ":")).encode("utf-8")
        return self._request("POST", "/emotion", body)

    def _request(self, method: str, path: str, body: bytes | None = None) -> Mapping[str, Any]:
        request = urllib.request.Request(
            f"{self._base_url}{path}",
            data=body,
            headers={"Content-Type": "application/json"} if body else {},
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise VisionServiceError(f"FER+ 服务 HTTP {exc.code}：{detail}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            reason = getattr(exc, "reason", exc)
            raise VisionServiceError(f"FER+ 服务不可用：{reason}") from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise VisionServiceError("FER+ 服务返回了无效 JSON") from exc
        if not isinstance(payload, dict):
            raise VisionServiceError("FER+ 服务返回值必须是 JSON 对象")
        return payload


class HttpSemanticProvider:
    """访问板内常驻 RKLLM VLM；该请求仅由低频后台任务调用。"""

    def __init__(self, base_url: str, timeout_seconds: float = 25.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds

    def health(self) -> Mapping[str, Any]:
        return self._request("GET", "/health")

    def describe(self, image_base64: str) -> Mapping[str, Any]:
        body = json.dumps({"image": image_base64}, separators=(",", ":")).encode("utf-8")
        return self._request("POST", "/analyze", body)

    def _request(self, method: str, path: str, body: bytes | None = None) -> Mapping[str, Any]:
        request = urllib.request.Request(
            f"{self._base_url}{path}",
            data=body,
            headers={"Content-Type": "application/json"} if body else {},
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise VisionServiceError(f"语义视觉服务 HTTP {exc.code}：{detail}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            reason = getattr(exc, "reason", exc)
            raise VisionServiceError(f"语义视觉服务不可用：{reason}") from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise VisionServiceError("语义视觉服务返回了无效 JSON") from exc
        if not isinstance(payload, dict):
            raise VisionServiceError("语义视觉服务返回值必须是 JSON 对象")
        return payload


class BoardVisionService:
    """向 HTTP 层提供 load/health/analyze 三个稳定操作。"""

    def __init__(
        self,
        config: VisionServiceConfig,
        analyzer: SceneAnalyzer | None = None,
        pose_estimator: PoseEstimator | None = None,
        emotion_provider: EmotionProvider | None = None,
        semantic_provider: SemanticProvider | None = None,
    ) -> None:
        self._config = config
        self._analyzer = analyzer or SceneAnalyzer(
            SceneAnalyzerConfig(
                yolo_model_path=str(config.model_path),
                conf_threshold=config.confidence_threshold,
            )
        )
        self._emotion = emotion_provider or HttpEmotionProvider(config.emotion_service_url)
        self._pose = pose_estimator or (
            PoseEstimator(config.pose_model_path) if config.pose_model_path is not None else None
        )
        self._semantic = semantic_provider or (
            HttpSemanticProvider(config.semantic_service_url)
            if config.semantic_service_url
            else None
        )
        self._inference_lock = threading.Lock()
        self._cpu_executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="vision-face",
        )
        self._semantic_executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="vision-semantic",
        )
        self._semantic_lock = threading.Lock()
        self._semantic_future: Future[Mapping[str, Any]] | None = None
        self._semantic_result: dict[str, Any] = {}
        self._semantic_signature: bytes | None = None
        self._semantic_requested_signature: bytes | None = None
        self._semantic_started_at = 0.0
        self._semantic_completed_at = 0.0
        self._semantic_error = ""

    def load(self) -> None:
        if not self._config.model_path.is_file():
            raise VisionServiceError(f"RKNN 视觉模型不存在：{self._config.model_path}")
        self._analyzer.load()
        if self._pose is not None:
            self._pose.load()
        health = self._emotion.health()
        if health.get("ok") is not True:
            raise VisionServiceError(f"FER+ 服务未就绪：{health.get('error') or health}")
        if self._semantic is not None:
            semantic_health = self._semantic.health()
            if semantic_health.get("ok") is not True:
                raise VisionServiceError(
                    f"语义视觉服务未就绪：{semantic_health.get('error') or semantic_health}"
                )

    def close(self) -> None:
        self._analyzer.unload()
        if self._pose is not None:
            self._pose.close()
        self._cpu_executor.shutdown(wait=True, cancel_futures=True)
        self._semantic_executor.shutdown(wait=True, cancel_futures=True)

    def health(self) -> dict[str, Any]:
        emotion_health = self._emotion.health()
        scene_ready = self._analyzer.is_loaded()
        emotion_ready = emotion_health.get("ok") is True
        pose_ready = self._pose is not None and self._pose.is_loaded()
        semantic_health = self._semantic.health() if self._semantic is not None else {"ok": True}
        semantic_ready = semantic_health.get("ok") is True
        return {
            "ok": scene_ready and pose_ready and emotion_ready and semantic_ready,
            "backend": "elf2-local-yolo-pose-yunet-sface-ferplus",
            "scene_backend": "rknn-yolov5s",
            "pose_backend": "rknn-yolov8n-pose",
            "face_backend": str(emotion_health.get("backend") or "yunet-sface-ferplus-local"),
            "emotion_backend": str(emotion_health.get("emotion") or "ferplus-onnx"),
            "semantic_backend": str(semantic_health.get("backend") or "disabled"),
            "semantic_ready": semantic_ready,
            "model_path": str(self._config.model_path),
            "loaded": scene_ready,
        }

    def analyze(self, image_base64: str) -> dict[str, Any]:
        image = _decode_image(image_base64)
        if not self._inference_lock.acquire(timeout=INFERENCE_LOCK_TIMEOUT_SECONDS):
            raise VisionBusyError("本地视觉仍在处理上一帧，请稍后重试")
        started_at = time.perf_counter()
        emotion_future: Future[Mapping[str, Any]] | None = None
        try:
            if not self._analyzer.is_loaded():
                raise VisionServiceError("RKNN 视觉模型尚未加载")
            # 人脸/身份/情绪走 CPU，可与两个顺序 NPU 任务重叠，缩短视频帧总延迟。
            emotion_future = self._cpu_executor.submit(self._emotion.classify, image_base64)
            frame = self._analyzer.analyze(image)
            poses = self._pose.analyze(image) if self._pose is not None else []
            emotion = emotion_future.result()
        except Exception:
            if emotion_future is not None and not emotion_future.cancel():
                try:
                    emotion_future.result()
                except Exception:
                    pass
            raise
        finally:
            self._inference_lock.release()

        if "emotion" not in emotion or "has_face" not in emotion:
            raise VisionServiceError("FER+ 服务响应缺少 emotion 或 has_face")
        faces = list(emotion.get("faces") or [])[:5]
        focus_index = emotion.get("focus_face_index")
        focus_face = (
            faces[focus_index]
            if isinstance(focus_index, int) and 0 <= focus_index < len(faces)
            else None
        )
        pose_records = [_pose_record(item) for item in poses]
        pose_activity = _pose_activity(poses)
        frame_signature = _frame_signature(image)
        self._schedule_semantic(image_base64, frame_signature)
        semantic = self._semantic_snapshot(
            current_signature=frame_signature,
            person_count=frame.person_count,
            has_face=bool(emotion["has_face"]),
            objects_detected=frame.objects_detected,
        )
        return {
            "ok": True,
            "backend": "elf2-local-yolo-pose-yunet-sface-ferplus",
            "timestamp": frame.timestamp,
            "latency_ms": round((time.perf_counter() - started_at) * 1000.0, 1),
            "frame_width": frame.frame_width,
            "frame_height": frame.frame_height,
            "scene_caption": frame.scene_caption,
            "person_activity": pose_activity or frame.person_activity,
            "scene_person_activity": frame.person_activity,
            "person_count": frame.person_count,
            "objects_detected": frame.objects_detected,
            "objects": [
                {
                    "label": item.label,
                    "confidence": round(float(item.confidence), 4),
                }
                for item in frame.objects
            ],
            "has_face": bool(emotion["has_face"]),
            "emotion": str(emotion["emotion"]),
            "confidence": round(float(emotion.get("confidence") or 0.0), 4),
            "full_scores": {
                str(key): round(float(value), 4)
                for key, value in dict(emotion.get("full_scores") or {}).items()
            },
            "faces": faces,
            "focus_face_index": focus_index if focus_face is not None else None,
            "focus_face": focus_face,
            "focus_reason": str(emotion.get("focus_reason") or "no_face"),
            "active_speaker": dict(emotion.get("active_speaker") or {"status": "unknown"}),
            "poses": pose_records,
            "person_actions": sorted({action for item in poses for action in item.actions}),
            "body_state": poses[0].overall_state if poses else "unknown",
            **semantic,
        }

    def _schedule_semantic(self, image_base64: str, frame_signature: bytes) -> None:
        if self._semantic is None:
            return
        now = time.monotonic()
        with self._semantic_lock:
            if self._semantic_future is not None and not self._semantic_future.done():
                return
            scene_changed = (
                self._semantic_requested_signature is None
                or _frame_signature_distance(frame_signature, self._semantic_requested_signature)
                > SEMANTIC_FRAME_DISTANCE_LIMIT
            )
            refresh_interval = (
                min(
                    self._config.semantic_refresh_seconds,
                    SEMANTIC_CHANGED_SCENE_MIN_INTERVAL_SECONDS,
                )
                if scene_changed
                else self._config.semantic_refresh_seconds
            )
            if now - self._semantic_started_at < refresh_interval:
                return
            self._semantic_started_at = now
            self._semantic_requested_signature = frame_signature
            future = self._semantic_executor.submit(self._semantic.describe, image_base64)
            self._semantic_future = future
        # Future 可能在 add_done_callback 前已完成；必须在锁外注册，避免同步回调自锁。
        future.add_done_callback(
            lambda completed, signature=frame_signature: self._store_semantic_result(completed, signature)
        )

    def _store_semantic_result(self, future: Future[Mapping[str, Any]], frame_signature: bytes) -> None:
        try:
            payload = future.result()
            caption = " ".join(str(payload.get("semantic_caption") or "").split())[:400]
            if payload.get("ok") is not True or not caption:
                raise VisionServiceError(str(payload.get("error") or "语义视觉返回空描述"))
            result = {
                "semantic_caption": caption,
                "semantic_backend": str(payload.get("backend") or "rk3588-local-vlm")[:80],
            }
            error = ""
        except Exception as exc:  # 后台失败不能破坏实时 YOLO/人脸响应。
            result = {}
            error = str(exc)[:240]
        with self._semantic_lock:
            if result:
                self._semantic_result = result
                self._semantic_signature = frame_signature
                self._semantic_completed_at = time.monotonic()
            self._semantic_error = error

    def _semantic_snapshot(
        self,
        *,
        current_signature: bytes | None = None,
        person_count: int | None = None,
        has_face: bool | None = None,
        objects_detected: list[str] | None = None,
    ) -> dict[str, Any]:
        if self._semantic is None:
            return {"semantic_status": "disabled"}
        with self._semantic_lock:
            result = dict(self._semantic_result)
            running = self._semantic_future is not None and not self._semantic_future.done()
            completed_at = self._semantic_completed_at
            error = self._semantic_error
            semantic_signature = self._semantic_signature
        if result:
            age_seconds = max(0.0, time.monotonic() - completed_at)
            if age_seconds > SEMANTIC_MAX_AGE_SECONDS:
                return {"semantic_status": "refreshing" if running else "stale"}
            if (
                current_signature is not None
                and semantic_signature is not None
                and _frame_signature_distance(current_signature, semantic_signature)
                > SEMANTIC_FRAME_DISTANCE_LIMIT
            ):
                return {"semantic_status": "refreshing" if running else "stale_frame"}
            caption = str(result.get("semantic_caption") or "")
            if person_count == 0 and has_face is False and _caption_claims_human(caption):
                return {
                    "semantic_status": "conflict",
                    "semantic_error": "语义人物描述与本地人物检测结果冲突，已阻止进入上下文",
                }
            animal_conflict = _animal_caption_conflict(caption, objects_detected or [])
            if animal_conflict:
                return {
                    "semantic_status": "conflict",
                    "semantic_error": animal_conflict,
                }
            result["semantic_status"] = "refreshing" if running else "ready"
            result["semantic_age_ms"] = round(age_seconds * 1000.0, 1)
            return result
        if error:
            return {"semantic_status": "error", "semantic_error": error}
        return {"semantic_status": "warming" if running else "pending"}


def _frame_signature(image: np.ndarray) -> bytes:
    """生成便宜的彩色缩略帧指纹，用于阻止上一场景的 VLM 描述污染当前画面。"""

    reduced = cv2.resize(image, (12, 12), interpolation=cv2.INTER_AREA)
    return bytes(reduced.reshape(-1).tolist())


def _frame_signature_distance(left: bytes, right: bytes) -> float:
    if len(left) != len(right) or not left:
        return 255.0
    return sum(abs(a - b) for a, b in zip(left, right, strict=True)) / len(left)


def _caption_claims_human(caption: str) -> bool:
    normalized = str(caption or "")
    for term in HUMAN_NEGATION_TERMS:
        normalized = normalized.replace(term, "")
    return any(term in normalized for term in HUMAN_CLAIM_TERMS)


def _animal_caption_conflict(caption: str, objects_detected: list[str]) -> str:
    labels = set(objects_detected)
    if not labels:
        return ""
    claims = {
        label
        for label, terms in ANIMAL_CLAIM_TERMS.items()
        if any(term in caption for term in terms)
    }
    if "cat" in labels and "dog" not in labels and "dog" in claims and "cat" not in claims:
        return "语义把本地检测到的猫描述成狗，已阻止进入上下文"
    if "dog" in labels and "cat" not in labels and "cat" in claims and "dog" not in claims:
        return "语义把本地检测到的狗描述成猫，已阻止进入上下文"
    return ""


def _pose_record(person: PosePerson) -> dict[str, Any]:
    return {
        "confidence": round(float(person.confidence), 4),
        "bbox": list(person.bbox),
        "keypoints": [list(point) for point in person.keypoints],
        "actions": list(person.actions),
        "overall_state": person.overall_state,
    }


def _pose_activity(people: list[PosePerson]) -> str:
    if not people:
        return ""
    labels = {
        "left_hand_raised": "举起左手",
        "right_hand_raised": "举起右手",
        "leaning": "身体倾斜",
        "standing": "站立",
        "sitting": "坐姿",
    }
    primary = people[0]
    descriptions = [labels[action] for action in primary.actions if action in labels]
    if primary.overall_state in labels:
        descriptions.append(labels[primary.overall_state])
    return "主要人物姿态：" + "、".join(descriptions) if descriptions else ""


def _decode_image(image_base64: str) -> np.ndarray:
    if not isinstance(image_base64, str) or not image_base64:
        raise VisionInputError("缺少非空 image 字段")
    if len(image_base64) > MAX_DECODED_IMAGE_BYTES * 4 // 3 + 8:
        raise VisionInputError("图片超过 1.5 MiB 限制")
    try:
        image_bytes = base64.b64decode(image_base64, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise VisionInputError("image 必须是有效 Base64") from exc
    if not image_bytes or len(image_bytes) > MAX_DECODED_IMAGE_BYTES:
        raise VisionInputError("图片为空或超过 1.5 MiB 限制")
    image = cv2.imdecode(np.frombuffer(image_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None or image.size == 0:
        raise VisionInputError("图片解码失败，只接受 JPEG/PNG 图像")
    height, width = image.shape[:2]
    if width * height > MAX_IMAGE_PIXELS:
        raise VisionInputError("图片像素数超过 1200 万限制")
    return image
