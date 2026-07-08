import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const stageRoot = path.resolve(__dirname, "..");
const mainRoot = path.resolve(stageRoot, "..");
const projectRoot = path.resolve(mainRoot, "..");
const modelRoot = path.resolve(mainRoot, "assets/live2d/Strawberry_Rabbit");

function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

function assert(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

const html = fs.readFileSync(path.join(stageRoot, "index.html"), "utf8");
for (const vendorFile of [
  "live2dcubismcore.min.js",
  "pixi-6.5.10.min.js",
  "pixi-live2d-display-0.4.0-cubism4.min.js",
]) {
  assert(html.includes(`/vendor/${vendorFile}`), `index.html 缺少本地运行库 ${vendorFile}。`);
  assert(fs.statSync(path.join(stageRoot, "public", "vendor", vendorFile)).size > 100_000, `${vendorFile} 内容不完整。`);
}
assert(!html.includes('<script src="https://'), "生产页面不应依赖外部 CDN 脚本。");
assert(html.includes("chatInput"), "index.html 缺少实时对话输入框。");
assert(html.includes('id="stageFallback"'), "index.html 缺少移动端模型失败后的可交互提示。");
assert(html.includes("speechRateInput"), "index.html 缺少语速控制。");
assert(html.includes("voiceList"), "index.html 缺少语音模型列表。");
assert(html.includes("voicePreviewButton"), "index.html 缺少当前语音模型试听按钮。");
assert(html.includes("referenceSelect"), "index.html 缺少参考音频选择框。");
assert(html.includes("referenceAudioPreview"), "index.html 缺少参考音频试听控件。");
assert(html.includes("referenceTextInput"), "index.html 缺少参考文本编辑框。");
assert(html.includes("modelScalePanel"), "index.html 缺少点击人物后显示的人物大小滑条。");
assert(html.includes("modelScaleInput"), "index.html 缺少人物大小滑条输入控件。");
assert(html.includes("modelScaleCloseButton"), "index.html 缺少人物大小面板关闭按钮。");
for (const id of ["actionDiskButton", "voiceModelButton", "skinModelButton", "controlLogButton"]) {
  assert(html.includes(id), `index.html 缺少功能按钮 ${id}。`);
}
for (const id of ["mobileControlButton", "mobileStageButton"]) {
  assert(html.includes(id), `index.html 缺少移动端导航 ${id}。`);
}
assert(html.includes('id="backendPanelButton" type="button">运行后端</button>'), "后端面板入口应描述当前真实运行状态。");
assert(html.includes("当前运行后端"), "后端面板缺少真实运行状态标题。");
assert(html.includes("cameraPanelButton"), "index.html 缺少视觉摄像头按钮。");
assert(html.includes("audioPanelButton"), "index.html 缺少听觉麦克风按钮。");
assert(html.includes('id="controlLogButton" type="button">运行日志</button>'), "index.html 应将日志入口显示为运行日志。");
assert(html.includes("运行日志"), "index.html 缺少运行日志面板标题。");
assert(!html.includes("LLM 控制日志"), "日志面板不应只描述为 LLM 控制日志。");
assert(html.includes("historyButton"), "index.html 缺少历史记录按钮。");
assert(!html.includes("closeHistoryPanelButton"), "历史记录面板不应保留独立收起按钮。");
for (const id of ["actionPanel", "voicePanel", "skinPanel", "cameraPanel", "audioPanel", "logPanel", "historyPanel"]) {
  assert(html.includes(id), `index.html 缺少右侧展开面板 ${id}。`);
}
for (const id of ["cameraSelect", "cameraDetectButton", "cameraStartButton", "cameraStopButton", "cameraDefaultButton", "cameraWindow", "cameraPreview", "cameraResizeHandle"]) {
  assert(html.includes(id), `index.html 缺少摄像头控件 ${id}。`);
}
for (const id of ["audioSelect", "audioDetectButton", "audioStartButton", "audioStopButton", "audioDefaultButton", "audioWindow", "audioLevelBar"]) {
  assert(html.includes(id), `index.html 缺少听觉模块控件 ${id}。`);
}
assert(html.includes("audioTranscript"), "index.html 缺少语音识别文本状态。");
assert(!html.includes("cameraWindowHandle"), "摄像头预览窗不应保留标题栏。");

const stageScript = fs.readFileSync(path.join(stageRoot, "src/stage.js"), "utf8");
const perceptionScript = fs.readFileSync(path.join(stageRoot, "src/perception-client.js"), "utf8");
const pcmCaptureScript = fs.readFileSync(path.join(stageRoot, "src/pcm-capture-processor.js"), "utf8");
const viteConfig = fs.readFileSync(path.join(stageRoot, "vite.config.mjs"), "utf8");
assert(stageScript.includes("setupPointerTracking"), "stage.js 缺少鼠标上下跟随逻辑。");
assert(stageScript.includes("MODEL_TRANSFORM_STORAGE_KEY"), "stage.js 缺少人物拖放缩放持久化配置。");
assert(stageScript.includes("setupModelTransformControls"), "stage.js 缺少人物拖放缩放事件入口。");
assert(stageScript.includes("isPointInsideDisplayedModel"), "stage.js 缺少点击人物命中检测。");
assert(stageScript.includes("showModelScalePanel"), "stage.js 缺少点击人物显示大小滑条逻辑。");
assert(stageScript.includes("hideModelScalePanelFromOutside"), "stage.js 缺少点击外部关闭人物大小面板逻辑。");
assert(stageScript.includes("modelFitFrame"), "stage.js 缺少安全构图与完整渲染画布分离逻辑。");
assert(stageScript.includes("zoomModelFromWheel"), "stage.js 缺少滚轮缩放人物逻辑。");
assert(stageScript.includes("persistModelTransform"), "stage.js 缺少人物位置保存逻辑。");
assert(stageScript.includes("buildMouthTimeline"), "stage.js 缺少语音口型时间线。");
assert(stageScript.includes("releaseExternalAudio(audio, audioUrl)"), "音频结束和失败后必须释放 Blob URL。");
assert(stageScript.includes("VISIBLE_ACTIONS"), "stage.js 缺少可见动作池。");
assert(stageScript.includes("CHAT_API_URL"), "stage.js 缺少浏览器 LLM 聊天接口。");
assert(stageScript.includes("TTS_API_URL"), "stage.js 缺少可替换 TTS 服务入口。");
assert(stageScript.includes("previewSelectedVoice"), "stage.js 缺少独立于 LLM 的当前语音模型试听入口。");
assert(stageScript.includes("TTS_HEALTH_API_URL"), "stage.js 缺少 TTS 健康检查入口。");
assert(stageScript.includes("VOICES_API_URL"), "stage.js 缺少语音模型列表接口。");
assert(stageScript.includes("REFERENCE_AUDIO_URL"), "stage.js 缺少参考音频试听接口。");
assert(stageScript.includes("navigator.mediaDevices"), "stage.js 缺少浏览器摄像头设备访问逻辑。");
assert(stageScript.includes("STAGE_MODEL_FIT"), "stage.js 缺少稳定舞台画布适配配置。");
assert(stageScript.includes("heightRatio: 0.84"), "stage.js 全身构图人物比例应接近框选参考。");
assert(stageScript.includes("bottomY: 1.08"), "stage.js 全身构图人物落点应接近框选参考。");
assert(stageScript.includes("CAMERA_DEFAULT_STORAGE_KEY"), "stage.js 缺少默认摄像头持久化配置。");
assert(stageScript.includes("CAMERA_WINDOW_WIDTH_STORAGE_KEY"), "stage.js 缺少摄像头窗口宽度持久化配置。");
assert(stageScript.includes("startCameraPreview"), "stage.js 缺少摄像头预览启动逻辑。");
assert(stageScript.includes("setupCameraWindowDrag"), "stage.js 缺少摄像头预览窗拖拽逻辑。");
assert(stageScript.includes("setCameraWindowWidth"), "stage.js 缺少摄像头预览窗等比缩放逻辑。");
assert(stageScript.includes("clearInterval(modelState.perceptionTimer)"), "关闭摄像头时必须清理感知面板定时器。");
assert(stageScript.includes("AUDIO_DEFAULT_STORAGE_KEY"), "stage.js 缺少默认麦克风持久化配置。");
assert(stageScript.includes("startAudioMonitor"), "stage.js 缺少麦克风监听启动逻辑。");
assert(stageScript.includes("updateAudioLevelLoop"), "stage.js 缺少麦克风音量电平更新逻辑。");
assert(stageScript.includes("setupAudioWindowDrag"), "stage.js 缺少麦克风监听窗拖拽逻辑。");
assert(stageScript.includes("PcmSpeechSegmenter"), "stage.js 缺少离线语音句段切分逻辑。");
assert(stageScript.includes("processOfflineAsrQueue"), "stage.js 缺少本机离线语音识别队列。");
assert(stageScript.includes("handlePcmCapture"), "stage.js 缺少 AudioWorklet PCM 采集结果处理逻辑。");
assert(stageScript.includes("submitChatText(text, { source: \"speech\" })"), "stage.js 语音识别结果未接入实时对话。");
assert(stageScript.includes("armOfflineAsrBargeIn"), "stage.js 缺少播放期间的高阈值语音打断监听。");
assert(stageScript.includes("PcmBargeInDetector"), "stage.js 缺少用户语音抢占 TTS 的持续语音检测。");
assert(stageScript.includes("用户语音打断 TTS"), "stage.js 缺少语音打断运行日志。");
assert(!stageScript.includes("webkitSpeechRecognition"), "stage.js 不应继续依赖联网的浏览器 Web Speech。");
assert(pcmCaptureScript.includes("BATCH_SAMPLES = 1024"), "AudioWorklet 应批量投递 PCM，避免高频跨线程消息。");
assert(viteConfig.includes("path.relative(live2dRoot, filePath)"), "Vite Live2D 资源服务必须使用真实路径边界检查。");
assert(stageScript.includes("await perceptionClient.getContextForChat()"), "stage.js 聊天请求缺少带语义等待的视觉上下文。");
assert(stageScript.includes("STAGE_VIEW_MODE = \"fullbody\""), "stage.js 未启用全身构图。");
assert(stageScript.includes("ACTION_FADE_MS = 300"), "stage.js 未把动作渐入渐出限制在 0.3 秒。");
assert(stageScript.includes("openSidePanel"), "stage.js 缺少右侧面板展开逻辑。");
assert(stageScript.includes("loadVoiceModels"), "stage.js 缺少语音模型加载逻辑。");
assert(stageScript.includes("voice: modelState.selectedVoice"), "stage.js 请求 TTS 时必须传递所选语音模型。");
assert(stageScript.includes("reference: modelState.selectedReference"), "stage.js 请求 TTS 时必须传递所选参考音频。");
assert(stageScript.includes("promptText: modelState.referencePromptText"), "stage.js 请求 TTS 时必须传递可编辑参考文本。");
assert(stageScript.includes("toggleSidePanel(historyPanel)"), "历史记录按钮应支持再次点击收回面板。");
assert(stageScript.includes("addChatHistory"), "stage.js 缺少对话历史记录逻辑。");
assert(stageScript.includes("MAX_RUNTIME_LOG_ITEMS"), "stage.js 缺少运行日志保留上限。");
assert(!stageScript.includes("restoreHistoryItem"), "历史记录条目不应保留恢复按钮逻辑。");
assert(stageScript.includes("ACTIONS_BY_NAME"), "stage.js 缺少动作状态名称索引。");
assert(stageScript.includes("mode === \"hold\" ? null"), "stage.js 缺少持久动作状态。");
assert(stageScript.includes("scheduleActionControl"), "stage.js 缺少延时动作计划调度。");
assert(stageScript.includes("clearScheduledActions"), "stage.js 缺少新回复取消旧延时动作的逻辑。");
assert(stageScript.includes("conflictGroups"), "stage.js 缺少动作冲突组配置。");
assert(stageScript.includes("function applyExpressionAsset"), "stage.js 缺少动作表情资源触发函数。");
assert(stageScript.includes("isVisibleActionActive"), "stage.js 缺少动作盘再次点击检测。");
assert(stageScript.includes("cancelVisibleAction"), "stage.js 缺少动作盘再次点击取消逻辑。");
assert(!stageScript.includes("voice: \"strawberry_rabbit\""), "stage.js 不应固定请求旧音色。");
assert(!stageScript.includes("Neo TTS"), "stage.js 不应残留 Neo TTS 运行时文案。");
assert(stageScript.includes("RUNTIME_BACKENDS"), "stage.js 缺少真实运行后端说明。");
assert(!stageScript.includes("INFERENCE_BACKENDS"), "stage.js 不应展示未接线的伪后端切换项。");
assert(!stageScript.includes("applyBackendChange"), "stage.js 不应把非 TTS 后端错误发送到语音切换接口。");

assert(perceptionScript.includes('apiUrl("/vision")'), "perception-client.js 未调用统一板端视觉接口。");
assert(perceptionScript.includes("VISION_FRAME_GAP_MS = 5000"), "浏览器语义分析上传应限制为约 5 秒一次，优先保证摄像头预览流畅。");
assert(perceptionScript.includes("CAPTURE_MAX_WIDTH = 320"), "浏览器语义分析只应上传低分辨率缩略图，避免卡住 60 FPS 预览。");
assert(perceptionScript.includes("waitForCaptureIdle"), "浏览器语义截图应等待空闲时段，避免和摄像头预览抢主线程。");
assert(stageScript.includes("frameRate: { ideal: 60, max: 60 }"), "stage.js 摄像头预览应请求 60 FPS。");
assert(stageScript.includes("PERCEPTION_PANEL_REFRESH_MS = 1000"), "视觉状态面板应低频刷新，避免拖慢摄像头预览。");
assert(perceptionScript.includes("this._scheduleNext(generation, retryDelay)"), "浏览器连续视觉必须在上一请求结束后背压调度。");
assert(!perceptionScript.includes("setInterval"), "浏览器视觉不能用定时并发堆积请求。");
assert(perceptionScript.includes('method: "POST"'), "perception-client.js 未上传摄像头帧。");
assert(perceptionScript.includes("getContext(now = Date.now())"), "perception-client.js 缺少给 LLM 使用的视觉上下文。");
assert(perceptionScript.includes("getContextForChat(timeoutMs = CHAT_SEMANTIC_WAIT_MS)"), "perception-client.js 聊天上下文必须等待语义结果。");
assert(perceptionScript.includes("emotionSource"), "perception-client.js 缺少情绪来源字段。");
assert(perceptionScript.includes("fullScores"), "perception-client.js 缺少完整情绪分数字段。");
assert(perceptionScript.includes("generation === this._generation"), "perception-client.js 缺少摄像头异步启动取消保护。");
assert(!perceptionScript.includes("MediaPipe"), "浏览器端不应继续运行 MediaPipe 推理。");
assert(!perceptionScript.includes("blendshape_rule"), "浏览器端不应保留情绪规则降级。");

const ttsConfig = readJson(path.resolve(mainRoot, "config/tts_models.json"));
assert(ttsConfig.active, "tts_models.json 缺少 active 音色。");
assert(ttsConfig.models?.[ttsConfig.active], "tts_models.json 缺少 active 对应模型配置。");
const activeVoice = ttsConfig.models[ttsConfig.active];
const supportedTtsBackends = ["sherpa_onnx", "voxcpm_cpp_local"];
for (const [voiceName, voiceConfig] of Object.entries(ttsConfig.models || {})) {
  assert(supportedTtsBackends.includes(voiceConfig.backend), `${voiceName} 使用了未知 TTS 后端。`);
}
assert(supportedTtsBackends.includes(activeVoice.backend), "active 音色必须是可生成语音后端。");
assert(ttsConfig.active_reference, "tts_models.json 缺少 active_reference。");
assert(ttsConfig.references?.[ttsConfig.active_reference], "tts_models.json 缺少 active_reference 对应参考音频。");
for (const [referenceName, referenceConfig] of Object.entries(ttsConfig.references || {})) {
  assert(fs.existsSync(path.resolve(projectRoot, referenceConfig.audio_path)), `${referenceName} 参考音频文件不存在。`);
  assert(typeof referenceConfig.prompt_text === "string" && referenceConfig.prompt_text.length > 0, `${referenceName} 缺少参考文本。`);
}

const model3 = readJson(path.join(modelRoot, "Strawberry_Rabbit.model3.json"));
const refs = model3.FileReferences || {};
assert(Array.isArray(refs.Expressions) && refs.Expressions.length >= 20, "model3.json 未声明足够的表情。");
assert(refs.Motions && Object.keys(refs.Motions).length >= 4, "model3.json 未声明动作。");
for (const [motionGroup, motions] of Object.entries(refs.Motions || {})) {
  for (const motion of motions) {
    assert(motion.FadeInTime <= 0.3, `${motionGroup} 动作 FadeInTime 超过 0.3 秒。`);
    assert(motion.FadeOutTime <= 0.3, `${motionGroup} 动作 FadeOutTime 超过 0.3 秒。`);
  }
}
assert(
  Array.isArray(model3.Groups)
    && model3.Groups.some((group) => group.Name === "LipSync" && group.Ids?.includes("ParamMouthOpenY")),
  "model3.json 未声明 ParamMouthOpenY 为 LipSync 参数。"
);

const latestControl = readJson(path.join(stageRoot, "public/control/latest_control.json"));
for (const key of ["text", "emotion", "expression", "motion", "actions", "speech", "parameters"]) {
  assert(Object.prototype.hasOwnProperty.call(latestControl, key), `latest_control.json 缺少 ${key}`);
}
assert(Array.isArray(latestControl.actions), "latest_control.json 的 actions 必须是数组。");

const styles = fs.readFileSync(path.join(stageRoot, "src/styles.css"), "utf8");
assert(styles.includes(".action-list button.is-active"), "styles.css 缺少动作盘激活态样式。");
assert(styles.includes("--stage-control-safe"), "styles.css 缺少舞台底部控件安全区。");
assert(styles.includes(".reference-config-fields[hidden]"), "sherpa 模式必须真正隐藏 VoxCPM 参考音频设置。");
assert(styles.includes("minmax(430px, 560px)"), "styles.css 应允许右侧控制面板扩展。");
assert(styles.includes("height: min(var(--shell-max-height), calc(100dvh - 36px))"), "桌面舞台应利用可用视口高度。");
assert(styles.includes(".mobile-control-button"), "styles.css 缺少移动端控制台快捷入口。");
assert(styles.includes(".stage-fallback"), "styles.css 缺少模型失败提示样式。");
assert(styles.includes("--stage-chat-side"), "styles.css 应让舞台输入区随舞台宽度缩放。");
assert(styles.includes("width: clamp(200px, 32%, 310px)"), "styles.css 应让回复气泡按舞台宽度缩放且避免过大。");
assert(styles.includes("@media (max-width: 1180px)"), "styles.css 应在双栏最小宽度前切换为单栏布局。");
assert(styles.includes(".model-scale-panel"), "styles.css 缺少人物大小滑条样式。");
assert(styles.includes(".model-scale-close"), "styles.css 缺少人物大小面板关闭按钮样式。");
assert(styles.includes("inset: var(--stage-inset);"), "styles.css 应让 Live2D 渲染画布覆盖舞台内区，允许人物越过安全构图区。");
assert(styles.includes(".live2d-canvas.is-dragging"), "styles.css 缺少人物拖放光标状态。");
assert(styles.includes("touch-action: none"), "styles.css 缺少人物拖放触控保护。");
assert(styles.includes(".camera-window"), "styles.css 缺少摄像头悬浮窗样式。");
assert(styles.includes(".camera-resize-handle"), "styles.css 缺少摄像头缩放热区样式。");
assert(styles.includes("var(--camera-aspect-ratio"), "styles.css 缺少摄像头等比例显示样式。");
assert(styles.includes(".audio-window"), "styles.css 缺少麦克风监听悬浮窗样式。");
assert(styles.includes("var(--audio-level"), "styles.css 缺少麦克风音量电平样式。");
assert(styles.includes("transform: scaleY(var(--audio-level, 0))"), "styles.css 应使用竖向麦克风电平条。");
assert(styles.includes(".audio-transcript"), "styles.css 缺少语音识别状态样式。");

const toolsRoot = path.resolve(projectRoot, "tools");
const launchersRoot = path.resolve(toolsRoot, "launchers");
const live2dStageMenuPath = path.join(toolsRoot, "live2d_stage_menu.ps1");
const live2dStageLauncherPath = path.join(launchersRoot, "live2d_stage.bat");
assert(fs.existsSync(live2dStageMenuPath), "tools 缺少统一 Live2D 网页启动菜单。");
assert(fs.existsSync(live2dStageLauncherPath), "launchers 缺少统一 Live2D 网页 BAT 入口。");
const live2dStageMenu = fs.readFileSync(live2dStageMenuPath, "utf8");
assert(live2dStageMenu.includes("一键开启：控制服务 + FER+ 情绪服务 + Live2D 网页 + 浏览器"), "Live2D 启动菜单缺少一键开启选项。");
assert(live2dStageMenu.includes("只开启本地控制 / TTS 服务"), "Live2D 启动菜单缺少独立控制服务选项。");
for (const obsoleteLauncher of [
  "open_live2d_stage.bat",
  "start_live2d_tts.bat",
  "test_live2d_stage.bat",
  "generate_llm_control.bat",
]) {
  assert(!fs.existsSync(path.join(launchersRoot, obsoleteLauncher)), `${obsoleteLauncher} 已合并到 live2d_stage.bat，不应继续保留。`);
}

console.log("Live2D Stage 静态检查通过。");
