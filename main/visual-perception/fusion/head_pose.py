"""头部姿态 SolvePnP"""
from __future__ import annotations
import cv2
import numpy as np

_FACE_3D = np.array([
    [0.0, 0.0, 0.0], [0.0, -30.0, -10.0],
    [-35.0, -25.0, 15.0], [35.0, -25.0, 15.0],
    [-25.0, 15.0, 5.0], [25.0, 15.0, 5.0], [0.0, 35.0, -5.0],
], dtype=np.float64)
_IDX = [33, 51, 72, 87, 59, 65, 10]


def estimate_head_pose(landmarks, img_w, img_h):
    if len(landmarks) < 90:
        return (0.0, 0.0, 0.0)
    pts = np.array([landmarks[i] for i in _IDX if i < len(landmarks)], dtype=np.float64)
    pts[:, 0] *= img_w
    pts[:, 1] *= img_h

    focal = img_w
    cm = np.array([[focal, 0, img_w/2], [0, focal, img_h/2], [0, 0, 1]], dtype=np.float64)
    dc = np.zeros((4, 1), dtype=np.float64)

    success, rvec, _ = cv2.solvePnP(_FACE_3D[:len(pts)], pts, cm, dc, flags=cv2.SOLVEPNP_ITERATIVE)
    if not success:
        return (0.0, 0.0, 0.0)

    rmat, _ = cv2.Rodrigues(rvec)
    sy = np.sqrt(rmat[0, 0]**2 + rmat[1, 0]**2)
    pitch = np.degrees(np.arctan2(-rmat[2, 0], sy))
    yaw = np.degrees(np.arctan2(rmat[1, 0], rmat[0, 0]))
    roll = np.degrees(np.arctan2(rmat[2, 1], rmat[2, 2]))
    return (float(pitch), float(yaw), float(roll))
