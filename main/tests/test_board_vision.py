from __future__ import annotations

import base64
import sys
import tempfile
import time
import unittest
from concurrent.futures import Future
from pathlib import Path

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = PROJECT_ROOT / "main" / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from visual_companion_robot.integrations.model_runtime import Detection, DetectionResult
from visual_companion_robot.perception.scene_analyzer import SceneAnalyzer, SceneAnalyzerConfig
from visual_companion_robot.perception.vision import PerceptionFrame
from visual_companion_robot.perception.vision_service import (
    BoardVisionService,
    VisionInputError,
    VisionServiceConfig,
    _animal_caption_conflict,
    _caption_claims_human,
)
from visual_companion_robot.perception.pose import PosePerson
from visual_companion_robot.perception.yolo_v5 import postprocess_yolov5


class FakeDetector:
    def __init__(self) -> None:
        self.loaded = False

    def load(self) -> None:
        self.loaded = True

    def unload(self) -> None:
        self.loaded = False

    def is_loaded(self) -> bool:
        return self.loaded

    def detect(self, image: np.ndarray) -> DetectionResult:
        height, width = image.shape[:2]
        return DetectionResult(
            detections=[
                Detection(0, "person", 0.91, 1, 2, 30, 40),
                Detection(63, "laptop", 0.82, 5, 10, 25, 35),
            ],
            frame_width=width,
            frame_height=height,
        )

    @staticmethod
    def describe(result: DetectionResult) -> str:
        return "画面中有1人、1台笔记本电脑"


class FakeEmotionProvider:
    def health(self) -> dict:
        return {"ok": True, "backend": "ferplus-onnx"}

    def classify(self, image_base64: str) -> dict:
        self.last_image = image_base64
        return {
            "has_face": True,
            "emotion": "happy",
            "confidence": 0.87,
            "full_scores": {"happy": 0.87, "neutral": 0.13},
        }


class FakePoseEstimator:
    def __init__(self) -> None:
        self.loaded = False

    def load(self) -> None:
        self.loaded = True

    def close(self) -> None:
        self.loaded = False

    def is_loaded(self) -> bool:
        return self.loaded

    def analyze(self, _image: np.ndarray) -> list[PosePerson]:
        return [
            PosePerson(
                confidence=0.9,
                bbox=(1, 2, 30, 40),
                keypoints=tuple((0.0, 0.0, 0.0) for _ in range(17)),
                actions=("left_hand_raised",),
                overall_state="standing",
            )
        ]


class FakeSemanticProvider:
    def __init__(self) -> None:
        self.calls = 0

    def health(self) -> dict:
        return {"ok": True, "backend": "rk3588-qwen3-vl-2b-w8a8"}

    def describe(self, image_base64: str) -> dict:
        self.calls += 1
        self.last_image = image_base64
        return {
            "ok": True,
            "backend": "rk3588-qwen3-vl-2b-w8a8",
            "semantic_caption": "一名微笑的人坐在电脑前，背景是室内书桌。",
        }


class YoloPostprocessTests(unittest.TestCase):
    def test_three_detection_heads_produce_scaled_person_box(self) -> None:
        outputs = [
            np.zeros((1, 3, 85, 80, 80), dtype=np.float32),
            np.zeros((1, 3, 85, 40, 40), dtype=np.float32),
            np.zeros((1, 3, 85, 20, 20), dtype=np.float32),
        ]
        outputs[0][0, 0, 4, 10, 10] = 10.0
        outputs[0][0, 0, 5, 10, 10] = 10.0

        candidates = postprocess_yolov5(outputs, frame_size=(320, 240), conf_threshold=0.7)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].class_id, 0)
        self.assertGreater(candidates[0].confidence, 0.99)
        self.assertTrue(0 <= candidates[0].x1 < candidates[0].x2 < 320)
        self.assertTrue(0 <= candidates[0].y1 < candidates[0].y2 < 240)

    def test_invalid_head_shape_fails_instead_of_guessing(self) -> None:
        with self.assertRaisesRegex(ValueError, "输出形状"):
            postprocess_yolov5(
                [
                    np.zeros((1, 85, 80, 80), dtype=np.float32),
                    np.zeros((1, 3, 85, 40, 40), dtype=np.float32),
                    np.zeros((1, 3, 85, 20, 20), dtype=np.float32),
                ],
                frame_size=(640, 480),
            )

    def test_flat_channel_heads_are_supported(self) -> None:
        outputs = [
            np.full((1, 255, size, size), -20.0, dtype=np.float32)
            for size in (80, 40, 20)
        ]
        outputs[0][0, 4, 10, 12] = 10.0
        outputs[0][0, 5, 10, 12] = 10.0

        candidates = postprocess_yolov5(outputs, frame_size=(640, 640), conf_threshold=0.5)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].class_id, 0)

    def test_pre_activated_rockchip_heads_are_not_sigmoided_twice(self) -> None:
        outputs = [
            np.zeros((1, 255, size, size), dtype=np.float32)
            for size in (80, 40, 20)
        ]
        outputs[0][0, 4, 10, 12] = 0.9
        outputs[0][0, 5, 10, 12] = 0.8

        candidates = postprocess_yolov5(outputs, frame_size=(640, 640), conf_threshold=0.7)

        self.assertEqual(len(candidates), 1)
        self.assertAlmostEqual(candidates[0].confidence, 0.72, places=5)


