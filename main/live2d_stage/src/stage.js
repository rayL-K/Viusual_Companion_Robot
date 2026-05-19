const MODEL_URL = "/live2d/Strawberry_Rabbit/Strawberry_Rabbit.model3.json";
const MANIFEST_URL = "/live2d/Strawberry_Rabbit/manifest.json";
const CONTROL_URL = "/control/latest_control.json";
const CHAT_API_URL = "http://127.0.0.1:8765/chat";
const TTS_API_URL = "http://127.0.0.1:8765/tts";
const VOICES_API_URL = "http://127.0.0.1:8765/voices";
const TTS_HEALTH_API_URL = "http://127.0.0.1:8765/tts-health";
const TTS_RUNTIME_API_URL = "http://127.0.0.1:8765/tts-runtime";
const REFERENCE_AUDIO_URL = "http://127.0.0.1:8765/reference-audio";
const STAGE_VIEW_MODE = "fullbody";
const DEFAULT_SPEECH_RATE = 1.12;
const ACTION_FADE_MS = 300;
const REPLY_STREAM_INTERVAL_MS = 42;
const IDLE_DELAY_RANGE_MS = { min: 8000, max: 15000 };
const THINKING_MOTION_SEQUENCE = ["captain", "admiral", "governor"];
const IDLE_ACTION_NAMES = ["blush", "heart", "question", "flowers", "star_eyes", "sweat", "twin_tail"];
const STAGE_MODEL_FIT = {
  fullbody: {
    widthRatio: 0.72,
    heightRatio: 0.84,
    centerX: 0.58,
    bottomY: 1.08,
  },
  portrait: {
    widthRatio: 0.78,
    heightRatio: 0.82,
    centerX: 0.48,
    centerY: 0.98,
  },
};
const CAMERA_DEFAULT_STORAGE_KEY = "visual-companion.default-camera-id";
const CAMERA_WINDOW_POSITION_STORAGE_KEY = "visual-companion.camera-window-position";
const CAMERA_WINDOW_WIDTH_STORAGE_KEY = "visual-companion.camera-window-width";
const CAMERA_WINDOW_MIN_WIDTH = 180;
const CAMERA_WINDOW_MAX_WIDTH = 720;
const AUDIO_DEFAULT_STORAGE_KEY = "visual-companion.default-audio-id";
const AUDIO_WINDOW_POSITION_STORAGE_KEY = "visual-companion.audio-window-position";
const AUDIO_ANALYSER_FFT_SIZE = 512;
const POINTER_FOLLOW_LIMITS = {
  angleX: 34,
  angleY: 24,
  angleZ: 12,
  bodyX: 13,
  bodyY: 9,
  eyeX: 1,
  eyeY: 0.95,
};
const ACTION_PARAMETER_IDS = [
  "Param",
  "Param2",
  "Param3",
  "Param4",
  "Param5",
  "Param6",
  "Param7",
  "Param8",
  "Param9",
  "Param10",
  "Param11",
  "Param12",
  "Param13",
  "Param14",
  "Param15",
  "Param16",
  "Param17",
  "Param26",
  "Param79",
  "Param80",
  "Param81",
  "Param82",
  "Param85",
  "Param267",
];
const VISIBLE_ACTIONS = [
  { name: "right_hand_up", group: "right_hand", conflictGroups: ["right_hand", "both_hands"], label: "1 右抬手", hotkey: "小键盘1", expression: "right_hand_up", parameters: { Param17: 1, Param14: 0, Param15: 0, Param16: 0 }, durationMs: 3200, defaultMode: "hold" },
  { name: "left_hand_up", group: "left_hand", conflictGroups: ["left_hand", "both_hands"], label: "2 左抬手", hotkey: "小键盘2", expression: "left_hand_up", parameters: { Param267: 1, Param14: 0, Param15: 0, Param16: 0 }, durationMs: 3200, defaultMode: "hold" },
  { name: "twin_tail", group: "hair_style", label: "3 双马尾", hotkey: "小键盘3", expression: "twin_tail", parameters: { Param: 1 }, durationMs: 3200, defaultMode: "hold" },
  { name: "microphone", group: "both_hands", conflictGroups: ["right_hand", "left_hand", "both_hands"], label: "4 麦克风", hotkey: "小键盘4", expression: "microphone", parameters: { Param16: 1, Param14: 0, Param15: 0, Param17: 0, Param267: 0 }, durationMs: 3200, defaultMode: "hold" },
  { name: "finger_heart", group: "both_hands", conflictGroups: ["right_hand", "left_hand", "both_hands"], label: "5 比心", hotkey: "小键盘5", expression: "finger_heart", parameters: { Param15: 1, Param14: 0, Param16: 0, Param17: 0, Param267: 0 }, durationMs: 3200, defaultMode: "hold" },
  { name: "gaming", group: "both_hands", conflictGroups: ["right_hand", "left_hand", "both_hands"], label: "6 游戏机", hotkey: "小键盘6", expression: "gaming", parameters: { Param14: 1, Param15: 0, Param16: 0, Param17: 0, Param267: 0 }, durationMs: 3200, defaultMode: "hold" },
  { name: "shadow_face", group: "face_effect", label: "7 黑脸", hotkey: "小键盘7", expression: "shadow_face", parameters: { Param2: 1 }, durationMs: 2600, defaultMode: "pulse" },
  { name: "cry", group: "face_effect", label: "8 哭哭", hotkey: "小键盘8", expression: "cry", parameters: { Param8: 1 }, durationMs: 2600, defaultMode: "pulse" },
  { name: "heart", group: "face_effect", label: "9 爱心眼", hotkey: "小键盘9", expression: "heart", parameters: { Param6: 1 }, durationMs: 2600, defaultMode: "pulse" },
  { name: "star_eyes", group: "face_effect", label: "10 星星眼", hotkey: "Ctrl+1", expression: "star_eyes", parameters: { Param7: 1 }, durationMs: 2600, defaultMode: "pulse" },
  { name: "dizzy", group: "face_effect", label: "11 晕晕", hotkey: "Ctrl+2", expression: "dizzy", parameters: { Param5: 1 }, durationMs: 2600, defaultMode: "pulse" },
  { name: "sweat", group: "face_effect", label: "12 流汗", hotkey: "Ctrl+3", expression: "sweat", parameters: { Param11: 1 }, durationMs: 2600, defaultMode: "pulse" },
  { name: "anxious", group: "face_effect", label: "13 着急", hotkey: "Ctrl+4", expression: "anxious", parameters: { Param12: 1 }, durationMs: 2600, defaultMode: "pulse" },
  { name: "angry", group: "face_effect", label: "14 生气", hotkey: "Ctrl+5", expression: "angry", parameters: { Param10: 1 }, durationMs: 2600, defaultMode: "pulse" },
  { name: "blush", group: "face_effect", label: "15 脸红", hotkey: "Ctrl+6", expression: "blush", parameters: { Param3: 1 }, durationMs: 2600, defaultMode: "pulse" },
  { name: "flowers", group: "face_effect", label: "16 花花", hotkey: "Ctrl+7", expression: "flowers", parameters: { Param9: 1 }, durationMs: 2600, defaultMode: "pulse" },
  { name: "question", group: "face_effect", label: "17 问号", hotkey: "Ctrl+8", expression: "question", parameters: { Param13: 1 }, durationMs: 2600, defaultMode: "pulse" },
  { name: "dark_mode", group: "face_effect", label: "18 黑化", hotkey: "Ctrl+9", expression: "dark_mode", parameters: { Param4: 1 }, durationMs: 2600, defaultMode: "pulse" },
  { name: "captain", group: "roulette", label: "19 舰长轮盘", hotkey: "Ctrl+Z", motion: "captain", parameters: {}, durationMs: 2600, defaultMode: "pulse" },
  { name: "admiral", group: "roulette", label: "20 提督轮盘", hotkey: "Ctrl+X", motion: "admiral", parameters: {}, durationMs: 2600, defaultMode: "pulse" },
  { name: "governor", group: "roulette", label: "21 总督轮盘", hotkey: "Ctrl+C", motion: "governor", parameters: {}, durationMs: 2600, defaultMode: "pulse" },
  { name: "up", group: "gamepad_key", label: "游戏上", hotkey: "↑", expression: "up", parameters: { Param81: 1 }, durationMs: 1800, defaultMode: "pulse" },
  { name: "down", group: "gamepad_key", label: "游戏下", hotkey: "↓", expression: "down", parameters: { Param79: 1 }, durationMs: 1800, defaultMode: "pulse" },
  { name: "left", group: "gamepad_key", label: "游戏左", hotkey: "←", expression: "left", parameters: { Param82: 1 }, durationMs: 1800, defaultMode: "pulse" },
  { name: "right", group: "gamepad_key", label: "游戏右", hotkey: "→", expression: "right", parameters: { Param80: 1 }, durationMs: 1800, defaultMode: "pulse" },
  { name: "plus", group: "gamepad_key", label: "游戏Shift", hotkey: "Shift", expression: "plus", parameters: { Param85: 1 }, durationMs: 1800, defaultMode: "pulse" },
  { name: "scene1", group: "motion", label: "待机动作", motion: "scene1", parameters: {}, durationMs: 2600, defaultMode: "pulse" },
];
const ACTIONS_BY_NAME = Object.fromEntries(VISIBLE_ACTIONS.map((action) => [action.name, action]));

const demoPlan = {
  text: "主人，草莓兔兔已经准备好啦。现在我可以用表情、动作和口型配合回答你。",
  emotion: "happy",
  expression: "heart",
  motion: "scene1",
  speech: {
    voice: "female_zh",
    rate: DEFAULT_SPEECH_RATE,
    pitch: 1.18,
  },
  parameters: {
    ParamAngleX: 4,
    ParamAngleY: 2,
    ParamBodyAngleX: 3,
    ParamMouthForm: 0.35,
  },
};

const modelState = {
  app: null,
  model: null,
  manifest: null,
  currentPlan: demoPlan,
  speaking: false,
  speechPaused: false,
  speakingStartedAt: 0,
  mouthBase: 0,
  mouthCurrent: 0,
  mouthTarget: 0,
  mouthFormTarget: 0,
  mouthTimeline: [],
  speechBoundaryAt: 0,
  speechBoundaryTarget: null,
  speechRequestId: 0,
  audio: null,
  audioUrl: "",
  replyStreamTimer: 0,
  replyTargetText: "",
  generatingSpeech: false,
  thinkingAnimationToken: 0,
  thinkingMotionTimer: 0,
  thinkingMotionIndex: 0,
  idleTimer: 0,
  pointer: {
    active: false,
    x: 0,
    y: 0,
    targetX: 0,
    targetY: 0,
  },
  baseParameters: {},
  activeActions: [],
  scheduledActionTimers: [],
  voiceModels: {},
  voiceReferences: {},
  selectedVoice: "",
  selectedReference: "",
  referencePromptText: "",
  voiceRuntimeRequestId: 0,
  fitModelFrame: 0,
  stageResizeObserver: null,
  cameraDevices: [],
  selectedCameraId: "",
  defaultCameraId: "",
  cameraStream: null,
  cameraDrag: null,
  cameraResize: null,
  audioDevices: [],
  selectedAudioId: "",
  defaultAudioId: "",
  audioStream: null,
  audioContext: null,
  audioSource: null,
  audioAnalyser: null,
  audioLevelData: null,
  audioLevelFrame: 0,
  audioDrag: null,
};

