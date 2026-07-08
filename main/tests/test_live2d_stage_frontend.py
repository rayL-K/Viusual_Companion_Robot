"""Live2D 浏览器端控制链路的静态回归测试。"""

from __future__ import annotations

import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
STAGE_JS_PATH = PROJECT_ROOT / "main" / "live2d_stage" / "src" / "stage.js"
PERCEPTION_JS_PATH = PROJECT_ROOT / "main" / "live2d_stage" / "src" / "perception-client.js"
STAGE_HTML_PATH = PROJECT_ROOT / "main" / "live2d_stage" / "index.html"
STAGE_STYLE_PATH = PROJECT_ROOT / "main" / "live2d_stage" / "src" / "styles.css"


class Live2DStageFrontendTest(unittest.TestCase):
    """验证关键前端控制参数没有在请求或播放链路中丢失。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.stage_source = STAGE_JS_PATH.read_text(encoding="utf-8")
        cls.perception_source = PERCEPTION_JS_PATH.read_text(encoding="utf-8")
        cls.stage_html = STAGE_HTML_PATH.read_text(encoding="utf-8")
        cls.stage_styles = STAGE_STYLE_PATH.read_text(encoding="utf-8")

    def test_runtime_scripts_are_served_from_the_project_origin(self) -> None:
        self.assertNotIn('<script src="https://', self.stage_html)
        for filename in (
            "live2dcubismcore.min.js",
            "pixi-6.5.10.min.js",
            "pixi-live2d-display-0.4.0-cubism4.min.js",
        ):
            self.assertIn(f'/vendor/{filename}', self.stage_html)
            self.assertGreater((STAGE_HTML_PATH.parent / "public" / "vendor" / filename).stat().st_size, 100_000)

    def test_responsive_page_has_direct_stage_and_console_navigation(self) -> None:
        self.assertIn('id="mobileControlButton"', self.stage_html)
        self.assertIn('id="mobileStageButton"', self.stage_html)
        self.assertIn('mobileControlButton.addEventListener("click"', self.stage_source)
        self.assertIn('mobileStageButton.addEventListener("click"', self.stage_source)
        self.assertIn("height: min(var(--shell-max-height), calc(100dvh - 36px))", self.stage_styles)

    def test_mobile_uses_reduced_texture_model_and_keeps_chat_available_on_failure(self) -> None:
        model_root = PROJECT_ROOT / "main" / "assets" / "live2d" / "Strawberry_Rabbit"
        mobile_model = model_root / "Strawberry_Rabbit.mobile-1024-r2.model3.json"
        self.assertTrue(mobile_model.is_file())
        self.assertIn("textures_1024_r2/", mobile_model.read_text(encoding="utf-8"))
        self.assertIn("MOBILE_MODEL_URL", self.stage_source)
        self.assertIn("function preferredModelUrl", self.stage_source)
        self.assertIn("function showStageFallback", self.stage_source)
        self.assertIn('id="stageFallback"', self.stage_html)
        textures = sorted((model_root / "textures_1024_r2").glob("*.png"))
        self.assertEqual(len(textures), 5)
        for texture in textures:
            self.assertLess(texture.stat().st_size, 1024 * 1024)

    def test_speech_rate_is_applied_once_by_tts_backend(self) -> None:
        self.assertIn("audio.playbackRate = safeRate", self.stage_source)
        self.assertIn("audio.defaultPlaybackRate = safeRate", self.stage_source)
        self.assertIn("applyAudioPlaybackRate(audio, 1.0)", self.stage_source)
        self.assertIn("startMouthSync(plan, speechRate)", self.stage_source)
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
        self.assertNotIn("文字已先显示", self.stage_source)
        self.assertIn("startReplyStream(plan.text, speechRate)", self.stage_source)
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

    def test_render_loop_targets_60_fps_with_adaptive_resolution(self) -> None:
        self.assertIn("app.ticker.maxFPS = 60", self.stage_source)
        self.assertIn("powerPreference: \"high-performance\"", self.stage_source)
        self.assertIn("tuneRenderResolution(now)", self.stage_source)
        self.assertIn("natural.angleX + x * POINTER_FOLLOW_LIMITS.angleX", self.stage_source)

    def test_pointer_follow_uses_whole_page_not_only_canvas(self) -> None:
        self.assertIn('document.addEventListener("pointermove", updatePointerTargetFromEvent', self.stage_source)
        self.assertIn("function updatePointerTargetFromEvent(event)", self.stage_source)
        self.assertIn("function resetPointerTarget()", self.stage_source)
        self.assertNotIn('canvasHost.addEventListener("pointermove"', self.stage_source)

    def test_audio_status_resets_after_playback_finishes(self) -> None:
        self.assertIn("音频播放完成", self.stage_source)
        self.assertIn("可以继续对话，或等待她做待机动作。", self.stage_source)
        self.assertIn("hintEl.textContent = hint", self.stage_source)

    def test_audio_mouth_sync_overrides_camera_tracking_for_the_full_clip(self) -> None:
        speaking_branch = 'if (modelState.speaking || !perceptionParams)'
        self.assertIn(speaking_branch, self.stage_source)
        self.assertGreater(
            self.stage_source.index(speaking_branch),
            self.stage_source.index('if (perceptionParams) {'),
        )
        self.assertIn("audio.currentTime / audio.duration", self.stage_source)
        self.assertIn('setParameter("ParamMouthOpenY", modelState.mouthCurrent)', self.stage_source)

    def test_mobile_media_capture_does_not_require_device_enumeration_or_audio_worklet(self) -> None:
        self.assertIn("function getUserMedia(constraints)", self.stage_source)
        self.assertIn("navigator.webkitGetUserMedia", self.stage_source)
        self.assertIn("function mediaEnumerationAvailable()", self.stage_source)
        self.assertIn("modelState.audioContext.createScriptProcessor(2048, 1, 1)", self.stage_source)
        self.assertIn('facingMode: { ideal: "user" }', self.stage_source)
        self.assertNotIn(
            "navigator.mediaDevices?.getUserMedia && navigator.mediaDevices?.enumerateDevices && audioContextCtor()",
            self.stage_source,
        )

    def test_local_voice_health_check_is_visible(self) -> None:
        self.assertIn("TTS_HEALTH_API_URL", self.stage_source)
        self.assertIn("checkSelectedVoiceHealth()", self.stage_source)
        self.assertIn("voxcpm_cpp_local", self.stage_source)
        self.assertIn("VoxCPM 开发板本地量化推理", self.stage_source)

    def test_backend_panel_only_describes_real_runtime_connections(self) -> None:
        self.assertIn("RUNTIME_BACKENDS", self.stage_source)
        self.assertIn("ELF2 YOLO + Qwen3-VL + 人脸/姿态", self.stage_source)
        self.assertIn("不提供客户端或云端降级", self.stage_source)
        self.assertNotIn("INFERENCE_BACKENDS", self.stage_source)
        self.assertNotIn("applyBackendChange", self.stage_source)
        self.assertNotIn("vc-backend-llm", self.stage_source)

    def test_failed_voice_activation_rolls_back_the_selection(self) -> None:
        self.assertIn("const activated = await synchronizeSelectedVoiceRuntime()", self.stage_source)
        self.assertIn("modelState.selectedVoice = previousVoice", self.stage_source)
        self.assertIn('addControlLog("恢复语音模型选择"', self.stage_source)
        self.assertIn("语音切换失败，已恢复原模型", self.stage_source)

    def test_visual_context_is_sent_with_chat_request(self) -> None:
        self.assertIn("await perceptionClient.getContextForChat()", self.stage_source)
        self.assertIn("getContextForChat(timeoutMs = CHAT_SEMANTIC_WAIT_MS)", self.perception_source)
        self.assertIn("SEMANTIC_CONTEXT_MAX_AGE_MS", self.perception_source)
        self.assertIn("getContext(now = Date.now())", self.perception_source)
        self.assertIn("emotionSource", self.perception_source)
        self.assertIn("semanticCaption", self.perception_source)
        self.assertIn("fullScores", self.perception_source)
        self.assertIn('apiUrl("/vision")', self.perception_source)
        self.assertIn('analyzing: "板端分析中"', self.stage_source)
        self.assertIn("ELF2 正在分析当前画面", self.stage_source)
        self.assertIn("frameRate: { ideal: 60, max: 60 }", self.stage_source)

    def test_browser_has_no_visual_inference_fallback(self) -> None:
        self.assertNotIn("MediaPipe", self.perception_source)
        self.assertNotIn("blendshape_rule", self.perception_source)
        self.assertNotIn("FaceLandmarker", self.perception_source)
        self.assertIn('backend !== "elf2-local-yolo-pose-yunet-sface-ferplus"', self.perception_source)


if __name__ == "__main__":
    unittest.main()
