"""YOLOv5 RKNN 输出后处理。

该模块只处理纯 NumPy 数据，便于在 Windows 开发机上验证板端 NPU 输出契约。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np


YOLOV5_ANCHORS = np.asarray(
    [
        [[10, 13], [16, 30], [33, 23]],
        [[30, 61], [62, 45], [59, 119]],
        [[116, 90], [156, 198], [373, 326]],
    ],
    dtype=np.float32,
)


@dataclass(frozen=True)
class YoloCandidate:
    """已经缩放到原始图像坐标的单个候选框。"""

    class_id: int
    confidence: float
    x1: int
    y1: int
    x2: int
    y2: int


@dataclass(frozen=True)
class YoloLetterboxTransform:
    """把模型输入坐标还原到原图所需的缩放和填充信息。"""

    scale: float
    pad_x: float
    pad_y: float


def postprocess_yolov5(
    outputs: Sequence[np.ndarray],
    frame_size: tuple[int, int],
    input_size: tuple[int, int] = (640, 640),
    conf_threshold: float = 0.5,
    iou_threshold: float = 0.45,
    letterbox: YoloLetterboxTransform | None = None,
) -> list[YoloCandidate]:
    """把三个 YOLOv5 检测头转换为按类别 NMS 后的候选框。"""

    if len(outputs) != 3:
        raise ValueError(f"YOLOv5 需要 3 个输出张量，实际为 {len(outputs)} 个")
    if not 0.0 < conf_threshold < 1.0:
        raise ValueError("conf_threshold 必须在 0 和 1 之间")
    if not 0.0 < iou_threshold < 1.0:
        raise ValueError("iou_threshold 必须在 0 和 1 之间")

    input_width, input_height = input_size
    frame_width, frame_height = frame_size
    if min(input_width, input_height, frame_width, frame_height) <= 0:
        raise ValueError("图像尺寸必须为正整数")

    boxes: list[np.ndarray] = []
    confidences: list[np.ndarray] = []
    class_ids: list[np.ndarray] = []

    ordered_outputs = sorted(outputs, key=lambda value: int(value.shape[-1]), reverse=True)
    for output, anchors in zip(ordered_outputs, YOLOV5_ANCHORS):
        prediction = _normalize_head(output)
        grid_height, grid_width = prediction.shape[1:3]
        stride = np.asarray([input_width / grid_width, input_height / grid_height], dtype=np.float32)
        grid_x, grid_y = np.meshgrid(np.arange(grid_width), np.arange(grid_height))
        grid = np.stack((grid_x, grid_y), axis=-1).astype(np.float32)[np.newaxis, ...]

        activated = _activate_head(prediction)
        centers = (activated[..., 0:2] * 2.0 - 0.5 + grid) * stride
        sizes = (activated[..., 2:4] * 2.0) ** 2 * anchors[:, np.newaxis, np.newaxis, :]
        class_scores = activated[..., 4:5] * activated[..., 5:]
        best_class_ids = np.argmax(class_scores, axis=-1)
        best_confidences = np.max(class_scores, axis=-1)
        keep = best_confidences >= conf_threshold
        if not np.any(keep):
            continue

        half_sizes = sizes / 2.0
        xyxy = np.concatenate((centers - half_sizes, centers + half_sizes), axis=-1)
        boxes.append(xyxy[keep])
        confidences.append(best_confidences[keep])
        class_ids.append(best_class_ids[keep])

    if not boxes:
        return []

    all_boxes = np.concatenate(boxes, axis=0)
    all_confidences = np.concatenate(confidences, axis=0)
    all_class_ids = np.concatenate(class_ids, axis=0)
    selected = _classwise_nms(all_boxes, all_confidences, all_class_ids, iou_threshold)

    results: list[YoloCandidate] = []
    for index in selected:
        x1, y1, x2, y2 = all_boxes[index]
        if letterbox is None:
            x1, x2 = x1 * frame_width / input_width, x2 * frame_width / input_width
            y1, y2 = y1 * frame_height / input_height, y2 * frame_height / input_height
        else:
            if letterbox.scale <= 0:
                raise ValueError("letterbox.scale 必须大于 0")
            x1, x2 = (x1 - letterbox.pad_x) / letterbox.scale, (x2 - letterbox.pad_x) / letterbox.scale
            y1, y2 = (y1 - letterbox.pad_y) / letterbox.scale, (y2 - letterbox.pad_y) / letterbox.scale
        results.append(
            YoloCandidate(
                class_id=int(all_class_ids[index]),
                confidence=float(all_confidences[index]),
                x1=int(np.clip(round(x1), 0, frame_width - 1)),
                y1=int(np.clip(round(y1), 0, frame_height - 1)),
                x2=int(np.clip(round(x2), 0, frame_width - 1)),
                y2=int(np.clip(round(y2), 0, frame_height - 1)),
            )
        )
    return results


def _normalize_head(output: np.ndarray) -> np.ndarray:
    value = np.asarray(output, dtype=np.float32)
    if value.ndim == 4 and value.shape[0] == 1 and value.shape[1] % 3 == 0:
        attributes = value.shape[1] // 3
        value = value.reshape(1, 3, attributes, value.shape[2], value.shape[3])
    if value.ndim != 5 or value.shape[0] != 1 or value.shape[1] != 3 or value.shape[2] < 6:
        raise ValueError(f"YOLOv5 输出形状无效：{tuple(value.shape)}")
    return value[0].transpose(0, 2, 3, 1)


def _sigmoid(value: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(value, -30.0, 30.0)))


def _activate_head(value: np.ndarray) -> np.ndarray:
    """兼容原始 logits 与 Rockchip 已内置 sigmoid 的 YOLOv5 输出。"""

    if float(np.min(value)) >= 0.0 and float(np.max(value)) <= 1.0:
        return value
    return _sigmoid(value)


def _classwise_nms(
    boxes: np.ndarray,
    scores: np.ndarray,
    class_ids: np.ndarray,
    iou_threshold: float,
) -> list[int]:
    selected: list[int] = []
    for class_id in np.unique(class_ids):
        indices = np.flatnonzero(class_ids == class_id)
        order = indices[np.argsort(scores[indices])[::-1]]
        while order.size:
            current = int(order[0])
            selected.append(current)
            if order.size == 1:
                break
            remaining = order[1:]
            order = remaining[_intersection_over_union(boxes[current], boxes[remaining]) <= iou_threshold]
    return sorted(selected, key=lambda index: float(scores[index]), reverse=True)[:100]


def _intersection_over_union(box: np.ndarray, boxes: np.ndarray) -> np.ndarray:
    top_left = np.maximum(box[:2], boxes[:, :2])
    bottom_right = np.minimum(box[2:], boxes[:, 2:])
    intersection_size = np.maximum(0.0, bottom_right - top_left)
    intersection = intersection_size[:, 0] * intersection_size[:, 1]
    box_area = max(0.0, float(box[2] - box[0])) * max(0.0, float(box[3] - box[1]))
    boxes_size = np.maximum(0.0, boxes[:, 2:] - boxes[:, :2])
    boxes_area = boxes_size[:, 0] * boxes_size[:, 1]
    union = box_area + boxes_area - intersection
    return np.divide(intersection, union, out=np.zeros_like(intersection), where=union > 0)