const statusEl = document.getElementById("stageStatus");
const hintEl = document.getElementById("stageHint");
const replyBubbleEl = document.getElementById("replyBubble");
const replyEl = document.getElementById("replyText");
const expressionEl = document.getElementById("expressionValue");
const motionEl = document.getElementById("motionValue");
const emotionEl = document.getElementById("emotionValue");
const voiceEl = document.getElementById("voiceValue");
const canvasHost = document.getElementById("live2dCanvas");
const chatForm = document.getElementById("chatForm");
const chatInput = document.getElementById("chatInput");
const speechRateInput = document.getElementById("speechRateInput");
const speechRateValue = document.getElementById("speechRateValue");
const actionPanel = document.getElementById("actionPanel");
const voicePanel = document.getElementById("voicePanel");
const skinPanel = document.getElementById("skinPanel");
const cameraPanel = document.getElementById("cameraPanel");
const audioPanel = document.getElementById("audioPanel");
const logPanel = document.getElementById("logPanel");
const historyPanel = document.getElementById("historyPanel");
const actionListEl = document.getElementById("actionList");
const voiceListEl = document.getElementById("voiceList");
const referenceSelectEl = document.getElementById("referenceSelect");
const referenceAudioPreviewEl = document.getElementById("referenceAudioPreview");
const referenceTextInputEl = document.getElementById("referenceTextInput");
const referenceHintEl = document.getElementById("referenceHint");
const cameraSelectEl = document.getElementById("cameraSelect");
const cameraDetectButton = document.getElementById("cameraDetectButton");
const cameraStartButton = document.getElementById("cameraStartButton");
const cameraStopButton = document.getElementById("cameraStopButton");
const cameraDefaultButton = document.getElementById("cameraDefaultButton");
const cameraStatusEl = document.getElementById("cameraStatus");
const cameraWindowEl = document.getElementById("cameraWindow");
const cameraPreviewEl = document.getElementById("cameraPreview");
const cameraResizeHandleEl = document.getElementById("cameraResizeHandle");
const cameraWindowStatusEl = document.getElementById("cameraWindowStatus");
const audioSelectEl = document.getElementById("audioSelect");
const audioDetectButton = document.getElementById("audioDetectButton");
const audioStartButton = document.getElementById("audioStartButton");
const audioStopButton = document.getElementById("audioStopButton");
const audioDefaultButton = document.getElementById("audioDefaultButton");
const audioStatusEl = document.getElementById("audioStatus");
const audioWindowEl = document.getElementById("audioWindow");
const audioWindowStatusEl = document.getElementById("audioWindowStatus");
const controlLogEl = document.getElementById("controlLog");
const historyListEl = document.getElementById("historyList");
const controlLogs = [];
const MAX_RUNTIME_LOG_ITEMS = 120;
const chatHistory = [];
const actionButtons = new Map();
const sidePanels = [actionPanel, voicePanel, skinPanel, cameraPanel, audioPanel, logPanel, historyPanel];

function setStatus(message, hint = "") {
  statusEl.textContent = message;
  if (hint) {
    hintEl.textContent = hint;
  }
}

function setReplyThinking() {
  clearReplyStream();
  replyBubbleEl.classList.add("is-thinking");
  replyEl.textContent = "...";
}

function setReplyText(text) {
  clearReplyStream();
  setReplyTextContent(text);
}

function setReplyTextContent(text) {
  replyBubbleEl.classList.remove("is-thinking");
  replyEl.textContent = text;
}

function startReplyStream(text, rate) {
  clearReplyStream();
  const chars = Array.from(String(text || ""));
  const intervalMs = clamp(REPLY_STREAM_INTERVAL_MS / Math.max(rate || 1, 0.1), 24, 80);
  let index = 0;
  modelState.replyTargetText = chars.join("");
  setReplyTextContent("");
  if (!chars.length) {
    return;
  }
  modelState.replyStreamTimer = window.setInterval(() => {
    index += 1;
    setReplyTextContent(chars.slice(0, index).join(""));
    if (index >= chars.length) {
      clearReplyStream({ keepText: true });
    }
  }, intervalMs);
}

function clearReplyStream(options = {}) {
  if (modelState.replyStreamTimer) {
    window.clearInterval(modelState.replyStreamTimer);
    modelState.replyStreamTimer = 0;
  }
  if (!options.keepText) {
    modelState.replyTargetText = "";
  }
}

function finishReplyStream() {
  if (modelState.replyStreamTimer) {
    const targetText = modelState.replyTargetText;
    clearReplyStream();
    setReplyTextContent(targetText);
  }
}

function addControlLog(type, payload) {
  const item = {
    time: new Date().toLocaleTimeString("zh-CN", { hour12: false }),
    type,
    payload,
  };
  controlLogs.unshift(item);
  if (controlLogs.length > MAX_RUNTIME_LOG_ITEMS) {
    controlLogs.pop();
  }
  renderControlLog();
}

function renderControlLog() {
  if (!controlLogs.length) {
    controlLogEl.textContent = "暂无运行日志。";
    return;
  }
  controlLogEl.textContent = controlLogs
    .map((item) => `[${item.time}] ${item.type}\n${JSON.stringify(item.payload, null, 2)}`)
    .join("\n\n");
}

function addChatHistory(userText, robotText, plan = null, error = "") {
  chatHistory.unshift({
    time: new Date().toLocaleTimeString("zh-CN", { hour12: false }),
    userText,
    robotText,
    plan,
    error,
  });
  if (chatHistory.length > 40) {
    chatHistory.pop();
  }
  renderChatHistory();
}

function renderChatHistory() {
  historyListEl.replaceChildren();
  if (!chatHistory.length) {
    historyListEl.textContent = "暂无历史记录。";
    return;
  }
  chatHistory.forEach((item) => {
    const card = document.createElement("article");
    card.className = "history-item";

    const meta = document.createElement("div");
    meta.className = "history-meta";
    meta.textContent = item.error ? `${item.time} 失败` : item.time;

    const userBubble = document.createElement("div");
    userBubble.className = "history-bubble user";
    userBubble.textContent = item.userText;

    const robotBubble = document.createElement("div");
    robotBubble.className = "history-bubble robot";
    robotBubble.textContent = item.robotText || item.error || "无回复";

    card.append(meta, userBubble, robotBubble);
    historyListEl.appendChild(card);
  });
}

function openSidePanel(panel) {
  sidePanels.forEach((item) => {
    item.hidden = item !== panel;
  });
}

function toggleSidePanel(panel) {
  if (!panel.hidden) {
    closeSidePanel(panel);
    return;
  }
  openSidePanel(panel);
}

function closeSidePanel(panel) {
  panel.hidden = true;
}

function waitForRuntime() {
  if (!window.PIXI || !window.PIXI.live2d?.Live2DModel) {
    throw new Error("PixiJS 或 pixi-live2d-display 未加载，请检查 CDN 网络。");
  }
}

async function loadJson(url) {
  const response = await fetch(url, { cache: "no-cache" });
  if (!response.ok) {
    throw new Error(`${url} 加载失败：HTTP ${response.status}`);
  }
  return response.json();
}

async function initStage() {
  waitForRuntime();
  modelState.manifest = await loadJson(MANIFEST_URL);

  const app = new PIXI.Application({
    resizeTo: canvasHost,
    backgroundAlpha: 0,
    antialias: true,
    autoDensity: true,
    resolution: Math.min(window.devicePixelRatio || 1, 2),
  });
  canvasHost.appendChild(app.view);
  modelState.app = app;

  const model = await PIXI.live2d.Live2DModel.from(MODEL_URL, { autoInteract: false });
  modelState.model = model;
  app.stage.addChild(model);
  resetDisplayParameters();
  fitModel();

  window.addEventListener("resize", handleViewportResize);
  if ("ResizeObserver" in window) {
    modelState.stageResizeObserver = new ResizeObserver(requestFitModel);
    modelState.stageResizeObserver.observe(canvasHost);
  }
  setupPointerTracking();
  app.ticker.add(updateModelParameters);
  setStatus("Live2D 模型已加载", "可以直接在下方输入框对话，或从右侧动作盘手动测试动作。");
  await loadVoiceModels();
  await loadInitialControl();
  scheduleIdleAction();
}

function fitModel() {
  const { app, model } = modelState;
  if (!app || !model) {
    return;
  }

  const hostRect = canvasHost.getBoundingClientRect();
  const width = Math.max(1, Math.round(hostRect.width || canvasHost.clientWidth));
  const height = Math.max(1, Math.round(hostRect.height || canvasHost.clientHeight));
  app.renderer.resize(width, height);
  model.scale.set(1);
  const bounds = model.getLocalBounds();
  const safeWidth = Math.max(bounds.width, 1);
  const safeHeight = Math.max(bounds.height, 1);
  const fit = STAGE_VIEW_MODE === "fullbody" ? STAGE_MODEL_FIT.fullbody : STAGE_MODEL_FIT.portrait;
  const baseScale = Math.min((width * fit.widthRatio) / safeWidth, (height * fit.heightRatio) / safeHeight);
  const scale = STAGE_VIEW_MODE === "portrait" ? baseScale * 2.35 : baseScale;
  model.scale.set(scale);
  model.x = width * fit.centerX - (bounds.x + safeWidth / 2) * scale;
  if (STAGE_VIEW_MODE === "fullbody") {
    model.y = height * fit.bottomY - (bounds.y + safeHeight) * scale;
    return;
  }
  model.y = height * fit.centerY - (bounds.y + safeHeight / 2) * scale;
}

function requestFitModel() {
  if (modelState.fitModelFrame) {
    window.cancelAnimationFrame(modelState.fitModelFrame);
  }
  modelState.fitModelFrame = window.requestAnimationFrame(() => {
    modelState.fitModelFrame = 0;
    fitModel();
  });
}

function handleViewportResize() {
  requestFitModel();
  if (!cameraWindowEl.hidden) {
    const rect = cameraWindowEl.getBoundingClientRect();
    setCameraWindowPosition(rect.left, rect.top);
  }
  if (!audioWindowEl.hidden) {
    const rect = audioWindowEl.getBoundingClientRect();
    setAudioWindowPosition(rect.left, rect.top);
  }
}

function setupPointerTracking() {
  document.addEventListener("pointermove", updatePointerTargetFromEvent, { passive: true });
  window.addEventListener("pointerout", (event) => {
    if (!event.relatedTarget) {
      resetPointerTarget();
    }
  });
  window.addEventListener("blur", resetPointerTarget);
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      resetPointerTarget();
    }
  });
}

function updatePointerTargetFromEvent(event) {
  const rect = canvasHost.getBoundingClientRect();
  const x = ((event.clientX - rect.left) / Math.max(rect.width, 1)) * 2 - 1;
  const y = ((event.clientY - rect.top) / Math.max(rect.height, 1)) * 2 - 1;
  modelState.pointer.active = true;
  modelState.pointer.targetX = clamp(x, -1, 1);
  modelState.pointer.targetY = clamp(-y, -1, 1);
}

