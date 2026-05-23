"""手势识别"""
from __future__ import annotations
from collections import deque
from dataclasses import dataclass, field

from fusion.state import Gesture, BodyKeypoints, HeadPose

COCO = {"nose": 0, "Lshoulder": 5, "Rshoulder": 6, "Lwrist": 9, "Rwrist": 10}


@dataclass
class _GS:
    wy: deque[float] = field(default_factory=lambda: deque(maxlen=15))
    ph: deque[float] = field(default_factory=lambda: deque(maxlen=15))
    yh: deque[float] = field(default_factory=lambda: deque(maxlen=15))
    last_area: float = 0.0

_ST = _GS()


def recognize_gestures(body: BodyKeypoints, head_pose: HeadPose, face_area: float, fps=30) -> Gesture:
    r = Gesture()
    pts = body.points
    if len(pts) < 13:
        return r

    ws = [pts[COCO["Rwrist"]], pts[COCO["Lwrist"]]]
    wp = next((w[1] for w in ws if w[2] > 0.3), None)
    if wp is not None:
        _ST.wy.append(wp)
        sy = min(pts[COCO["Rshoulder"]][1], pts[COCO["Lshoulder"]][1])
        r.hand_up = wp < sy - 0.05
        if len(_ST.wy) == 15:
            amp = max(_ST.wy) - min(_ST.wy)
            r.waving = amp > 0.08

    _ST.ph.append(head_pose.pitch)
    _ST.yh.append(head_pose.yaw)
    if len(_ST.ph) == 15:
        r.nodding = max(_ST.ph) - min(_ST.ph) > 15
    if len(_ST.yh) == 15:
        r.head_shaking = max(_ST.yh) - min(_ST.yh) > 20

    _ST.last_area = face_area
    return r


def reset_gesture_state():
    _ST.wy.clear()
    _ST.ph.clear()
    _ST.yh.clear()
    _ST.last_area = 0.0
