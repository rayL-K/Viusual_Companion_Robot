"""感知数据状态定义"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FaceInfo:
    detected: bool = False
    bbox: tuple[float, float, float, float] = (0, 0, 0, 0)
    confidence: float = 0.0


@dataclass
class FaceLandmarks:
    points: list[tuple[float, float]] = field(default_factory=list)
    left_eye_ear: float = 0.0
    right_eye_ear: float = 0.0
    mouth_aspect_ratio: float = 0.0
    brow_raise: float = 0.0
    smile_ratio: float = 0.0


@dataclass
class HeadPose:
    pitch: float = 0.0
    yaw: float = 0.0
    roll: float = 0.0


@dataclass
class Emotion:
    dominant: str = "neutral"
    scores: dict[str, float] = field(default_factory=lambda: {
        "angry": 0.0, "disgust": 0.0, "fear": 0.0,
        "happy": 0.0, "sad": 0.0, "surprise": 0.0, "neutral": 1.0,
    })


@dataclass
class BodyKeypoints:
    points: list[tuple[float, float, float]] = field(default_factory=list)


@dataclass
class Gesture:
    waving: bool = False
    hand_up: bool = False
    nodding: bool = False
    head_shaking: bool = False


@dataclass
class PerceptionFrame:
    face: FaceInfo = field(default_factory=FaceInfo)
    landmarks: FaceLandmarks = field(default_factory=FaceLandmarks)
    head_pose: HeadPose = field(default_factory=HeadPose)
    emotion: Emotion = field(default_factory=Emotion)
    body: BodyKeypoints = field(default_factory=BodyKeypoints)
    gesture: Gesture = field(default_factory=Gesture)

    def to_dict(self) -> dict:
        return {
            "face": {
                "detected": self.face.detected,
                "bbox": list(self.face.bbox),
            },
            "head_pose": {
                "pitch": round(self.head_pose.pitch, 2),
                "yaw": round(self.head_pose.yaw, 2),
                "roll": round(self.head_pose.roll, 2),
            },
            "emotion": {
                "dominant": self.emotion.dominant,
                "scores": self.emotion.scores,
            },
            "landmarks": {
                "left_eye_ear": round(self.landmarks.left_eye_ear, 3),
                "right_eye_ear": round(self.landmarks.right_eye_ear, 3),
                "mouth_aspect_ratio": round(self.landmarks.mouth_aspect_ratio, 3),
                "smile_ratio": round(self.landmarks.smile_ratio, 3),
                "brow_raise": round(self.landmarks.brow_raise, 3),
            },
            "gesture": {
                "waving": self.gesture.waving,
                "hand_up": self.gesture.hand_up,
                "nodding": self.gesture.nodding,
                "head_shaking": self.gesture.head_shaking,
            },
        }