function resetPointerTarget() {
  modelState.pointer.active = false;
  modelState.pointer.targetX = 0;
  modelState.pointer.targetY = 0;
}

function resetDisplayParameters() {
  const hiddenByDefault = {
    Param44: 0,
    Param59: 0,
    Param60: 0,
    Param61: 0,
    Param62: 0,
    Param63: 0,
    Param64: 0,
    Param65: 0,
    Param78: 0,
    Param261: 1,
  };
  Object.entries(hiddenByDefault).forEach(([id, value]) => setParameter(id, value, 1));
}

function setParameter(id, value, weight = 1) {
  const coreModel = modelState.model?.internalModel?.coreModel;
  if (!coreModel || typeof coreModel.setParameterValueById !== "function") {
    return;
  }
  try {
    coreModel.setParameterValueById(id, value, weight);
  } catch (error) {
    console.warn(`参数写入失败：${id}`, error);
  }
}

function updateModelParameters() {
  if (!modelState.model) {
    return;
  }

  const now = performance.now();
  const seconds = now / 1000;
  const breathing = Math.sin(seconds * 2.1) * 0.5 + 0.5;
  const eyeBlink = blinkingValue(seconds);
  updatePointerFollow();
  updateActionParameters(now);
  updateActionButtonStates(now);
  updateMouthSync(now);

  resetDisplayParameters();
  setParameter("ParamBreath", breathing);
  setParameter("ParamEyeLOpen", eyeBlink);
  setParameter("ParamEyeROpen", eyeBlink);
  applyBaseParameters();
  applyPointerParameters();
  applyHeldActionParameters(now);
  setParameter("ParamMouthOpenY", modelState.mouthCurrent);
  setParameter("ParamMouthForm", modelState.mouthFormTarget);
}

function blinkingValue(seconds) {
  const cycle = seconds % 4.2;
  if (cycle < 0.08) {
    return 0.15;
  }
  if (cycle < 0.16) {
    return 0.45;
  }
  return 1;
}

function updatePointerFollow() {
  const pointer = modelState.pointer;
  pointer.x += (pointer.targetX - pointer.x) * 0.18;
  pointer.y += (pointer.targetY - pointer.y) * 0.18;
}

function applyPointerParameters() {
  const { x, y } = modelState.pointer;
  const natural = naturalHeadMotion(performance.now() / 1000);
  setParameter("ParamAngleX", natural.angleX + x * POINTER_FOLLOW_LIMITS.angleX);
  setParameter("ParamAngleY", natural.angleY + y * POINTER_FOLLOW_LIMITS.angleY);
  setParameter("ParamAngleZ", natural.angleZ - x * POINTER_FOLLOW_LIMITS.angleZ);
  setParameter("ParamBodyAngleX", natural.bodyX + x * POINTER_FOLLOW_LIMITS.bodyX);
  setParameter("ParamBodyAngleX2", natural.bodyX * 0.65 + x * POINTER_FOLLOW_LIMITS.bodyX * 0.65);
  setParameter("ParamBodyAngleY", natural.bodyY + y * POINTER_FOLLOW_LIMITS.bodyY);
  setParameter("ParamEyeBallX", x * POINTER_FOLLOW_LIMITS.eyeX);
  setParameter("ParamEyeBallY", y * POINTER_FOLLOW_LIMITS.eyeY);
}

function naturalHeadMotion(seconds) {
  const calmWeight = modelState.generatingSpeech ? 0.85 : modelState.speaking ? 0.75 : 1;
  return {
    angleX: (Math.sin(seconds * 0.73) * 4.8 + Math.sin(seconds * 1.37) * 1.6) * calmWeight,
    angleY: (Math.sin(seconds * 0.91 + 0.8) * 3.4 + Math.sin(seconds * 1.61) * 1.1) * calmWeight,
    angleZ: Math.sin(seconds * 0.53 + 1.6) * 2.4 * calmWeight,
    bodyX: Math.sin(seconds * 0.47 + 0.4) * 3.2 * calmWeight,
    bodyY: Math.sin(seconds * 0.67 + 1.2) * 2.2 * calmWeight,
  };
}

function applyBaseParameters() {
  Object.entries(modelState.baseParameters).forEach(([id, value]) => setParameter(id, value, 1));
}

function updateActionParameters(now) {
  modelState.activeActions = modelState.activeActions.filter((action) => action.endsAt === null || now <= action.endsAt);
}

function updateActionButtonStates(now = performance.now()) {
  VISIBLE_ACTIONS.forEach((action) => {
    const button = actionButtons.get(action.name);
    if (button) {
      button.classList.toggle("is-active", isVisibleActionActive(action, now));
    }
  });
}

function applyHeldActionParameters(now) {
  const mixedParameters = {};
  ACTION_PARAMETER_IDS.forEach((id) => setParameter(id, 0, 1));
  modelState.activeActions.forEach((action) => {
    const weight = actionFadeWeight(action, now);
    Object.entries(action.parameters).forEach(([id, value]) => {
      mixedParameters[id] = (mixedParameters[id] || 0) + Number(value) * weight;
    });
  });
  Object.entries(mixedParameters).forEach(([id, value]) => setParameter(id, clamp(value, 0, 1), 1));
}

function actionFadeWeight(action, now) {
  const fadeIn = clamp((now - action.startedAt) / ACTION_FADE_MS, 0, 1);
  if (action.endsAt === null) {
    return fadeIn;
  }
  const fadeOut = clamp((action.endsAt - now) / ACTION_FADE_MS, 0, 1);
  return Math.min(fadeIn, fadeOut);
}

function updateMouthSync(now) {
  const target = resolveMouthTarget(now);
  const closeSpeed = target.open < modelState.mouthCurrent ? 0.56 : 0.38;
  const formSpeed = target.form < modelState.mouthFormTarget ? 0.42 : 0.28;
  modelState.mouthTarget = target.open;
  modelState.mouthFormTarget += (target.form - modelState.mouthFormTarget) * formSpeed;
  modelState.mouthCurrent += (modelState.mouthTarget - modelState.mouthCurrent) * closeSpeed;
  if (!modelState.speaking && modelState.mouthCurrent < 0.025) {
    modelState.mouthCurrent = 0;
  }
}

function resolveMouthTarget(now) {
  if (!modelState.speaking || modelState.speechPaused) {
    return { open: modelState.mouthBase, form: 0 };
  }

  if (modelState.speechBoundaryTarget && now - modelState.speechBoundaryAt < 210) {
    return modelState.speechBoundaryTarget;
  }

  const elapsed = now - modelState.speakingStartedAt;
  return mouthTargetAt(elapsed, modelState.mouthTimeline);
}

function mouthTargetAt(elapsedMs, timeline) {
  if (!timeline.length) {
    return { open: 0.32, form: 0 };
  }
  const item = timeline.find((entry) => elapsedMs >= entry.startMs && elapsedMs < entry.endMs);
  if (!item) {
    return { open: 0, form: 0 };
  }
  const progress = (elapsedMs - item.startMs) / Math.max(item.endMs - item.startMs, 1);
  if (item.silence) {
    return { open: 0, form: 0 };
  }
  const envelope = progress < 0.18 ? progress / 0.18 : progress > 0.72 ? (1 - progress) / 0.28 : 1;
  return {
    open: clamp(item.open * clamp(envelope, 0, 1), 0, 1),
    form: item.form,
  };
}

async function applyPlan(plan, options = { speak: true }) {
  clearScheduledActions();
  modelState.currentPlan = normalizePlan(plan);
  const shouldSpeak = options.speak !== false;
  if (shouldSpeak) {
    setReplyThinking();
  } else {
    setReplyText(modelState.currentPlan.text);
  }
  expressionEl.textContent = modelState.currentPlan.expression || "无";
  motionEl.textContent = modelState.currentPlan.motion || "无";
  emotionEl.textContent = modelState.currentPlan.emotion || "neutral";
  addControlLog("Live2D 控制计划", {
    text: modelState.currentPlan.text,
    emotion: modelState.currentPlan.emotion,
    expression: modelState.currentPlan.expression || "无",
    motion: modelState.currentPlan.motion || "无",
    speech: {
      rate: currentSpeechRate(modelState.currentPlan),
      pitch: modelState.currentPlan.speech.pitch,
    },
    actions: modelState.currentPlan.actions,
    parameters: modelState.currentPlan.parameters,
  });

  if (shouldSpeak) {
    speakPlan(modelState.currentPlan);
    return;
  }

  await applyPlanVisuals(modelState.currentPlan);
}

async function applyPlanVisuals(plan) {
  if (plan.actions.length) {
    await applyActionControls(plan.actions);
  } else {
    await applyExpression(plan.expression);
  }
  await applyMotion(plan.motion);
  applyParameters(plan.parameters);
}

function normalizePlan(plan) {
  return {
    text: String(plan?.text || demoPlan.text),
    emotion: String(plan?.emotion || "neutral"),
    expression: plan?.expression ? String(plan.expression) : "",
    motion: plan?.motion ? String(plan.motion) : "",
    actions: Array.isArray(plan?.actions) ? plan.actions.map(normalizeActionControl).filter(Boolean) : [],
    speech: {
      voice: String(plan?.speech?.voice || "female_zh"),
      rate: Number(plan?.speech?.rate || DEFAULT_SPEECH_RATE),
      pitch: Number(plan?.speech?.pitch || 1.15),
    },
    parameters: plan?.parameters && typeof plan.parameters === "object" ? plan.parameters : {},
  };
}

function normalizeActionControl(action) {
  if (!action || typeof action !== "object") {
    return null;
  }
  const name = String(action.name || action.expression || action.motion || "");
  if (!actionByName(name)) {
    return null;
  }
  const mode = ["hold", "pulse", "off"].includes(action.mode) ? action.mode : "pulse";
  return {
    name,
    mode,
    durationMs: clamp(Number(action.durationMs || action.duration_ms || 2600), 300, 10000),
    delayMs: clamp(Number(action.delayMs || action.delay_ms || 0), 0, 30000),
  };
}

async function applyExpression(expressionName) {
  if (!expressionName || !modelState.model) {
    return;
  }
  try {
    const action = VISIBLE_ACTIONS.find((item) => item.expression === expressionName);
    if (action?.parameters) {
      holdVisibleAction(action);
      return;
    }
    if (typeof modelState.model.expression === "function") {
      await modelState.model.expression(expressionName);
    }
  } catch (error) {
    console.warn(`表情触发失败：${expressionName}`, error);
  }
}

async function applyExpressionAsset(expressionName) {
  if (!expressionName || !modelState.model) {
    return;
  }
  try {
    if (typeof modelState.model.expression === "function") {
      await modelState.model.expression(expressionName);
    }
  } catch (error) {
    console.warn(`表情资源触发失败：${expressionName}`, error);
  }
}

async function applyMotion(motionName) {
  if (!motionName || !modelState.model) {
    return;
  }
  try {
    if (typeof modelState.model.motion === "function") {
      await modelState.model.motion(motionName, 0);
    }
  } catch (error) {
    console.warn(`动作触发失败：${motionName}`, error);
  }
}