class BoardVisionServiceTests(unittest.TestCase):
    def test_vlm_prompt_requires_grounded_compact_output(self) -> None:
        source = (PROJECT_ROOT / "main" / "native" / "rk3588_vlm" / "vlm_worker.cpp").read_text(encoding="utf-8")
        self.assertIn("不超过45个汉字", source)
        self.assertIn("看不清写不确定", source)
        self.assertIn("禁止猜测年龄、身份、地点或画外内容", source)

    def test_human_conflict_guard_ignores_explicit_no_person_caption(self) -> None:
        self.assertFalse(_caption_claims_human("画面中未检测到人，也没有明显人物。"))
        self.assertFalse(_caption_claims_human("这是一架无人机。"))
        self.assertTrue(_caption_claims_human("一名男子站在书桌旁。"))

    def test_animal_conflict_guard_rejects_cat_dog_substitution(self) -> None:
        self.assertIn("猫描述成狗", _animal_caption_conflict("一只金毛犬在厨房里", ["cat", "chair"]))
        self.assertIn("狗描述成猫", _animal_caption_conflict("一只橘猫躺在床上", ["dog"]))
        self.assertEqual(_animal_caption_conflict("一只橘猫在厨房里", ["cat"]), "")
        self.assertEqual(_animal_caption_conflict("猫和狗在沙发上", ["cat", "dog"]), "")

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.model_path = Path(self.temp_dir.name) / "model.rknn"
        self.model_path.write_bytes(b"test-model")
        detector = FakeDetector()
        self.analyzer = SceneAnalyzer(
            SceneAnalyzerConfig(str(self.model_path)),
            detector=detector,  # type: ignore[arg-type]
        )
        self.emotion = FakeEmotionProvider()
        self.service = BoardVisionService(
            VisionServiceConfig(self.model_path),
            analyzer=self.analyzer,
            pose_estimator=FakePoseEstimator(),  # type: ignore[arg-type]
            emotion_provider=self.emotion,
        )

    def tearDown(self) -> None:
        self.service.close()
        self.temp_dir.cleanup()

    def test_load_requires_both_local_models_and_analyze_combines_results(self) -> None:
        self.service.load()
        image = np.zeros((48, 64, 3), dtype=np.uint8)
        ok, encoded = cv2.imencode(".jpg", image)
        self.assertTrue(ok)
        image_base64 = base64.b64encode(encoded).decode("ascii")

        result = self.service.analyze(image_base64)

        self.assertTrue(result["ok"])
        self.assertEqual(result["backend"], "elf2-local-yolo-pose-yunet-sface-ferplus")
        self.assertEqual(result["scene_caption"], "画面中有1人、1台笔记本电脑")
        self.assertEqual(result["person_activity"], "主要人物姿态：举起左手、站立")
        self.assertEqual(result["person_actions"], ["left_hand_raised"])
        self.assertEqual(result["person_count"], 1)
        self.assertEqual(result["emotion"], "happy")
        self.assertEqual(result["frame_width"], 64)
        self.assertEqual(result["frame_height"], 48)
        self.assertEqual(self.emotion.last_image, image_base64)
        self.assertTrue(self.service.health()["ok"])

    def test_invalid_base64_is_rejected_before_inference(self) -> None:
        self.service.load()
        with self.assertRaisesRegex(VisionInputError, "Base64"):
            self.service.analyze("not-base64!")

    def test_semantic_vlm_refreshes_in_background_without_blocking_structured_vision(self) -> None:
        self.service.close()
        semantic = FakeSemanticProvider()
        self.service = BoardVisionService(
            VisionServiceConfig(
                self.model_path,
                semantic_service_url="http://127.0.0.1:8767",
                semantic_refresh_seconds=60.0,
            ),
            analyzer=self.analyzer,
            pose_estimator=FakePoseEstimator(),  # type: ignore[arg-type]
            emotion_provider=self.emotion,
            semantic_provider=semantic,
        )
        self.service.load()
        image = np.zeros((48, 64, 3), dtype=np.uint8)
        ok, encoded = cv2.imencode(".jpg", image)
        self.assertTrue(ok)
        image_base64 = base64.b64encode(encoded).decode("ascii")

        first = self.service.analyze(image_base64)
        self.assertIn(first["semantic_status"], {"warming", "ready"})
        deadline = time.monotonic() + 1.0
        while self.service._semantic_snapshot().get("semantic_status") != "ready":
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.005)
        second = self.service.analyze(image_base64)

        self.assertEqual(second["semantic_status"], "ready")
        self.assertIn("电脑前", second["semantic_caption"])
        self.assertEqual(semantic.last_image, image_base64)
        self.assertTrue(self.service.health()["semantic_ready"])

        signature = self.service._semantic_signature
        self.assertIsNotNone(signature)
        changed_scene = self.service._semantic_snapshot(
            current_signature=bytes(255 - value for value in signature or b""),
            person_count=1,
            has_face=True,
        )
        self.assertIn(changed_scene["semantic_status"], {"stale_frame", "refreshing"})
        self.assertNotIn("semantic_caption", changed_scene)

        conflicting_person = self.service._semantic_snapshot(
            current_signature=signature,
            person_count=0,
            has_face=False,
        )
        self.assertEqual(conflicting_person["semantic_status"], "conflict")
        self.assertNotIn("semantic_caption", conflicting_person)

        # 同一场景遵守低频刷新；画面明显变化时不必再等待完整的 60 秒间隔。
        self.service._semantic_started_at -= 1.1
        changed_image = np.full((48, 64, 3), 255, dtype=np.uint8)
        ok, changed_encoded = cv2.imencode(".jpg", changed_image)
        self.assertTrue(ok)
        changed_base64 = base64.b64encode(changed_encoded).decode("ascii")
        self.service.analyze(changed_base64)
        deadline = time.monotonic() + 1.0
        while semantic.calls < 2:
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.005)
        self.assertEqual(semantic.last_image, changed_base64)

    def test_stale_semantic_result_reports_refreshing_while_new_inference_runs(self) -> None:
        self.service.close()
        self.service = BoardVisionService(
            VisionServiceConfig(self.model_path, semantic_service_url="http://127.0.0.1:8767"),
            analyzer=self.analyzer,
            pose_estimator=FakePoseEstimator(),  # type: ignore[arg-type]
            emotion_provider=self.emotion,
            semantic_provider=FakeSemanticProvider(),
        )
        pending: Future[dict[str, object]] = Future()
        self.service._semantic_result = {"semantic_caption": "旧场景", "semantic_backend": "test-vlm"}
        self.service._semantic_completed_at = time.monotonic() - 25.0
        self.service._semantic_future = pending

        snapshot = self.service._semantic_snapshot()

        self.assertEqual(snapshot, {"semantic_status": "refreshing"})

    def test_missing_model_prevents_startup(self) -> None:
        missing = Path(self.temp_dir.name) / "missing.rknn"
        service = BoardVisionService(
            VisionServiceConfig(missing),
            analyzer=self.analyzer,
            emotion_provider=self.emotion,
        )
        with self.assertRaisesRegex(RuntimeError, "模型不存在"):
            service.load()


if __name__ == "__main__":
    unittest.main()
