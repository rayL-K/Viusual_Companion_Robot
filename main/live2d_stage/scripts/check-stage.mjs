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
assert(html.includes("pixi-live2d-display"), "index.html 缺少 pixi-live2d-display CDN。");
assert(html.includes("live2dcubismcore"), "index.html 缺少 Cubism Core CDN。");
assert(html.includes("chatInput"), "index.html 缺少实时对话输入框。");
assert(html.includes("speechRateInput"), "index.html 缺少语速控制。");
assert(html.includes("voiceList"), "index.html 缺少语音模型列表。");
assert(html.includes("referenceSelect"), "index.html 缺少参考音频选择框。");
assert(html.includes("referenceAudioPreview"), "index.html 缺少参考音频试听控件。");
assert(html.includes("referenceTextInput"), "index.html 缺少参考文本编辑框。");
for (const id of ["actionDiskButton", "voiceModelButton", "skinModelButton", "controlLogButton"]) {
  assert(html.includes(id), `index.html 缺少功能按钮 ${id}。`);
}
assert(html.includes("cameraPanelButton"), "index.html 缺少视觉摄像头按钮。");
assert(html.includes("audioPanelButton"), "index.html 缺少听觉麦克风按钮。");
assert(html.includes("显示运行日志"), "index.html 应将日志入口显示为运行日志。");
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
assert(!html.includes("cameraWindowHandle"), "摄像头预览窗不应保留标题栏。");

const stageScript = fs.readFileSync(path.join(stageRoot, "src/stage.js"), "utf8");
assert(stageScript.includes("setupPointerTracking"), "stage.js 缺少鼠标上下跟随逻辑。");
assert(stageScript.includes("buildMouthTimeline"), "stage.js 缺少语音口型时间线。");
assert(stageScript.includes("VISIBLE_ACTIONS"), "stage.js 缺少可见动作池。");
assert(stageScript.includes("CHAT_API_URL"), "stage.js 缺少浏览器 LLM 聊天接口。");
assert(stageScript.includes("TTS_API_URL"), "stage.js 缺少可替换 TTS 服务入口。");
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
assert(stageScript.includes("AUDIO_DEFAULT_STORAGE_KEY"), "stage.js 缺少默认麦克风持久化配置。");
assert(stageScript.includes("startAudioMonitor"), "stage.js 缺少麦克风监听启动逻辑。");
assert(stageScript.includes("updateAudioLevelLoop"), "stage.js 缺少麦克风音量电平更新逻辑。");
assert(stageScript.includes("setupAudioWindowDrag"), "stage.js 缺少麦克风监听窗拖拽逻辑。");
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

const ttsConfig = readJson(path.resolve(mainRoot, "config/tts_models.json"));
assert(ttsConfig.active, "tts_models.json 缺少 active 音色。");
assert(ttsConfig.models?.[ttsConfig.active], "tts_models.json 缺少 active 对应模型配置。");
const activeVoice = ttsConfig.models[ttsConfig.active];
const supportedTtsBackends = ["voxcpm_hf_space", "voxcpm_project_local", "voxcpm_local", "voxcpm_local_gradio"];
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
assert(styles.includes("--page-height-safe"), "styles.css 缺少浏览器外部 UI 高度缓冲。");
assert(styles.includes("--shell-design-width: 1840"), "styles.css 应扩大舞台设计宽度，减少右侧空白。");
assert(styles.includes("minmax(430px, 560px)"), "styles.css 应允许右侧控制面板扩展。");
assert(styles.includes("var(--shell-design-width) / var(--shell-design-height)"), "styles.css 应让舞台宽高按共享设计比例同步。");
assert(styles.includes("--stage-chat-side"), "styles.css 应让舞台输入区随舞台宽度缩放。");
assert(styles.includes("width: clamp(200px, 32%, 310px)"), "styles.css 应让回复气泡按舞台宽度缩放且避免过大。");
assert(styles.includes(".camera-window"), "styles.css 缺少摄像头悬浮窗样式。");
assert(styles.includes(".camera-resize-handle"), "styles.css 缺少摄像头缩放热区样式。");
assert(styles.includes("var(--camera-aspect-ratio"), "styles.css 缺少摄像头等比例显示样式。");
assert(styles.includes(".audio-window"), "styles.css 缺少麦克风监听悬浮窗样式。");
assert(styles.includes("var(--audio-level"), "styles.css 缺少麦克风音量电平样式。");
assert(styles.includes("transform: scaleY(var(--audio-level, 0))"), "styles.css 应使用竖向麦克风电平条。");

console.log("Live2D Stage 静态检查通过。");