function applyParameters(parameters) {
  const allowed = new Set([
    "ParamMouthForm",
    "ParamMouthOpenY",
  ]);

  modelState.baseParameters = {};
  modelState.mouthBase = 0;
  Object.entries(parameters || {}).forEach(([id, value]) => {
    if (!allowed.has(id)) {
      return;
    }
    if (id === "ParamMouthOpenY") {
      modelState.mouthBase = Math.max(0, Math.min(1, Number(value)));
      return;
    }
    modelState.baseParameters[id] = Number(value);
  });
}

async function speakPlan(plan) {
  stopSpeechPlayback();
  const requestId = ++modelState.speechRequestId;
  const rate = currentSpeechRate(plan);
  if (!modelState.generatingSpeech) {
    startThinkingAnimation();
  }
  setSpeechStatus(requestId, `正在生成 ${currentBackendLabel()} 音频`, "VoxCPM 生成完成后会自动播放。");

  try {
    const audioBlob = await requestExternalTts(plan, rate);
    const played = await playExternalAudio(audioBlob, plan, rate, requestId);
    if (!played) {
      stopThinkingAnimation({ restoreMotion: true, clearRoulette: true });
      setReplyText(plan.text);
      setSpeechStatus(requestId, `${currentBackendLabel()} 音频播放失败`, "浏览器拒绝自动播放音频；请点击页面后重试。");
      scheduleIdleAction();
    }
  } catch (error) {
    console.warn("TTS 服务不可用。", error);
    stopThinkingAnimation({ restoreMotion: true, clearRoulette: true });
    setReplyText(plan.text);
    setTtsErrorStatus(error, requestId);
    scheduleIdleAction();
  }
}

function startThinkingAnimation() {
  stopThinkingAnimation({ restoreMotion: false, clearRoulette: false });
  const token = ++modelState.thinkingAnimationToken;
  modelState.generatingSpeech = true;
  modelState.thinkingMotionIndex = 0;
  playNextThinkingMotion(token);
  modelState.thinkingMotionTimer = window.setInterval(() => {
    playNextThinkingMotion(token);
  }, 760);
}

function playNextThinkingMotion(token) {
  if (token !== modelState.thinkingAnimationToken || !modelState.generatingSpeech) {
    return;
  }
  const motion = THINKING_MOTION_SEQUENCE[modelState.thinkingMotionIndex % THINKING_MOTION_SEQUENCE.length];
  modelState.thinkingMotionIndex += 1;
  applyMotion(motion).catch((error) => {
    addControlLog("生成等待动画失败", { motion, error: error.message });
  });
}

function stopThinkingAnimation(options = { restoreMotion: true, clearRoulette: false }) {
  if (modelState.thinkingMotionTimer) {
    window.clearInterval(modelState.thinkingMotionTimer);
    modelState.thinkingMotionTimer = 0;
  }
  modelState.thinkingAnimationToken += 1;
  modelState.generatingSpeech = false;
  if (options.clearRoulette) {
    clearRouletteMotionArtifacts().catch((error) => {
      addControlLog("清理轮盘动作失败", { error: error.message });
    });
  }
  if (options.restoreMotion && modelState.currentPlan.motion) {
    applyMotion(modelState.currentPlan.motion).catch((error) => {
      addControlLog("恢复动作失败", { motion: modelState.currentPlan.motion, error: error.message });
    });
  }
}

async function clearRouletteMotionArtifacts() {
  closeActionGroup("roulette");
  updateActionButtonStates();
  await applyMotion("scene1");
}

async function applyPlanVisualsForSpeech(plan) {
  await applyPlanVisuals(plan);
}

function stopSpeechPlayback() {
  if (modelState.audio) {
    modelState.audio.onplay = null;
    modelState.audio.onpause = null;
    modelState.audio.onended = null;
    modelState.audio.onerror = null;
    modelState.audio.pause();
    modelState.audio.src = "";
    modelState.audio = null;
  }
  if (modelState.audioUrl) {
    URL.revokeObjectURL(modelState.audioUrl);
    modelState.audioUrl = "";
  }
  stopThinkingAnimation({ restoreMotion: false, clearRoulette: false });
  stopMouthSync();
}

async function requestExternalTts(plan, rate) {
  const response = await fetch(TTS_API_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      text: plan.text,
      rate,
      voice: modelState.selectedVoice,
      reference: modelState.selectedReference,
      promptText: modelState.referencePromptText,
    }),
  });
  if (!response.ok) {
    let message = `HTTP ${response.status}`;
    try {
      const payload = await response.json();
      message = payload.error || message;
    } catch {
      // 非 JSON 错误响应只保留 HTTP 状态。
    }
    throw new Error(message);
  }
  const audioBlob = await response.blob();
  if (!audioBlob.size) {
    throw new Error("TTS 服务返回了空音频。");
  }
  if (!audioBlob.type.startsWith("audio/")) {
    throw new Error(`TTS 服务返回了非音频内容：${audioBlob.type || "未知类型"}`);
  }
  return audioBlob;
}

async function playExternalAudio(audioBlob, plan, rate, requestId) {
  const audioUrl = URL.createObjectURL(audioBlob);
  const audio = new Audio(audioUrl);
  const playbackRate = applyAudioPlaybackRate(audio, rate);
  modelState.audio = audio;
  modelState.audioUrl = audioUrl;
  updateVoiceStatus();

  audio.onplay = () => {
    if (requestId !== modelState.speechRequestId) {
      return;
    }
    applyPlanVisualsForSpeech(plan).catch((error) => {
      addControlLog("语音同步动作失败", { error: error.message });
    });
    startMouthSync(plan, playbackRate);
    startReplyStream(plan.text, playbackRate);
    const backend = currentVoiceConfig()?.backend || "unknown";
    if (backend === "voxcpm_hf_space") {
      setStatus("正在播放 VoxCPM 公网 API 音频", "当前音频由公网 Space 生成；如果排队或限流，后续要迁移到本地推理服务。");
      return;
    }
    setStatus(`正在播放 ${backendLabel(backend)} 音频`, "音频来自当前选择的语音后端。");
  };
  audio.onpause = () => {
    if (requestId !== modelState.speechRequestId) {
      return;
    }
    if (!audio.ended) {
      modelState.speechPaused = true;
      modelState.speechBoundaryTarget = { open: 0, form: 0 };
    }
  };
  audio.onended = () => {
    if (requestId === modelState.speechRequestId) {
      stopMouthSync();
      finishReplyStream();
      setSpeechStatus(requestId, `${currentBackendLabel()} 音频播放完成`, "可以继续对话，或等待她做待机动作。");
      scheduleIdleAction();
    }
  };
  audio.onerror = () => {
    if (requestId !== modelState.speechRequestId) {
      return;
    }
    stopMouthSync();
    setReplyText(plan.text);
    setStatus(`${currentBackendLabel()} 音频播放失败`, "已收到音频数据，但浏览器解码或播放失败；请先点参考音频确认浏览器音频可用。");
  };

  try {
    stopThinkingAnimation({ restoreMotion: false, clearRoulette: false });
    await clearRouletteMotionArtifacts();
    await audio.play();
    return true;
  } catch (error) {
    URL.revokeObjectURL(audioUrl);
    modelState.audio = null;
    modelState.audioUrl = "";
    console.warn("TTS 音频播放失败。", error);
    return false;
  }
}

function applyAudioPlaybackRate(audio, rate) {
  const safeRate = clamp(rate || DEFAULT_SPEECH_RATE, 0.85, 1.35);
  audio.defaultPlaybackRate = safeRate;
  audio.playbackRate = safeRate;
  if ("preservesPitch" in audio) {
    audio.preservesPitch = true;
  }
  if ("mozPreservesPitch" in audio) {
    audio.mozPreservesPitch = true;
  }
  if ("webkitPreservesPitch" in audio) {
    audio.webkitPreservesPitch = true;
  }
  return safeRate;
}

async function loadVoiceModels() {
  try {
    const config = await loadJson(VOICES_API_URL);
    modelState.voiceModels = config.models || {};
    modelState.voiceReferences = config.references || {};
    modelState.selectedVoice = modelState.voiceModels[config.active] ? config.active : Object.keys(modelState.voiceModels)[0] || "";
    modelState.selectedReference = modelState.voiceReferences[config.active_reference]
      ? config.active_reference
      : Object.keys(modelState.voiceReferences)[0] || "";
    modelState.referencePromptText = currentReferenceConfig()?.prompt_text || "";
    renderVoiceList();
    renderReferenceSelector();
    updateVoiceStatus();
    synchronizeSelectedVoiceRuntime();
  } catch (error) {
    modelState.voiceModels = {};
    modelState.voiceReferences = {};
    modelState.selectedVoice = "";
    modelState.selectedReference = "";
    modelState.referencePromptText = "";
    voiceListEl.textContent = "语音服务未连接，暂时无法切换生成方式。";
    referenceSelectEl.replaceChildren();
    referenceTextInputEl.value = "";
    referenceAudioPreviewEl.removeAttribute("src");
    referenceHintEl.textContent = "语音服务未连接，无法读取参考音频。";
    voiceEl.textContent = "语音服务未连接";
    addControlLog("读取语音模型失败", { error: error.message });
  }
}

function renderVoiceList() {
  voiceListEl.replaceChildren();
  const entries = Object.entries(modelState.voiceModels);
  if (!entries.length) {
    voiceListEl.textContent = "没有可用语音模型。";
    return;
  }

  entries.forEach(([voiceId, config]) => {
    const button = document.createElement("button");
    button.type = "button";
    button.classList.toggle("is-active", voiceId === modelState.selectedVoice);
    button.addEventListener("click", () => selectVoice(voiceId));

    const title = document.createElement("strong");
    title.textContent = config.display_name || voiceId;

    const backend = document.createElement("span");
    backend.textContent = backendLabel(config.backend);

    const description = document.createElement("small");
    description.textContent = config.description || "未填写说明。";

    button.append(title, backend, description);
    voiceListEl.appendChild(button);
  });
}

function renderReferenceSelector() {
  referenceSelectEl.replaceChildren();
  const entries = Object.entries(modelState.voiceReferences);
  if (!entries.length) {
    referenceSelectEl.disabled = true;
    referenceTextInputEl.disabled = true;
    referenceAudioPreviewEl.removeAttribute("src");
    referenceHintEl.textContent = "没有可用参考音频。";
    return;
  }

  referenceSelectEl.disabled = false;
  referenceTextInputEl.disabled = false;
  entries.forEach(([referenceId, config]) => {
    const option = document.createElement("option");
    option.value = referenceId;
    option.textContent = config.display_name || referenceId;
    referenceSelectEl.appendChild(option);
  });
  referenceSelectEl.value = modelState.selectedReference;
  updateReferenceControls();
}

function updateReferenceControls() {
  const config = currentReferenceConfig();
  if (!config) {
    referenceTextInputEl.value = "";
    referenceAudioPreviewEl.removeAttribute("src");
    referenceHintEl.textContent = "没有选中参考音频。";
    return;
  }
  referenceSelectEl.value = modelState.selectedReference;
  referenceTextInputEl.value = modelState.referencePromptText;
  referenceAudioPreviewEl.src = `${REFERENCE_AUDIO_URL}?id=${encodeURIComponent(modelState.selectedReference)}`;
  referenceAudioPreviewEl.load();
  referenceHintEl.textContent = `${config.display_name || modelState.selectedReference}：参考文本必须尽量与音频内容一致，VoxCPM 会使用它约束音色。`;
}

