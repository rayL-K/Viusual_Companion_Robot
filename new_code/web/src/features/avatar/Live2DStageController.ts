import { SignalMixer, type AvatarRenderIntent } from "./SignalMixer";
import {
  AvatarActionScheduler,
  STRAWBERRY_RABBIT_CAPABILITIES,
  type AvatarActionEnvelope,
  type AvatarOverlayExecutor,
} from "./AvatarActionScheduler";
import { AvatarInteractionController, type LocalContactFeedback } from "./interaction/AvatarInteractionController";
import { InteractionDirector } from "./interaction/InteractionDirector";
import { Live2DHitTestPort } from "./interaction/Live2DHitTestPort";

const DESKTOP_MODEL_URL = "/live2d/Strawberry_Rabbit/Strawberry_Rabbit.model3.json";
const MOBILE_MODEL_URL = "/live2d/Strawberry_Rabbit/Strawberry_Rabbit.mobile-1024-r2.model3.json";
const HIDDEN_DISPLAY_PARAMETERS: Readonly<Record<string, number>> = {
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

export type Live2DProfileInput = {
  coarsePointer: boolean;
  narrowViewport: boolean;
  deviceMemoryGb: number;
  maxTextureSize: number;
};

export type Live2DProfile = {
  modelUrl: string;
  renderResolution: number;
  label: "desktop" | "mobile";
};

const INITIAL_RENDER_INTENT: AvatarRenderIntent = {
  phase: "idle",
  expression: "soft",
  motion: "idle",
  gazeStrength: 0.68,
  bodyTension: 0.22,
  smile: 0.52,
  eyeOpen: 0.82,
  speechRate: 1,
  speechPitch: 1,
  affect: {
    valence: 0.12,
    arousal: 0.15,
    dominance: 0,
    affinity: 0.25,
    trust: 0.2,
  },
};

type CoreModel = {
  setParameterValueById: (id: string, value: number, weight?: number) => void;
};

type ExpressionManager = { resetExpression: () => void };
type MotionManager = {
  expressionManager?: ExpressionManager;
  stopAllMotions: () => void;
};
type InternalModel = {
  coreModel?: CoreModel;
  motionManager?: MotionManager;
  on?: (event: "beforeModelUpdate", callback: () => void) => void;
  off?: (event: "beforeModelUpdate", callback: () => void) => void;
};

type Live2DModel = {
  anchor?: { set: (x: number, y?: number) => void };
  scale: { x: number; y: number; set: (value: number) => void };
  position?: { set: (x: number, y: number) => void };
  x: number;
  y: number;
  width: number;
  height: number;
  internalModel?: InternalModel;
  expression?: (name: string) => Promise<boolean>;
  motion?: (group: string, index?: number, priority?: number) => Promise<boolean>;
  hitTest?: (x: number, y: number) => string[];
  destroy?: () => void;
};

type PixiRenderer = {
  gl?: WebGLRenderingContext;
  screen?: { width: number; height: number };
  plugins?: {
    interaction?: {
      mapPositionToPoint: (point: { x: number; y: number }, clientX: number, clientY: number) => void;
    };
  };
};

type PixiApplication = {
  stage: { addChild: (model: Live2DModel) => void };
  ticker: {
    deltaMS: number;
    maxFPS: number;
    minFPS: number;
    add: (callback: () => void) => void;
    remove: (callback: () => void) => void;
  };
  renderer?: PixiRenderer;
  destroy: (removeView: boolean, options: { children: boolean; texture: boolean; baseTexture: boolean }) => void;
};

type PixiRuntime = {
  Application: new (options: Record<string, unknown>) => PixiApplication;
  Ticker?: { shared?: { maxFPS: number } };
  live2d: { Live2DModel: { from: (url: string, options: { autoInteract: boolean }) => Promise<Live2DModel> } };
};

declare global {
  interface Window {
    PIXI?: PixiRuntime;
  }
}

export class Live2DStageController {
  private app: PixiApplication | null = null;
  private model: Live2DModel | null = null;
  private resizeObserver: ResizeObserver | null = null;
  private intent: AvatarActionEnvelope = INITIAL_RENDER_INTENT;
  private actionScheduler: AvatarActionScheduler | null = null;
  private interactionController: AvatarInteractionController | null = null;
  private readonly interactionDirector = new InteractionDirector();
  private feedbackTimer: ReturnType<typeof setTimeout> | null = null;
  private gaze = { x: 0, y: 0 };
  private externalAudioRms = 0;
  private externalAudioAt = 0;
  private readonly mixer = new SignalMixer();
  private readonly applyContinuousSignals = () => this.updateFrame();
  private readonly resize = () => this.fitModel();

  constructor(
    private readonly canvas: HTMLCanvasElement,
    private readonly host: HTMLElement,
  ) {}

  async start(): Promise<Live2DProfile> {
    this.destroy();
    const runtime = window.PIXI;
    if (!runtime?.live2d?.Live2DModel) throw new Error("本地 Cubism/Pixi Live2D 运行库未加载");

    const requestedResolution = Math.min(window.devicePixelRatio || 1, 1.5);
    const initialProfile = selectLive2DProfile(readBrowserProfileInput(), requestedResolution);
    const app = new runtime.Application({
      view: this.canvas,
      resizeTo: this.host,
      backgroundAlpha: 0,
      antialias: true,
      autoDensity: true,
      resolution: initialProfile.renderResolution,
      powerPreference: "high-performance",
      preserveDrawingBuffer: false,
    });
    this.app = app;
    app.ticker.maxFPS = 60;
    app.ticker.minFPS = 20;
    if (runtime.Ticker?.shared) runtime.Ticker.shared.maxFPS = 60;

    const profile = selectLive2DProfile(readProfileInput(app), requestedResolution);
    try {
      const model = await runtime.live2d.Live2DModel.from(profile.modelUrl, { autoInteract: false });
      if (this.app !== app) {
        model.destroy?.();
        throw new Error("Live2D 舞台已在加载期间关闭");
      }
      this.model = model;
      this.actionScheduler = new AvatarActionScheduler(
        createOverlayExecutor(model),
        STRAWBERRY_RABBIT_CAPABILITIES,
      );
      this.actionScheduler.submit(this.intent);
      model.internalModel?.on?.("beforeModelUpdate", this.applyContinuousSignals);
      app.stage.addChild(model);
      this.fitModel();
      if (!model.hitTest || !app.renderer) throw new Error("Live2D 身体命中运行时不可用");
      this.interactionController = new AvatarInteractionController(
        this.host,
        new Live2DHitTestPort(
          { hitTest: (x, y) => model.hitTest?.(x, y) ?? [] },
          app.renderer,
          this.canvas,
        ),
        {
          onInteraction: (event) => {
            this.interactionDirector.accept(event, this.intent);
            this.host.dataset.interactionArea = event.area;
            this.host.dataset.interactionGesture = event.gesture;
            this.host.dataset.interactionSequence = String(event.sequence);
          },
          onGaze: (gaze) => { this.gaze = gaze; },
          onFeedback: (feedback) => this.showInteractionFeedback(feedback),
        },
      );
      this.interactionController.start();
      if (typeof ResizeObserver !== "undefined") {
        this.resizeObserver = new ResizeObserver(this.resize);
        this.resizeObserver.observe(this.host);
      } else {
        window.addEventListener("resize", this.resize, { passive: true });
      }
      return profile;
    } catch (error) {
      this.destroy();
      throw error;
    }
  }

  setIntent(intent: AvatarActionEnvelope): void {
    const result = this.actionScheduler?.submit(intent);
    if (result && !result.accepted) return;
    this.intent = intent;
  }

  setAudioRms(rms: number): void {
    this.externalAudioRms = clamp(rms, 0, 1);
    this.externalAudioAt = performance.now();
  }

  primaryContact(): void {
    this.interactionController?.primaryContact();
  }

  destroy(): void {
    this.resizeObserver?.disconnect();
    this.resizeObserver = null;
    window.removeEventListener("resize", this.resize);
    this.interactionController?.destroy();
    this.interactionController = null;
    this.interactionDirector.reset();
    if (this.feedbackTimer !== null) clearTimeout(this.feedbackTimer);
    this.feedbackTimer = null;
    delete this.host.dataset.contactPulse;
    delete this.host.dataset.interactionArea;
    delete this.host.dataset.interactionGesture;
    delete this.host.dataset.interactionSequence;
    this.host.style.removeProperty("--contact-x");
    this.host.style.removeProperty("--contact-y");
    this.model?.internalModel?.off?.("beforeModelUpdate", this.applyContinuousSignals);
    this.actionScheduler?.destroy();
    this.actionScheduler = null;
    this.app?.destroy(false, { children: true, texture: true, baseTexture: true });
    this.app = null;
    this.model = null;
  }

  private updateFrame(): void {
    const coreModel = this.model?.internalModel?.coreModel;
    if (!coreModel) return;
    const now = performance.now();
    const deltaMs = clamp(this.app?.ticker.deltaMS ?? 1000 / 60, 1, 50);
    const audioRms = selectMouthAudioRms({
      actualRms: this.externalAudioRms,
      actualAgeMs: now - this.externalAudioAt,
      intent: this.intent,
      elapsedMs: now,
    });
    const frame = this.mixer.update({
      elapsedMs: now,
      deltaMs,
      intent: this.intent,
      audioRms,
      gaze: this.gaze,
      reflex: this.interactionDirector.sample(now),
    });

    for (const [id, value] of Object.entries(HIDDEN_DISPLAY_PARAMETERS)) {
      coreModel.setParameterValueById(id, value, 1);
    }
    coreModel.setParameterValueById("ParamAngleX", frame.headX, 0.9);
    coreModel.setParameterValueById("ParamAngleY", frame.headY, 0.9);
    coreModel.setParameterValueById("ParamBodyAngleX", frame.bodyX, 0.65);
    coreModel.setParameterValueById("ParamEyeBallX", frame.eyeX, 0.9);
    coreModel.setParameterValueById("ParamEyeBallY", frame.eyeY, 0.9);
    coreModel.setParameterValueById("ParamEyeLOpen", blinkingValue(now) * frame.eyeOpen, 0.85);
    coreModel.setParameterValueById("ParamEyeROpen", blinkingValue(now) * frame.eyeOpen, 0.85);
    coreModel.setParameterValueById("ParamMouthOpenY", frame.mouthOpen, 1);
    coreModel.setParameterValueById("ParamMouthForm", frame.smile * 1.4 - 0.45, 0.75);
    coreModel.setParameterValueById("ParamBreath", frame.breath, 0.7);
  }

  private fitModel(): void {
    const model = this.model;
    if (!model) return;
    const { width, height } = this.host.getBoundingClientRect();
    if (width < 1 || height < 1) return;
    model.scale.set(1);
    const naturalWidth = Math.max(model.width, 1);
    const naturalHeight = Math.max(model.height, 1);
    const scale = Math.min(width * 0.88 / naturalWidth, height * 1.04 / naturalHeight);
    model.scale.set(scale);
    model.anchor?.set(0.5, 0.5);
    if (model.position) model.position.set(width * 0.5, height * 0.52);
    else { model.x = width * 0.5; model.y = height * 0.52; }
  }

  private showInteractionFeedback(feedback: LocalContactFeedback): void {
    const rect = this.host.getBoundingClientRect();
    const x = clamp((feedback.clientX - rect.left) / Math.max(rect.width, 1) * 100, 0, 100);
    const y = clamp((feedback.clientY - rect.top) / Math.max(rect.height, 1) * 100, 0, 100);
    this.host.style.setProperty("--contact-x", `${x}%`);
    this.host.style.setProperty("--contact-y", `${y}%`);
    delete this.host.dataset.contactPulse;
    void this.host.offsetWidth;
    this.host.dataset.contactPulse = feedback.area;
    if (this.feedbackTimer !== null) clearTimeout(this.feedbackTimer);
    this.feedbackTimer = setTimeout(() => {
      delete this.host.dataset.contactPulse;
      this.feedbackTimer = null;
    }, 560);
  }
}

function createOverlayExecutor(model: Live2DModel): AvatarOverlayExecutor {
  return {
    setExpression: (name) => model.expression?.(name) ?? false,
    resetExpression: () => model.internalModel?.motionManager?.expressionManager?.resetExpression(),
    startMotion: (group, priority) => model.motion?.(group, undefined, priority) ?? false,
    stopMotions: () => model.internalModel?.motionManager?.stopAllMotions(),
  };
}

export function selectLive2DProfile(input: Live2DProfileInput, requestedResolution = 1): Live2DProfile {
  const constrained = input.coarsePointer
    || input.narrowViewport
    || (input.deviceMemoryGb > 0 && input.deviceMemoryGb <= 6)
    || (input.maxTextureSize > 0 && input.maxTextureSize <= 4096);
  return constrained
    ? { modelUrl: MOBILE_MODEL_URL, renderResolution: 1, label: "mobile" }
    : { modelUrl: DESKTOP_MODEL_URL, renderResolution: requestedResolution, label: "desktop" };
}

function readProfileInput(app: PixiApplication): Live2DProfileInput {
  const gl = app.renderer?.gl;
  return { ...readBrowserProfileInput(), maxTextureSize: Number(gl?.getParameter(gl.MAX_TEXTURE_SIZE) ?? 0) };
}

function readBrowserProfileInput(): Live2DProfileInput {
  const memoryNavigator = navigator as Navigator & { deviceMemory?: number };
  return {
    coarsePointer: window.matchMedia("(pointer: coarse)").matches,
    narrowViewport: window.matchMedia("(max-width: 900px)").matches,
    deviceMemoryGb: Number(memoryNavigator.deviceMemory ?? 0),
    maxTextureSize: 0,
  };
}

export type MouthAudioInput = {
  actualRms: number;
  actualAgeMs: number;
  intent: AvatarRenderIntent;
  elapsedMs: number;
};

export function selectMouthAudioRms(input: MouthAudioInput): number {
  if (input.actualAgeMs >= 0 && input.actualAgeMs < 120) return clamp(input.actualRms, 0, 1);
  return syntheticSpeechRms(input.intent, input.elapsedMs);
}

function syntheticSpeechRms(intent: AvatarRenderIntent, nowMs: number): number {
  if (intent.phase !== "speaking") return 0;
  const rate = clamp(intent.speechRate, 0.5, 2);
  const pitch = clamp(intent.speechPitch, 0.5, 2);
  return 0.16 + Math.abs(Math.sin(nowMs / (83 / rate)) * Math.sin(nowMs / (47 / pitch))) * 0.28;
}

function blinkingValue(nowMs: number): number {
  const cycle = nowMs % 4_300;
  if (cycle < 70) return 0.12;
  if (cycle < 150) return 0.48;
  return 1;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}
