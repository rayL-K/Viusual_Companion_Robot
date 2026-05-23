"""Live2D 浏览器端控制链路的静态回归测试。"""

from __future__ import annotations

import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
STAGE_JS_PATH = PROJECT_ROOT / "main" / "live2d_stage" / "src" / "stage.js"
PERCEPTION_JS_PATH = PROJECT_ROOT / "main" / "live2d_stage" / "src" / "perception-client.js"
EMOTION_ONNX_JS_PATH = PROJECT_ROOT / "main" / "live2d_stage" / "src" / "emotion-onnx-client.js"


class Live2DStageFrontendTest(unittest.TestCase):
    """验证关键前端控制参数没有在请求或播放链路中丢失。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.stage_source = STAGE_JS_PATH.read_text(encoding="utf-8")
        cls.perception_source = PERCEPTION_JS_PATH.read_text(encoding="utf-8")
        cls.emotion_onnx_source = EMOTION_ONNX_JS_PATH.read_text(encoding="utf-8")

    def test_speech_rate_controls_real_audio_playback(self) -> None:
        self.assertIn("audio.playbackRate = safeRate", self.stage_source)
        self.assertIn("audio.defaultPlaybackRate = safeRate", self.stage_source)
        self.assertIn("startMouthSync(plan, playbackRate)", self.stage_source)
        self.assertIn("syncActiveSpeechRate(safeRate)", self.stage_source)

    def test_tts_request_still_sends_selected_rate(self) -> None:
        self.assertIn("rate,", self.stage_source)
        self.assertIn("voice: modelState.selectedVoice", self.stage_source)
        self.assertIn("reference: modelState.selectedReference", self.stage_source)
        self.assertIn("promptText: modelState.referencePromptText", self.stage_source)

    def test_action_disk_covers_original_model_shortcuts(self) -> None:
        for action_name in (
            "right_hand_up",
            "left_hand_up",
            "twin_tail",
            "microphone",
            "finger_heart",
            "gaming",
            "shadow_face",
            "cry",
            "heart",
            "star_eyes",
            "dizzy",
            "sweat",
            "anxious",
            "angry",
            "blush",
            "flowers",
            "question",
            "dark_mode",
            "captain",
            "admiral",
            "governor",
        ):
            self.assertIn(f'name: "{action_name}"', self.stage_source)

    def test_reply_and_waiting_animation_are_not_instant_only(self) -> None:
        self.assertIn("THINKING_MOTION_SEQUENCE", self.stage_source)
        self.assertIn("startThinkingAnimation();", self.stage_source)
        self.assertIn("stopThinkingAnimation({ restoreMotion: false, clearRoulette: false })", self.stage_source)
        self.assertIn("startReplyStream(plan.text, playbackRate)", self.stage_source)
        self.assertIn("finishReplyStream()", self.stage_source)

    def test_llm_visual_plan_starts_with_speech_playback(self) -> None:
        self.assertIn("applyPlanVisualsForSpeech(plan)", self.stage_source)
        self.assertIn("await applyPlanVisuals(plan)", self.stage_source)
        self.assertIn("await applyPlanVisuals(modelState.currentPlan)", self.stage_source)
        self.assertIn('await applyMotion("scene1")', self.stage_source)
        self.assertLess(
            self.stage_source.index("await clearRouletteMotionArtifacts()"),
            self.stage_source.index("await audio.play()"),
        )

    def test_idle_and_natural_motion_are_enabled(self) -> None:
        self.assertIn("IDLE_ACTION_NAMES", self.stage_source)
        self.assertIn('"twin_tail"', self.stage_source)
        self.assertIn("scheduleIdleAction()", self.stage_source)
        self.assertIn("runIdleAction()", self.stage_source)
        self.assertIn("naturalHeadMotion", self.stage_source)
        self.assertIn("natural.angleX + x * POINTER_FOLLOW_LIMITS.angleX", self.stage_source)

    def test_pointer_follow_uses_whole_page_not_only_canvas(self) -> None:
        self.assertIn('document.addEventListener("pointermove", updatePointerTargetFromEvent', self.stage_source)
        self.assertIn("function updatePointerTargetFromEvent(event)", self.stage_source)
        self.assertIn("function resetPointerTarget()", self.stage_source)
        self.assertNotIn('canvasHost.addEventListener("pointermove"', self.stage_source)

    def test_audio_status_resets_after_playback_finishes(self) -> None:
        self.assertIn("音频播放完成", self.stage_source)
        self.assertIn("可以继续对话，或等待她做待机动作。", self.stage_source)

    def test_local_voice_health_check_is_visible(self) -> None:
        self.assertIn("TTS_HEALTH_API_URL", self.stage_source)
        self.assertIn("checkSelectedVoiceHealth()", self.stage_source)
        self.assertIn("voxcpm_project_local", self.stage_source)
        self.assertIn("VoxCPM 项目内本地推理", self.stage_source)

    def test_visual_context_is_sent_with_chat_request(self) -> None:
        self.assertIn("vision: perceptionClient.getContext()", self.stage_source)
        self.assertIn("getContext()", self.perception_source)
        self.assertIn("emotionSource", self.perception_source)
        self.assertIn("fullScores", self.perception_source)
        self.assertIn("headPose", self.perception_source)

    def test_onnx_emotion_adapter_stays_optional(self) -> None:
        self.assertIn("emotionOnnxClient.classify(video, faceBox)", self.perception_source)
        self.assertIn('source: "blendshape_rule"', self.perception_source)
        self.assertIn("EMOTION_ONNX_MODEL_URL", self.emotion_onnx_source)
        self.assertIn('import("onnxruntime-web")', self.emotion_onnx_source)
        self.assertIn("dims: [1, 1, EMOTION_INPUT_SIZE, EMOTION_INPUT_SIZE]", self.emotion_onnx_source)
        self.assertIn('source: "onnx"', self.emotion_onnx_source)


if __name__ == "__main__":
    unittest.main()