function selectVoice(voiceId) {
  if (!modelState.voiceModels[voiceId]) {
    return;
  }
  modelState.selectedVoice = voiceId;
  renderVoiceList();
  updateVoiceStatus();
  addControlLog("切换语音模型", {
    voice: voiceId,
    backend: modelState.voiceModels[voiceId].backend,
  });
  synchronizeSelectedVoiceRuntime();
}

function selectReference(referenceId) {
  if (!modelState.voiceReferences[referenceId]) {
    return;
  }
  modelState.selectedReference = referenceId;
  modelState.referencePromptText = currentReferenceConfig()?.prompt_text || "";
  updateReferenceControls();
  updateVoiceStatus();
  addControlLog("切换参考音频", {
    reference: referenceId,
    promptText: modelState.referencePromptText,
  });
}

function currentVoiceConfig() {
  return modelState.voiceModels[modelState.selectedVoice] || null;
}

function currentReferenceConfig() {
  return modelState.voiceReferences[modelState.selectedReference] || null;
}

function readStoredValue(key) {
  try {
    return window.localStorage.getItem(key) || "";
  } catch (error) {
    return "";
  }
}

function writeStoredValue(key, value) {
  try {
    if (value) {
      window.localStorage.setItem(key, value);
      return;
    }
    window.localStorage.removeItem(key);
  } catch (error) {
    addControlLog("本地配置保存失败", { key, error: error.message });
  }
}

function cameraApiAvailable() {
  return Boolean(navigator.mediaDevices?.getUserMedia && navigator.mediaDevices?.enumerateDevices);
}

function cameraDeviceLabel(device, index) {
  return device.label || `摄像头 ${index + 1}`;
}

function setCameraStatus(message, hint = "") {
  const fullText = hint ? `${message} ${hint}` : message;
  cameraStatusEl.textContent = fullText;
  cameraWindowStatusEl.textContent = fullText;
}

function renderCameraControls() {
  cameraSelectEl.replaceChildren();
  const available = cameraApiAvailable();
  cameraSelectEl.disabled = !available || !modelState.cameraDevices.length;
  cameraDetectButton.disabled = !available;
  cameraStartButton.disabled = !available;
  cameraDefaultButton.disabled = !available || !modelState.selectedCameraId;
  cameraStopButton.disabled = !modelState.cameraStream;

  if (!available) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "当前浏览器不支持摄像头 API";
    cameraSelectEl.appendChild(option);
    setCameraStatus("浏览器不支持摄像头 API。", "请使用 Chrome/Edge 并通过 localhost 打开页面。");
    return;
  }

  if (!modelState.cameraDevices.length) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "尚未检测到摄像头";
    cameraSelectEl.appendChild(option);
    return;
  }

  modelState.cameraDevices.forEach((device, index) => {
    const option = document.createElement("option");
    option.value = device.deviceId;
    option.textContent = cameraDeviceLabel(device, index);
    if (device.deviceId && device.deviceId === modelState.defaultCameraId) {
      option.textContent += "（默认）";
    }
    cameraSelectEl.appendChild(option);
  });
  cameraSelectEl.value = modelState.selectedCameraId;
}

async function refreshCameraDevices(options = {}) {
  if (!cameraApiAvailable()) {
    renderCameraControls();
    return [];
  }

  let permissionStream = null;
  try {
    if (options.requestPermission) {
      permissionStream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
    }
    const devices = await navigator.mediaDevices.enumerateDevices();
    modelState.cameraDevices = devices.filter((device) => device.kind === "videoinput");
    const deviceIds = new Set(modelState.cameraDevices.map((device) => device.deviceId));
    if (modelState.defaultCameraId && deviceIds.has(modelState.defaultCameraId)) {
      modelState.selectedCameraId = modelState.defaultCameraId;
    } else if (!deviceIds.has(modelState.selectedCameraId)) {
      modelState.selectedCameraId = modelState.cameraDevices[0]?.deviceId || "";
    }
    renderCameraControls();
    if (modelState.cameraDevices.length) {
      setCameraStatus("摄像头设备已刷新。", "如设备名仍为空，请点击检测设备完成浏览器授权。");
    } else {
      setCameraStatus("未检测到可用摄像头。", "请确认 Windows 摄像头权限和设备连接状态。");
    }
    return modelState.cameraDevices;
  } catch (error) {
    setCameraStatus("摄像头检测失败。", error.message);
    addControlLog("摄像头检测失败", { error: error.message });
    return [];
  } finally {
    if (permissionStream) {
      permissionStream.getTracks().forEach((track) => track.stop());
    }
  }
}

function selectedCameraLabel() {
  const index = modelState.cameraDevices.findIndex((device) => device.deviceId === modelState.selectedCameraId);
  if (index < 0) {
    return "默认摄像头";
  }
  return cameraDeviceLabel(modelState.cameraDevices[index], index);
}

function buildCameraConstraints() {
  if (modelState.selectedCameraId) {
    return {
      video: { deviceId: { exact: modelState.selectedCameraId } },
      audio: false,
    };
  }
  return { video: true, audio: false };
}

async function startCameraPreview() {
  if (!cameraApiAvailable()) {
    renderCameraControls();
    return;
  }

  if (!modelState.cameraDevices.length) {
    await refreshCameraDevices({ requestPermission: true });
  }

  stopCameraPreview({ hideWindow: false, quiet: true });
  try {
    const stream = await navigator.mediaDevices.getUserMedia(buildCameraConstraints());
    modelState.cameraStream = stream;
    cameraPreviewEl.srcObject = stream;
    cameraWindowEl.hidden = false;
    restoreCameraWindowSize();
    restoreCameraWindowPosition();
    updateCameraWindowAspectRatio();
    const track = stream.getVideoTracks()[0];
    const deviceId = track?.getSettings?.().deviceId || modelState.selectedCameraId;
    if (deviceId) {
      modelState.selectedCameraId = deviceId;
    }
    await refreshCameraDevices({ requestPermission: false });
    setCameraStatus("摄像头预览已打开。", selectedCameraLabel());
    setStatus("摄像头预览已打开", "视觉模块将优先使用当前选择的摄像头。");
    addControlLog("打开摄像头预览", {
      deviceId: modelState.selectedCameraId,
      label: selectedCameraLabel(),
    });
  } catch (error) {
    stopCameraPreview({ hideWindow: true, quiet: true });
    setCameraStatus("摄像头预览打开失败。", error.message);
    setStatus("摄像头预览打开失败", error.message);
    addControlLog("打开摄像头失败", { error: error.message });
  } finally {
    renderCameraControls();
  }
}

function stopCameraPreview(options = {}) {
  if (modelState.cameraStream) {
    modelState.cameraStream.getTracks().forEach((track) => track.stop());
    modelState.cameraStream = null;
  }
  cameraPreviewEl.srcObject = null;
  if (options.hideWindow !== false) {
    cameraWindowEl.hidden = true;
  }
  if (!options.quiet) {
    setCameraStatus("摄像头预览已关闭。");
    setStatus("摄像头预览已关闭", "视觉模块暂时不会读取摄像头画面。");
    addControlLog("关闭摄像头预览", {});
  }
  renderCameraControls();
}

function saveDefaultCamera() {
  if (!modelState.selectedCameraId) {
    setCameraStatus("无法设置默认摄像头。", "请先检测并选择一个摄像头。");
    return;
  }
  modelState.defaultCameraId = modelState.selectedCameraId;
  writeStoredValue(CAMERA_DEFAULT_STORAGE_KEY, modelState.defaultCameraId);
  renderCameraControls();
  setCameraStatus("默认摄像头已保存。", selectedCameraLabel());
  addControlLog("设置默认摄像头", {
    deviceId: modelState.defaultCameraId,
    label: selectedCameraLabel(),
  });
}

function clampCameraWindowPosition(left, top) {
  const margin = 12;
  const maxLeft = Math.max(margin, window.innerWidth - cameraWindowEl.offsetWidth - margin);
  const maxTop = Math.max(margin, window.innerHeight - cameraWindowEl.offsetHeight - margin);
  return {
    left: clamp(left, margin, maxLeft),
    top: clamp(top, margin, maxTop),
  };
}

function setCameraWindowPosition(left, top) {
  const position = clampCameraWindowPosition(left, top);
  cameraWindowEl.style.left = `${position.left}px`;
  cameraWindowEl.style.top = `${position.top}px`;
  cameraWindowEl.style.right = "auto";
  cameraWindowEl.style.bottom = "auto";
  writeStoredValue(CAMERA_WINDOW_POSITION_STORAGE_KEY, JSON.stringify(position));
}

function clampCameraWindowWidth(width) {
  const margin = 12;
  const viewportMaxWidth = Math.max(CAMERA_WINDOW_MIN_WIDTH, window.innerWidth - margin * 2);
  return clamp(width, CAMERA_WINDOW_MIN_WIDTH, Math.min(CAMERA_WINDOW_MAX_WIDTH, viewportMaxWidth));
}

function setCameraWindowWidth(width) {
  const safeWidth = clampCameraWindowWidth(width);
  cameraWindowEl.style.width = `${safeWidth}px`;
  writeStoredValue(CAMERA_WINDOW_WIDTH_STORAGE_KEY, String(Math.round(safeWidth)));
  const rect = cameraWindowEl.getBoundingClientRect();
  if (rect.width && rect.height) {
    setCameraWindowPosition(rect.left, rect.top);
  }
}

function restoreCameraWindowSize() {
  const rawWidth = Number(readStoredValue(CAMERA_WINDOW_WIDTH_STORAGE_KEY));
  if (Number.isFinite(rawWidth) && rawWidth > 0) {
    setCameraWindowWidth(rawWidth);
  }
}

function restoreCameraWindowPosition() {
  const rawPosition = readStoredValue(CAMERA_WINDOW_POSITION_STORAGE_KEY);
  if (!rawPosition) {
    return;
  }
  try {
    const position = JSON.parse(rawPosition);
    if (Number.isFinite(position.left) && Number.isFinite(position.top)) {
      setCameraWindowPosition(position.left, position.top);
    }
  } catch (error) {
    writeStoredValue(CAMERA_WINDOW_POSITION_STORAGE_KEY, "");
  }
}

function updateCameraWindowAspectRatio() {
  const width = cameraPreviewEl.videoWidth;
  const height = cameraPreviewEl.videoHeight;
  if (width > 0 && height > 0) {
    cameraWindowEl.style.setProperty("--camera-aspect-ratio", String(width / height));
  }
}

