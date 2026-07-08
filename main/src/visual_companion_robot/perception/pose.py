"""YOLOv8 Pose RKNN 推理、关键点后处理与保守动作语义。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import cv2
import numpy as np

from .yolo_v5 import YoloLetterboxTransform


POSE_INPUT_SIZE = (640, 640)
KEYPOINT_NAMES = (
    "nose", "left_eye", "right_eye", "left_ear", "right_ear",
    "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
    "left_wrist", "right_wrist", "left_hip", "right_hip", "left_knee",
    "right_knee", "left_ankle", "right_ankle",
)


class PoseRuntimeError(RuntimeError):
    """人体姿态模型加载或推理失败。"""


@dataclass(frozen=True)
class PosePerson:
    confidence: float
    bbox: tuple[int, int, int, int]
    keypoints: tuple[tuple[float, float, float], ...]
    actions: tuple[str, ...]
    overall_state: str


class PoseEstimator:
    """只在 RK3588 NPU 上运行官方 YOLOv8n-pose RKNN。"""

    def __init__(self, model_path: Path, confidence_threshold: float = 0.5) -> None:
        self._model_path = model_path
        self._confidence_threshold = confidence_threshold
        self._model = None

    def load(self) -> None:
        if not self._model_path.is_file():
            raise PoseRuntimeError(f"姿态模型不存在：{self._model_path}")
        try:
            from rknnlite.api import RKNNLite
        except ImportError as exc:
            raise PoseRuntimeError("板端缺少 rknn-toolkit-lite2，不能启动姿态识别") from exc
        model = RKNNLite()
        if model.load_rknn(str(self._model_path)) != 0:
            raise PoseRuntimeError("姿态 RKNN 模型加载失败")
        if model.init_runtime() != 0:
            model.release()
            raise PoseRuntimeError("姿态 RKNN 运行时初始化失败")
        self._model = model

    def is_loaded(self) -> bool:
        return self._model is not None

    def close(self) -> None:
        if self._model is not None:
            self._model.release()
        self._model = None

    def analyze(self, image: np.ndarray) -> list[PosePerson]:
        if self._model is None:
            raise PoseRuntimeError("姿态模型尚未加载")
        prepared, transform = _letterbox(image, POSE_INPUT_SIZE, 56)
        rgb = cv2.cvtColor(prepared, cv2.COLOR_BGR2RGB)
        outputs = self._model.inference(inputs=[np.expand_dims(rgb, axis=0)])
        if not outputs:
            raise PoseRuntimeError("姿态 RKNN 没有返回输出")
        return postprocess_yolov8_pose(
            outputs,
            frame_size=(image.shape[1], image.shape[0]),
            transform=transform,
            confidence_threshold=self._confidence_threshold,
        )


def postprocess_yolov8_pose(
    outputs: Sequence[np.ndarray],
    frame_size: tuple[int, int],
    transform: YoloLetterboxTransform,
    confidence_threshold: float = 0.5,
    iou_threshold: float = 0.4,
) -> list[PosePerson]:
    heads = sorted(
        [
            np.asarray(value, dtype=np.float32)
            for value in outputs
            if np.asarray(value).ndim == 4 and np.asarray(value).shape[1] == 65
        ],
        key=lambda value: value.shape[-1],
        reverse=True,
    )
    keypoint_outputs = [
        np.asarray(value, dtype=np.float32)
        for value in outputs
        if (
            (np.asarray(value).ndim == 3 and 51 in np.asarray(value).shape)
            or (np.asarray(value).ndim == 4 and np.asarray(value).shape[1:3] == (17, 3))
        )
    ]
    if len(heads) != 3 or len(keypoint_outputs) != 1:
        raise PoseRuntimeError(f"姿态输出形状无效：{[tuple(np.asarray(v).shape) for v in outputs]}")
    keypoints = _normalize_keypoint_output(keypoint_outputs[0])

    candidates: list[tuple[float, np.ndarray, np.ndarray]] = []
    cell_offset = 0
    for head in heads:
        if head.shape[0] != 1 or head.shape[1] != 65 or head.shape[2] != head.shape[3]:
            raise PoseRuntimeError(f"姿态检测头形状无效：{tuple(head.shape)}")
        grid_size = head.shape[2]
        cells = grid_size * grid_size
        stride = POSE_INPUT_SIZE[0] / grid_size
        flat = head.reshape(1, 65, cells)
        scores = _sigmoid(flat[0, 64])
        for cell in np.flatnonzero(scores >= confidence_threshold):
            row, column = divmod(int(cell), grid_size)
            distribution = flat[0, :64, cell].reshape(4, 16)
            distances = (_softmax(distribution, axis=1) * np.arange(16, dtype=np.float32)).sum(axis=1)
            center = np.asarray([column + 0.5, row + 0.5], dtype=np.float32)
            box = np.asarray(
                [center[0] - distances[0], center[1] - distances[1],
                 center[0] + distances[2], center[1] + distances[3]],
                dtype=np.float32,
            ) * stride
            pose = keypoints[:, cell_offset + cell].reshape(17, 3).copy()
            candidates.append((float(scores[cell]), box, pose))
        cell_offset += cells
    if cell_offset != keypoints.shape[1]:
        raise PoseRuntimeError("姿态关键点数量与检测头不匹配")

    selected = _nms(candidates, iou_threshold)
    frame_width, frame_height = frame_size
    people: list[PosePerson] = []
    for confidence, box, pose in selected:
        projected_box = _project_box(box, transform, frame_width, frame_height)
        projected_pose = _project_keypoints(pose, transform, frame_width, frame_height)
        actions, overall_state = classify_pose(projected_pose, projected_box)
        people.append(PosePerson(confidence, projected_box, projected_pose, actions, overall_state))
    return people


def classify_pose(
    keypoints: tuple[tuple[float, float, float], ...],
    bbox: tuple[int, int, int, int],
    minimum_confidence: float = 0.35,
) -> tuple[tuple[str, ...], str]:
    """只输出能由单帧骨架支持的保守状态，不推断复杂行为意图。"""

    if len(keypoints) != 17:
        return (), "unknown"
    actions: list[str] = []
    left_shoulder, right_shoulder = keypoints[5], keypoints[6]
    left_wrist, right_wrist = keypoints[9], keypoints[10]
    if _visible(left_wrist, minimum_confidence) and _visible(left_shoulder, minimum_confidence):
        if left_wrist[1] < left_shoulder[1]:
            actions.append("left_hand_raised")
    if _visible(right_wrist, minimum_confidence) and _visible(right_shoulder, minimum_confidence):
        if right_wrist[1] < right_shoulder[1]:
            actions.append("right_hand_raised")

    shoulders = _midpoint(left_shoulder, right_shoulder, minimum_confidence)
    hips = _midpoint(keypoints[11], keypoints[12], minimum_confidence)
    if shoulders and hips:
        torso_height = max(1.0, abs(hips[1] - shoulders[1]))
        if abs(shoulders[0] - hips[0]) > torso_height * 0.35:
            actions.append("leaning")

    overall_state = _standing_or_sitting(keypoints, bbox, minimum_confidence)
    return tuple(actions), overall_state


def _standing_or_sitting(
    keypoints: tuple[tuple[float, float, float], ...],
    bbox: tuple[int, int, int, int],
    minimum_confidence: float,
) -> str:
    hips = _midpoint(keypoints[11], keypoints[12], minimum_confidence)
    knees = _midpoint(keypoints[13], keypoints[14], minimum_confidence)
    ankles = _midpoint(keypoints[15], keypoints[16], minimum_confidence)
    if not hips or not knees:
        return "unknown"
    box_height = max(1, bbox[3] - bbox[1])
    thigh_pairs = [
        (keypoints[11], keypoints[13]),
        (keypoints[12], keypoints[14]),
    ]
    visible_thighs = [
        (abs(knee[0] - hip[0]), abs(knee[1] - hip[1]))
        for hip, knee in thigh_pairs
        if _visible(hip, minimum_confidence) and _visible(knee, minimum_confidence)
    ]
    horizontal_thigh = sum(item[0] for item in visible_thighs) / len(visible_thighs)
    vertical_thigh = sum(item[1] for item in visible_thighs) / len(visible_thighs)
    if horizontal_thigh > vertical_thigh * 0.85:
        return "sitting"
    if ankles and ankles[1] > knees[1] > hips[1] and vertical_thigh > box_height * 0.12:
        return "standing"
    return "unknown"


def _letterbox(
    image: np.ndarray, size: tuple[int, int], pad_value: int
) -> tuple[np.ndarray, YoloLetterboxTransform]:
    target_width, target_height = size
    height, width = image.shape[:2]
    scale = min(target_width / width, target_height / height)
    resized_width, resized_height = max(1, int(width * scale)), max(1, int(height * scale))
    resized = cv2.resize(image, (resized_width, resized_height), interpolation=cv2.INTER_AREA)
    pad_x, pad_y = (target_width - resized_width) // 2, (target_height - resized_height) // 2
    canvas = np.full((target_height, target_width, 3), pad_value, dtype=np.uint8)
    canvas[pad_y:pad_y + resized_height, pad_x:pad_x + resized_width] = resized
    return canvas, YoloLetterboxTransform(scale, pad_x, pad_y)


def _normalize_keypoint_output(value: np.ndarray) -> np.ndarray:
    if value.shape[0] != 1:
        raise PoseRuntimeError(f"姿态关键点形状无效：{tuple(value.shape)}")
    if value.ndim == 4 and value.shape[1:3] == (17, 3):
        return value[0].reshape(51, value.shape[3])
    squeezed = value[0]
    if squeezed.shape[0] == 51:
        return squeezed
    if squeezed.shape[1] == 51:
        return squeezed.T
    raise PoseRuntimeError(f"姿态关键点形状无效：{tuple(value.shape)}")


def _project_box(
    box: np.ndarray, transform: YoloLetterboxTransform, frame_width: int, frame_height: int
) -> tuple[int, int, int, int]:
    x1, y1, x2, y2 = box
    projected = (
        (x1 - transform.pad_x) / transform.scale,
        (y1 - transform.pad_y) / transform.scale,
        (x2 - transform.pad_x) / transform.scale,
        (y2 - transform.pad_y) / transform.scale,
    )
    return (
        int(np.clip(round(projected[0]), 0, frame_width - 1)),
        int(np.clip(round(projected[1]), 0, frame_height - 1)),
        int(np.clip(round(projected[2]), 0, frame_width - 1)),
        int(np.clip(round(projected[3]), 0, frame_height - 1)),
    )


def _project_keypoints(
    keypoints: np.ndarray,
    transform: YoloLetterboxTransform,
    frame_width: int,
    frame_height: int,
) -> tuple[tuple[float, float, float], ...]:
    result = []
    for x, y, confidence in keypoints:
        projected_x = float(np.clip((x - transform.pad_x) / transform.scale, 0, frame_width - 1))
        projected_y = float(np.clip((y - transform.pad_y) / transform.scale, 0, frame_height - 1))
        score = float(confidence if 0 <= confidence <= 1 else _sigmoid(np.asarray(confidence)))
        result.append((round(projected_x, 2), round(projected_y, 2), round(score, 4)))
    return tuple(result)


def _nms(
    candidates: list[tuple[float, np.ndarray, np.ndarray]], iou_threshold: float
) -> list[tuple[float, np.ndarray, np.ndarray]]:
    ordered = sorted(candidates, key=lambda item: item[0], reverse=True)
    selected: list[tuple[float, np.ndarray, np.ndarray]] = []
    while ordered and len(selected) < 10:
        current = ordered.pop(0)
        selected.append(current)
        ordered = [item for item in ordered if _iou(current[1], item[1]) <= iou_threshold]
    return selected


def _iou(first: np.ndarray, second: np.ndarray) -> float:
    top_left = np.maximum(first[:2], second[:2])
    bottom_right = np.minimum(first[2:], second[2:])
    size = np.maximum(0.0, bottom_right - top_left)
    intersection = float(size[0] * size[1])
    first_area = float(np.prod(np.maximum(0.0, first[2:] - first[:2])))
    second_area = float(np.prod(np.maximum(0.0, second[2:] - second[:2])))
    union = first_area + second_area - intersection
    return intersection / union if union > 0 else 0.0


def _sigmoid(value: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(value, -30.0, 30.0)))


def _softmax(value: np.ndarray, axis: int) -> np.ndarray:
    shifted = value - np.max(value, axis=axis, keepdims=True)
    exponent = np.exp(shifted)
    return exponent / np.sum(exponent, axis=axis, keepdims=True)


def _visible(point: tuple[float, float, float], threshold: float) -> bool:
    return point[2] >= threshold


def _midpoint(
    first: tuple[float, float, float],
    second: tuple[float, float, float],
    threshold: float,
) -> tuple[float, float] | None:
    if not _visible(first, threshold) or not _visible(second, threshold):
        return None
    return ((first[0] + second[0]) / 2.0, (first[1] + second[1]) / 2.0)