function setupCameraWindowDrag() {
  cameraWindowEl.addEventListener("pointerdown", (event) => {
    if (event.target === cameraResizeHandleEl) {
      return;
    }
    const rect = cameraWindowEl.getBoundingClientRect();
    modelState.cameraDrag = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      left: rect.left,
      top: rect.top,
    };
    cameraWindowEl.setPointerCapture(event.pointerId);
  });
  cameraWindowEl.addEventListener("pointermove", (event) => {
    const drag = modelState.cameraDrag;
    if (!drag || drag.pointerId !== event.pointerId) {
      return;
    }
    setCameraWindowPosition(
      drag.left + event.clientX - drag.startX,
      drag.top + event.clientY - drag.startY,
    );
  });
  cameraWindowEl.addEventListener("pointerup", (event) => {
    if (modelState.cameraDrag?.pointerId === event.pointerId) {
      modelState.cameraDrag = null;
      cameraWindowEl.releasePointerCapture(event.pointerId);
    }
  });
  cameraWindowEl.addEventListener("pointercancel", (event) => {
    if (modelState.cameraDrag?.pointerId === event.pointerId) {
      modelState.cameraDrag = null;
    }
  });
  cameraResizeHandleEl.addEventListener("pointerdown", (event) => {
    event.stopPropagation();
    const rect = cameraWindowEl.getBoundingClientRect();
    modelState.cameraResize = {
      pointerId: event.pointerId,
      startX: event.clientX,
      width: rect.width,
    };
    cameraResizeHandleEl.setPointerCapture(event.pointerId);
  });
  cameraResizeHandleEl.addEventListener("pointermove", (event) => {
    const resize = modelState.cameraResize;
    if (!resize || resize.pointerId !== event.pointerId) {
      return;
    }
    setCameraWindowWidth(resize.width + event.clientX - resize.startX);
  });
  cameraResizeHandleEl.addEventListener("pointerup", (event) => {
    if (modelState.cameraResize?.pointerId === event.pointerId) {
      modelState.cameraResize = null;
      cameraResizeHandleEl.releasePointerCapture(event.pointerId);
    }
  });
  cameraResizeHandleEl.addEventListener("pointercancel", (event) => {
    if (modelState.cameraResize?.pointerId === event.pointerId) {
      modelState.cameraResize = null;
    }
  });
  cameraPreviewEl.addEventListener("loadedmetadata", updateCameraWindowAspectRatio);
}

function initializeCameraControls() {
  modelState.defaultCameraId = readStoredValue(CAMERA_DEFAULT_STORAGE_KEY);
  modelState.selectedCameraId = modelState.defaultCameraId;
  renderCameraControls();
  restoreCameraWindowSize();
  restoreCameraWindowPosition();
  refreshCameraDevices({ requestPermission: false });
}

function audioApiAvailable() {
  return Boolean(navigator.mediaDevices?.getUserMedia && navigator.mediaDevices?.enumerateDevices && audioContextCtor());
}

function audioContextCtor() {
  return window.AudioContext || window.webkitAudioContext || null;
}

function audioDeviceLabel(device, index) {
  return device.label || `麦克风 ${index + 1}`;
}

function setAudioStatus(message, hint = "") {
  const fullText = hint ? `${message} ${hint}` : message;
  audioStatusEl.textContent = fullText;
  audioWindowStatusEl.textContent = fullText;
}

function renderAudioControls() {
  audioSelectEl.replaceChildren();
  const available = audioApiAvailable();
  audioSelectEl.disabled = !available || !modelState.audioDevices.length;
  audioDetectButton.disabled = !available;
  audioStartButton.disabled = !available;
  audioDefaultButton.disabled = !available || !modelState.selectedAudioId;
  audioStopButton.disabled = !modelState.audioStream;

  if (!available) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "当前浏览器不支持麦克风 API";
    audioSelectEl.appendChild(option);
    setAudioStatus("听觉模块不可用。", "请使用支持 getUserMedia 与 Web Audio 的浏览器。");
    return;
  }

  if (!modelState.audioDevices.length) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "尚未检测到麦克风";
    audioSelectEl.appendChild(option);
    return;
  }

  modelState.audioDevices.forEach((device, index) => {
    const option = document.createElement("option");
    option.value = device.deviceId;
    option.textContent = audioDeviceLabel(device, index);
    if (device.deviceId && device.deviceId === modelState.defaultAudioId) {
      option.textContent += "（默认）";
    }
    audioSelectEl.appendChild(option);
  });
  audioSelectEl.value = modelState.selectedAudioId;
}

async function refreshAudioDevices(options = {}) {
  if (!audioApiAvailable()) {
    renderAudioControls();
    return [];
  }

  let permissionStream = null;
  try {
    if (options.requestPermission) {
      permissionStream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
    }
    const devices = await navigator.mediaDevices.enumerateDevices();
    modelState.audioDevices = devices.filter((device) => device.kind === "audioinput");
    const knownSelected = modelState.audioDevices.some((device) => device.deviceId === modelState.selectedAudioId);
    const knownDefault = modelState.audioDevices.some((device) => device.deviceId === modelState.defaultAudioId);
    if (!knownDefault) {
      modelState.defaultAudioId = "";
    }
    if (!knownSelected) {
      modelState.selectedAudioId = modelState.defaultAudioId || modelState.audioDevices[0]?.deviceId || "";
    }
    renderAudioControls();
    if (modelState.audioDevices.length) {
      setAudioStatus("麦克风设备已更新。", selectedAudioLabel());
    } else {
      setAudioStatus("未检测到可用麦克风。", "请确认 Windows 麦克风权限和设备连接状态。");
    }
    return modelState.audioDevices;
  } catch (error) {
    setAudioStatus("麦克风检测失败。", error.message);
    addControlLog("麦克风检测失败", { error: error.message });
    return [];
  } finally {
    if (permissionStream) {
      permissionStream.getTracks().forEach((track) => track.stop());
    }
  }
}

function selectedAudioLabel() {
  const index = modelState.audioDevices.findIndex((device) => device.deviceId === modelState.selectedAudioId);
  if (index < 0) {
    return "默认麦克风";
  }
  return audioDeviceLabel(modelState.audioDevices[index], index);
}

function buildAudioConstraints() {
  if (modelState.selectedAudioId) {
    return {
      audio: {
        deviceId: { exact: modelState.selectedAudioId },
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
      video: false,
    };
  }
  return { audio: true, video: false };
}

async function startAudioMonitor() {
  if (!audioApiAvailable()) {
    renderAudioControls();
    return;
  }

  if (!modelState.audioDevices.length) {
    await refreshAudioDevices({ requestPermission: true });
  }

  stopAudioMonitor({ hideWindow: false, quiet: true });
  try {
    const stream = await navigator.mediaDevices.getUserMedia(buildAudioConstraints());
    const AudioContextCtor = audioContextCtor();
    modelState.audioStream = stream;
    modelState.audioContext = new AudioContextCtor();
    modelState.audioSource = modelState.audioContext.createMediaStreamSource(stream);
    modelState.audioAnalyser = modelState.audioContext.createAnalyser();
    modelState.audioAnalyser.fftSize = AUDIO_ANALYSER_FFT_SIZE;
    modelState.audioLevelData = new Uint8Array(modelState.audioAnalyser.fftSize);
    modelState.audioSource.connect(modelState.audioAnalyser);
    audioWindowEl.hidden = false;
    restoreAudioWindowPosition();
    updateAudioLevelLoop();

    const track = stream.getAudioTracks()[0];
    const deviceId = track?.getSettings?.().deviceId || modelState.selectedAudioId;
    if (deviceId) {
      modelState.selectedAudioId = deviceId;
    }
    await refreshAudioDevices({ requestPermission: false });
    setAudioStatus("麦克风监听已打开。", selectedAudioLabel());
    setStatus("麦克风监听已打开", "听觉模块将优先使用当前选择的麦克风。");
    addControlLog("打开麦克风监听", {
      deviceId: modelState.selectedAudioId,
      label: selectedAudioLabel(),
    });
  } catch (error) {
    stopAudioMonitor({ hideWindow: true, quiet: true });
    setAudioStatus("麦克风监听打开失败。", error.message);
    setStatus("麦克风监听打开失败", error.message);
    addControlLog("打开麦克风失败", { error: error.message });
  } finally {
    renderAudioControls();
  }
}

function updateAudioLevelLoop() {
  const analyser = modelState.audioAnalyser;
  const data = modelState.audioLevelData;
  if (!analyser || !data) {
    return;
  }

  analyser.getByteTimeDomainData(data);
  let sum = 0;
  for (const value of data) {
    const normalized = (value - 128) / 128;
    sum += normalized * normalized;
  }
  const level = clamp(Math.sqrt(sum / data.length) * 3.2, 0, 1);
  audioWindowEl.style.setProperty("--audio-level", level.toFixed(3));
  audioWindowStatusEl.textContent = `当前麦克风音量 ${Math.round(level * 100)}%。`;
  modelState.audioLevelFrame = window.requestAnimationFrame(updateAudioLevelLoop);
}

function stopAudioMonitor(options = {}) {
  if (modelState.audioLevelFrame) {
    window.cancelAnimationFrame(modelState.audioLevelFrame);
    modelState.audioLevelFrame = 0;
  }
  if (modelState.audioSource) {
    modelState.audioSource.disconnect();
    modelState.audioSource = null;
  }
  if (modelState.audioContext) {
    modelState.audioContext.close();
    modelState.audioContext = null;
  }
  modelState.audioAnalyser = null;
  modelState.audioLevelData = null;
  if (modelState.audioStream) {
    modelState.audioStream.getTracks().forEach((track) => track.stop());
    modelState.audioStream = null;
  }
  audioWindowEl.style.setProperty("--audio-level", "0");
  if (options.hideWindow !== false) {
    audioWindowEl.hidden = true;
  }
  if (!options.quiet) {
    setAudioStatus("麦克风监听已关闭。");
    setStatus("麦克风监听已关闭", "听觉模块暂时不会读取麦克风输入。");
    addControlLog("关闭麦克风监听", {});
  }
  renderAudioControls();
}

function saveDefaultAudio() {
  if (!modelState.selectedAudioId) {
    setAudioStatus("无法设置默认麦克风。", "请先检测并选择一个麦克风。");
    return;
  }
  modelState.defaultAudioId = modelState.selectedAudioId;
  writeStoredValue(AUDIO_DEFAULT_STORAGE_KEY, modelState.defaultAudioId);
  renderAudioControls();
  setAudioStatus("默认麦克风已保存。", selectedAudioLabel());
  addControlLog("设置默认麦克风", {
    deviceId: modelState.defaultAudioId,
    label: selectedAudioLabel(),
  });
}

function clampAudioWindowPosition(left, top) {
  const margin = 12;
  const maxLeft = Math.max(margin, window.innerWidth - audioWindowEl.offsetWidth - margin);
  const maxTop = Math.max(margin, window.innerHeight - audioWindowEl.offsetHeight - margin);
  return {
    left: clamp(left, margin, maxLeft),
    top: clamp(top, margin, maxTop),
  };
}

function setAudioWindowPosition(left, top) {
  const position = clampAudioWindowPosition(left, top);
  audioWindowEl.style.left = `${position.left}px`;
  audioWindowEl.style.top = `${position.top}px`;
  audioWindowEl.style.right = "auto";
  audioWindowEl.style.bottom = "auto";
  writeStoredValue(AUDIO_WINDOW_POSITION_STORAGE_KEY, JSON.stringify(position));
}

function restoreAudioWindowPosition() {
  const rawPosition = readStoredValue(AUDIO_WINDOW_POSITION_STORAGE_KEY);
  if (!rawPosition) {
    return;
  }
  try {
    const position = JSON.parse(rawPosition);
    if (Number.isFinite(position.left) && Number.isFinite(position.top)) {
      setAudioWindowPosition(position.left, position.top);
    }
  } catch (error) {
    writeStoredValue(AUDIO_WINDOW_POSITION_STORAGE_KEY, "");
  }
}

function setupAudioWindowDrag() {
  audioWindowEl.addEventListener("pointerdown", (event) => {
    const rect = audioWindowEl.getBoundingClientRect();
    modelState.audioDrag = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      left: rect.left,
      top: rect.top,
    };
    audioWindowEl.setPointerCapture(event.pointerId);
  });
  audioWindowEl.addEventListener("pointermove", (event) => {
    const drag = modelState.audioDrag;
    if (!drag || drag.pointerId !== event.pointerId) {
      return;
    }
    setAudioWindowPosition(
      drag.left + event.clientX - drag.startX,
      drag.top + event.clientY - drag.startY,
    );
  });
  audioWindowEl.addEventListener("pointerup", (event) => {
    if (modelState.audioDrag?.pointerId === event.pointerId) {
      modelState.audioDrag = null;
      audioWindowEl.releasePointerCapture(event.pointerId);
    }
  });
  audioWindowEl.addEventListener("pointercancel", (event) => {
    if (modelState.audioDrag?.pointerId === event.pointerId) {
      modelState.audioDrag = null;
    }
  });
}

function initializeAudioControls() {
  modelState.defaultAudioId = readStoredValue(AUDIO_DEFAULT_STORAGE_KEY);
  modelState.selectedAudioId = modelState.defaultAudioId;
  renderAudioControls();
  restoreAudioWindowPosition();
  refreshAudioDevices({ requestPermission: false });
}

function updateVoiceStatus() {
  const config = currentVoiceConfig();
  if (!config) {
    voiceEl.textContent = modelState.selectedVoice || "等待 TTS 服务";
    return;
  }
  const referenceName = currentReferenceConfig()?.display_name || modelState.selectedReference || "未选参考音频";
  voiceEl.textContent = `${backendLabel(config.backend)} / ${referenceName}`;
}

async function checkSelectedVoiceHealth() {
  const config = currentVoiceConfig();
  if (!config || !["voxcpm_project_local", "voxcpm_local", "voxcpm_local_gradio"].includes(config.backend)) {
    return;
  }
  try {
    const response = await fetch(`${TTS_HEALTH_API_URL}?voice=${encodeURIComponent(modelState.selectedVoice)}`, {
      cache: "no-store",
    });
    const payload = await response.json();
    if (payload.ok) {
      setStatus(`${backendLabel(config.backend)} 已就绪`, payload.model_path || payload.base_url || payload.message || "");
      return;
    }
    setStatus(`${backendLabel(config.backend)} 未就绪`, payload.message || payload.error || "请检查本地模型路径和依赖。");
  } catch (error) {
    setStatus("语音健康检查失败", error.message);
  }
}

async function synchronizeSelectedVoiceRuntime() {
  const config = currentVoiceConfig();
  if (!config) {
    return;
  }
  const requestId = modelState.voiceRuntimeRequestId + 1;
  modelState.voiceRuntimeRequestId = requestId;
  const backend = config.backend;
  const isProjectLocal = backend === "voxcpm_project_local";
  setStatus(
    isProjectLocal ? "正在启动 VoxCPM 本地推理" : "正在切换到云端语音",
    isProjectLocal ? "首次加载模型可能需要较长时间，请等待本地推理进程准备完成。" : "正在通知后端释放本地 VoxCPM 模型缓存。",
  );

  try {
    const response = await fetch(TTS_RUNTIME_API_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ voice: modelState.selectedVoice }),
    });
    const payload = await response.json();
    if (requestId !== modelState.voiceRuntimeRequestId) {
      return;
    }

    addControlLog("语音运行时切换", payload);
    if (!payload.ok) {
      setStatus("语音运行时切换失败", payload.message || payload.error || "请检查控制服务日志。");
      return;
    }
    if (isProjectLocal) {
      setStatus("VoxCPM 本地推理已启动", payload.model_path || payload.message || "模型已加载到控制服务进程。");
      return;
    }
    setStatus("已切换到云端语音", payload.message || "本地 VoxCPM 模型缓存已释放。");
  } catch (error) {
    if (requestId === modelState.voiceRuntimeRequestId) {
      setStatus("语音运行时切换失败", error.message);
    }
  }
}

function backendLabel(backend) {
  const labels = {
    voxcpm_hf_space: "VoxCPM 公网 API",
    voxcpm_project_local: "VoxCPM 项目内本地推理",
    voxcpm_local: "VoxCPM 本地 Gradio 桥接",
    voxcpm_local_gradio: "VoxCPM 本地 Gradio 桥接",
  };
  return labels[backend] || String(backend || "未知后端");
}

function currentBackendLabel() {
  return backendLabel(currentVoiceConfig()?.backend);
}

function setSpeechStatus(requestId, message, hint = "") {
  if (requestId === modelState.speechRequestId) {
    setStatus(message, hint);
  }
}

function setTtsErrorStatus(error, requestId) {
  if (requestId !== modelState.speechRequestId) {
    return;
  }
  const message = error.message || "请检查 TTS 配置或启动语音服务。";
  const backend = currentVoiceConfig()?.backend || "";
  if (backend === "voxcpm_hf_space") {
    setStatus("VoxCPM 公网 API 生成失败", message);
    return;
  }
  if (backend === "voxcpm_project_local") {
    setStatus("VoxCPM 项目内本地推理不可用", message);
    return;
  }
  if (["voxcpm_local", "voxcpm_local_gradio"].includes(backend)) {
    setStatus("VoxCPM 本地 Gradio 桥接未连接", "请先启动本地 VoxCPM Gradio 服务，或切换到项目内本地推理/公网 API。");
    return;
  }
  setStatus("VoxCPM 语音服务不可用", message);
}

function startMouthSync(plan, rate) {
  modelState.speaking = true;
  modelState.speechPaused = false;
  modelState.speakingStartedAt = performance.now();
  modelState.speechBoundaryTarget = null;
  modelState.mouthTimeline = buildMouthTimeline(plan.text, rate);
}

function stopMouthSync() {
  modelState.speaking = false;
  modelState.speechPaused = false;
  modelState.mouthBase = 0;
  modelState.mouthTarget = 0;
  modelState.speechBoundaryTarget = null;
}

function currentSpeechRate(plan = modelState.currentPlan) {
  const fromControl = Number(speechRateInput?.value || plan?.speech?.rate || DEFAULT_SPEECH_RATE);
  return clamp(fromControl, 0.85, 1.35);
}

function syncSpeechRateControl(rate) {
  const safeRate = clamp(rate || DEFAULT_SPEECH_RATE, 0.85, 1.35);
  speechRateInput.value = String(safeRate.toFixed(2));
  speechRateValue.textContent = `${safeRate.toFixed(2)}x`;
  return safeRate;
}

function syncActiveSpeechRate(rate) {
  if (!modelState.audio) {
    return;
  }
  const safeRate = applyAudioPlaybackRate(modelState.audio, rate);
  if (modelState.speaking) {
    modelState.mouthTimeline = buildMouthTimeline(modelState.currentPlan.text, safeRate);
    modelState.speakingStartedAt = performance.now() - (modelState.audio.currentTime * 1000) / safeRate;
  }
}

function buildMouthTimeline(text, rate) {
  const timeline = [];
  let cursorMs = 0;
  const chars = Array.from(String(text || ""));
  const baseDurationMs = clamp(188 / Math.max(rate, 0.1), 118, 230);

  chars.forEach((char) => {
    if (isWhitespace(char)) {
      cursorMs += baseDurationMs * 0.45;
      return;
    }

    if (isPunctuation(char)) {
      const pauseMs = punctuationPauseMs(char, baseDurationMs);
      timeline.push({
        startMs: cursorMs,
        endMs: cursorMs + pauseMs,
        silence: true,
        open: 0,
        form: 0,
      });
      cursorMs += pauseMs;
      return;
    }

    const shape = mouthShapeForCharacter(char);
    timeline.push({
      startMs: cursorMs,
      endMs: cursorMs + baseDurationMs,
      silence: false,
      open: shape.open,
      form: shape.form,
    });
    cursorMs += baseDurationMs;
  });

  return timeline;
}

function mouthShapeForCharacter(char) {
  const lower = String(char || "").toLowerCase();
  if (!lower || isPunctuation(lower) || isWhitespace(lower)) {
    return { open: 0, form: 0 };
  }

  if ("aɑ".includes(lower)) {
    return { open: 0.92, form: 0.25 };
  }
  if ("oouü".includes(lower)) {
    return { open: 0.64, form: -0.55 };
  }
  if ("ei".includes(lower)) {
    return { open: 0.45, form: 0.48 };
  }
  if ("bpmfvw".includes(lower)) {
    return { open: 0.18, form: 0.05 };
  }

  const commonChineseShapes = {
    啊: { open: 0.94, form: 0.2 },
    呀: { open: 0.9, form: 0.22 },
    哈: { open: 0.9, form: 0.18 },
    好: { open: 0.76, form: -0.2 },
    我: { open: 0.64, form: -0.5 },
    兔: { open: 0.48, form: -0.62 },
    草: { open: 0.78, form: 0.08 },
    莓: { open: 0.42, form: 0.45 },
    你: { open: 0.38, form: 0.52 },
    是: { open: 0.34, form: 0.42 },
    的: { open: 0.34, form: 0.38 },
    了: { open: 0.5, form: 0.22 },
    吗: { open: 0.84, form: 0.18 },
    呢: { open: 0.42, form: 0.45 },
  };
  if (commonChineseShapes[char]) {
    return commonChineseShapes[char];
  }

  const codePoint = char.codePointAt(0) || 0;
  const profiles = [
    { open: 0.72, form: 0.18 },
    { open: 0.54, form: -0.38 },
    { open: 0.42, form: 0.44 },
    { open: 0.62, form: 0.02 },
  ];
  return profiles[codePoint % profiles.length];
}

function isWhitespace(char) {
  return /\s/.test(char);
}

function isPunctuation(char) {
  return /[，。！？、；：,.!?;:~…]/.test(char);
}

function punctuationPauseMs(char, baseDurationMs) {
  if (/[。！？.!?]/.test(char)) {
    return baseDurationMs * 2.4;
  }
  if (/[，、,]/.test(char)) {
    return baseDurationMs * 1.25;
  }
  return baseDurationMs * 1.7;
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, Number(value)));
}

async function loadLatestControl() {
  const plan = await loadJson(CONTROL_URL);
  await applyPlan(plan, { speak: true });
  setStatus("已加载 LLM 控制文件", "控制文件来自 public/control/latest_control.json。");
}

async function loadInitialControl() {
  try {
    const plan = await loadJson(CONTROL_URL);
    await applyPlan(plan, { speak: false });
    setStatus("已加载 LLM 控制文件", "输入新问题后会通过本地控制服务请求 LLM。");
  } catch (error) {
    await applyPlan(demoPlan, { speak: false });
    setStatus("已加载内置演示", "没有找到可用的 LLM 控制文件；输入新问题会走本地 LLM 服务。");
  }
}

function randomMotion() {
  if (!VISIBLE_ACTIONS.length) {
    return;
  }
  const action = VISIBLE_ACTIONS[Math.floor(Math.random() * VISIBLE_ACTIONS.length)];
  triggerVisibleAction(action);
}

function markUserActivity() {
  if (modelState.idleTimer) {
    window.clearTimeout(modelState.idleTimer);
    modelState.idleTimer = 0;
  }
}

function scheduleIdleAction() {
  if (modelState.idleTimer) {
    window.clearTimeout(modelState.idleTimer);
  }
  const delayMs = randomRange(IDLE_DELAY_RANGE_MS.min, IDLE_DELAY_RANGE_MS.max);
  modelState.idleTimer = window.setTimeout(() => {
    modelState.idleTimer = 0;
    runIdleAction();
  }, delayMs);
}

function runIdleAction() {
  if (isStageBusy() || chatInput.value.trim()) {
    scheduleIdleAction();
    return;
  }
  const action = actionByName(randomItem(IDLE_ACTION_NAMES));
  if (action) {
    applyActionControl({ name: action.name, mode: "pulse", durationMs: action.durationMs, delayMs: 0 })
      .then(() => addControlLog("待机动作", { name: action.name, label: action.label }))
      .catch((error) => addControlLog("待机动作失败", { name: action.name, error: error.message }));
  }
  scheduleIdleAction();
}

function isStageBusy() {
  return modelState.speaking || modelState.generatingSpeech || document.activeElement === chatInput;
}

function randomItem(items) {
  return items[Math.floor(Math.random() * items.length)];
}

function randomRange(min, max) {
  return Math.floor(min + Math.random() * (max - min));
}

function populateActionDisk() {
  actionListEl.replaceChildren();
  actionButtons.clear();
  VISIBLE_ACTIONS.forEach((action) => {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = action.label;
    if (action.hotkey) {
      button.title = action.hotkey;
    }
    button.addEventListener("click", () => triggerVisibleAction(action));
    actionButtons.set(action.name, button);
    actionListEl.appendChild(button);
  });
}

async function triggerVisibleAction(action) {
  markUserActivity();
  scheduleIdleAction();
  if (isVisibleActionActive(action)) {
    cancelVisibleAction(action);
    addControlLog("手动取消动作", {
      label: action.label,
      name: action.name,
      group: action.group,
      fadeMs: ACTION_FADE_MS,
    });
    updateActionButtonStates();
    return;
  }

  addControlLog("手动动作", {
    label: action.label,
    mode: action.defaultMode,
    group: action.group,
    expression: action.expression || "无",
    motion: action.motion || "无",
    parameters: action.parameters || {},
    fadeMs: ACTION_FADE_MS,
  });
  holdVisibleAction(action, { mode: action.defaultMode });
  if (action.expression) {
    await applyExpressionAsset(action.expression);
    expressionEl.textContent = action.expression;
  }
  if (action.motion) {
    await applyMotion(action.motion);
  }
  motionEl.textContent = action.label || action.motion || action.expression || "无";
  updateActionButtonStates();
}

async function applyActionControls(actions) {
  for (const control of actions) {
    if (control.delayMs > 0) {
      scheduleActionControl(control);
      continue;
    }
    await applyActionControl(control);
  }
}

function scheduleActionControl(control) {
  addControlLog("计划动作排队", {
    name: control.name,
    mode: control.mode,
    durationMs: control.durationMs,
    delayMs: control.delayMs,
  });
  const timerId = window.setTimeout(() => {
    modelState.scheduledActionTimers = modelState.scheduledActionTimers.filter((id) => id !== timerId);
    applyActionControl(control).catch((error) => {
      addControlLog("计划动作失败", { name: control.name, error: error.message });
    });
  }, control.delayMs);
  modelState.scheduledActionTimers.push(timerId);
}

function clearScheduledActions() {
  modelState.scheduledActionTimers.forEach((timerId) => window.clearTimeout(timerId));
  modelState.scheduledActionTimers = [];
}

async function applyActionControl(control) {
  const action = actionByName(control.name);
  if (!action) {
    return;
  }

  if (control.mode === "off") {
    closeActionGroup(action.group);
    addControlLog("关闭动作组", { name: action.name, group: action.group, fadeMs: ACTION_FADE_MS });
    return;
  }

  holdVisibleAction(action, { mode: control.mode, durationMs: control.durationMs });
  if (action.expression) {
    await applyExpressionAsset(action.expression);
    expressionEl.textContent = action.expression;
  }
  if (action.motion) {
    await applyMotion(action.motion);
  }
  motionEl.textContent = action.label || action.motion || action.expression || "无";
}

function closeActionGroup(group) {
  const now = performance.now();
  modelState.activeActions.forEach((activeAction) => {
    if (activeAction.group === group) {
      activeAction.endsAt = Math.min(activeAction.endsAt ?? Infinity, now + ACTION_FADE_MS);
    }
  });
}

function actionByName(name) {
  return ACTIONS_BY_NAME[String(name || "")] || null;
}

function cancelVisibleAction(action) {
  const now = performance.now();
  modelState.activeActions.forEach((activeAction) => {
    if (activeAction.name === action.name) {
      activeAction.endsAt = Math.min(activeAction.endsAt ?? Infinity, now + ACTION_FADE_MS);
    }
  });
}

function isVisibleActionActive(action, now = performance.now()) {
  return modelState.activeActions.some((activeAction) => activeAction.name === action.name && (activeAction.endsAt === null || activeAction.endsAt > now));
}

function actionConflictGroups(action) {
  return new Set(action.conflictGroups || [action.group]);
}

function holdVisibleAction(action, options = {}) {
  const now = performance.now();
  const mode = options.mode || action.defaultMode || "pulse";
  const durationMs = Number(options.durationMs || action.durationMs || 2600);
  const conflictGroups = actionConflictGroups(action);
  modelState.activeActions.forEach((activeAction) => {
    if (conflictGroups.has(activeAction.group)) {
      activeAction.endsAt = Math.min(activeAction.endsAt ?? Infinity, now + ACTION_FADE_MS);
    }
  });
  modelState.activeActions.push({
    name: action.name,
    group: action.group,
    parameters: { ...(action.parameters || {}) },
    startedAt: now,
    endsAt: mode === "hold" ? null : now + durationMs,
  });
}

async function requestChatPlan(userText) {
  const response = await fetch(CHAT_API_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      text: String(userText || "").trim(),
      rate: currentSpeechRate(),
    }),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.error || `LLM 服务返回 HTTP ${response.status}`);
  }
  return payload;
}

populateActionDisk();
document.getElementById("actionDiskButton").addEventListener("click", () => openSidePanel(actionPanel));
document.getElementById("voiceModelButton").addEventListener("click", () => openSidePanel(voicePanel));
document.getElementById("skinModelButton").addEventListener("click", () => openSidePanel(skinPanel));
document.getElementById("cameraPanelButton").addEventListener("click", () => {
  openSidePanel(cameraPanel);
  refreshCameraDevices({ requestPermission: false });
});
document.getElementById("audioPanelButton").addEventListener("click", () => {
  openSidePanel(audioPanel);
  refreshAudioDevices({ requestPermission: false });
});
document.getElementById("controlLogButton").addEventListener("click", () => {
  renderControlLog();
  openSidePanel(logPanel);
});
document.getElementById("historyButton").addEventListener("click", () => {
  renderChatHistory();
  toggleSidePanel(historyPanel);
});
document.getElementById("closeActionPanelButton").addEventListener("click", () => closeSidePanel(actionPanel));
document.getElementById("closeVoicePanelButton").addEventListener("click", () => closeSidePanel(voicePanel));
document.getElementById("closeSkinPanelButton").addEventListener("click", () => closeSidePanel(skinPanel));
document.getElementById("closeCameraPanelButton").addEventListener("click", () => closeSidePanel(cameraPanel));
document.getElementById("closeAudioPanelButton").addEventListener("click", () => closeSidePanel(audioPanel));
document.getElementById("closeLogPanelButton").addEventListener("click", () => closeSidePanel(logPanel));
cameraSelectEl.addEventListener("change", () => {
  modelState.selectedCameraId = cameraSelectEl.value;
  setCameraStatus("已选择摄像头。", selectedCameraLabel());
  renderCameraControls();
});
cameraDetectButton.addEventListener("click", () => refreshCameraDevices({ requestPermission: true }));
cameraStartButton.addEventListener("click", startCameraPreview);
cameraStopButton.addEventListener("click", () => stopCameraPreview());
cameraDefaultButton.addEventListener("click", saveDefaultCamera);
audioSelectEl.addEventListener("change", () => {
  modelState.selectedAudioId = audioSelectEl.value;
  setAudioStatus("已选择麦克风。", selectedAudioLabel());
  renderAudioControls();
});
audioDetectButton.addEventListener("click", () => refreshAudioDevices({ requestPermission: true }));
audioStartButton.addEventListener("click", startAudioMonitor);
audioStopButton.addEventListener("click", () => stopAudioMonitor());
audioDefaultButton.addEventListener("click", saveDefaultAudio);
referenceSelectEl.addEventListener("change", () => selectReference(referenceSelectEl.value));
referenceTextInputEl.addEventListener("input", () => {
  markUserActivity();
  modelState.referencePromptText = referenceTextInputEl.value;
  updateVoiceStatus();
});
speechRateInput.addEventListener("input", () => {
  markUserActivity();
  const safeRate = syncSpeechRateControl(Number(speechRateInput.value));
  syncActiveSpeechRate(safeRate);
});
chatInput.addEventListener("input", markUserActivity);
chatInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && event.ctrlKey) {
    event.preventDefault();
    chatForm.requestSubmit();
  }
});
chatForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const userText = chatInput.value.trim();
  if (!userText) {
    setStatus("请输入对话内容", "空输入不会发送给 LLM。");
    return;
  }
  const previousReply = replyEl.textContent;
  markUserActivity();
  clearScheduledActions();
  startThinkingAnimation();
  chatInput.value = "";
  setReplyThinking();
  setStatus("正在请求 LLM", "本地控制服务会调用 DeepSeek，并返回结构化 Live2D 控制计划。");
  addControlLog("用户输入", { text: userText });
  requestChatPlan(userText)
    .then((plan) => {
      addChatHistory(userText, plan.text, plan);
      return applyPlan(plan, { speak: true });
    })
    .catch((error) => {
      stopThinkingAnimation({ restoreMotion: true, clearRoulette: true });
      setReplyText(previousReply);
      addChatHistory(userText, "", null, error.message);
      addControlLog("LLM 回复失败", { error: error.message });
      setStatus("LLM 回复失败", error.message);
      scheduleIdleAction();
    });
});

setupCameraWindowDrag();
setupAudioWindowDrag();
initializeCameraControls();
initializeAudioControls();
window.addEventListener("beforeunload", () => {
  stopCameraPreview({ quiet: true });
  stopAudioMonitor({ quiet: true });
});

initStage().catch((error) => {
  console.error(error);
  setStatus("Live2D 舞台启动失败", error.message);
});
