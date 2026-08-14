import { useEffect, useMemo, useRef, useState } from "preact/hooks";

import {
  bootstrapAccess,
  TocApiClient,
  TocApiError,
  type TocAnima,
  type TocUser,
} from "../core/api/toc";
import { MediaSession } from "../core/media/MediaSession";
import { ensureRealtimeAdmission } from "../core/realtime/admission";
import { RealtimeClient, realtimeUrl } from "../core/realtime/RealtimeClient";
import { parseAvatarIntentPayload, type ServerEvent } from "../core/realtime/protocol";
import {
  applyAvatarIntent,
  assistantText,
  avatarIntent,
  connectionPhase,
  drawerOpen,
  replyPhase,
  resetAvatarGenerationDomain,
  transcript,
  visualSummary,
} from "../core/state/session";
import { AvatarStage } from "../features/avatar/AvatarStage";
import { CallControls } from "../features/call/CallControls";
import { CameraPreview } from "../features/call/CameraPreview";
import { AnimaSettingsPanel } from "../features/settings/AnimaSettingsPanel";

type DrawerView = "overview" | "settings";
export type ReplyTextCursor = Readonly<{
  sessionId: string;
  generation: number;
  nextIndex: number;
}>;
type AuthState =
  | { phase: "loading" }
  | { phase: "unauthenticated" }
  | { phase: "recoverable"; message: string }
  | { phase: "unavailable" }
  | { phase: "anonymous"; animas: TocAnima[] }
  | { phase: "authenticated"; user: TocUser; animas: TocAnima[] };

export const PRODUCT_NAME = "Anima";
export const PRODUCT_VERSION = "v0.0.1";

export function App() {
  const api = useMemo(() => new TocApiClient(), []);
  const [authState, setAuthState] = useState<AuthState>({ phase: "loading" });
  const [authAttempt, setAuthAttempt] = useState(0);
  const [selectedAnimaId, setSelectedAnimaId] = useState("");
  const [draft, setDraft] = useState("");
  const [callActive, setCallActive] = useState(false);
  const [callStarting, setCallStarting] = useState(false);
  const [cameraEnabled, setCameraEnabled] = useState(true);
  const [microphoneEnabled, setMicrophoneEnabled] = useState(true);
  const [callSeconds, setCallSeconds] = useState(0);
  const [mediaError, setMediaError] = useState("");
  const [drawerView, setDrawerView] = useState<DrawerView>("overview");
  const videoRef = useRef<HTMLVideoElement>(null);
  const callStartedAtRef = useRef(0);
  const replyTextCursorRef = useRef<ReplyTextCursor>({
    sessionId: "",
    generation: -1,
    nextIndex: 0,
  });
  const client = useMemo(
    () => new RealtimeClient(
      realtimeUrl(window.location, selectedAnimaId || undefined),
      undefined,
      undefined,
      ensureRealtimeAdmission,
    ),
    [selectedAnimaId],
  );
  const media = useMemo(() => new MediaSession(client), [client]);

  useEffect(() => {
    let active = true;
    setAuthState({ phase: "loading" });
    void bootstrapAccess(api)
      .then((access) => {
        if (!active) return;
        if (access.mode === "unavailable") {
          setAuthState({ phase: "unavailable" });
          setSelectedAnimaId("");
          return;
        }
        const animas = access.mode === "toc" ? access.animas : [access.anima];
        setAuthState(
          access.mode === "toc"
            ? { phase: "authenticated", user: access.user, animas }
            : { phase: "anonymous", animas },
        );
        setSelectedAnimaId((current) =>
          animas.some((anima) => anima.id === current)
            ? current
            : (animas[0]?.id ?? ""),
        );
      })
      .catch((error: unknown) => {
        if (!active) return;
        if (error instanceof TocApiError && error.kind === "unauthenticated") {
          setAuthState({ phase: "unauthenticated" });
          return;
        }
        setAuthState({
          phase: "recoverable",
          message: error instanceof Error ? error.message : "服务暂时不可达",
        });
      });
    return () => { active = false; };
  }, [api, authAttempt]);

  useEffect(() => {
    if (
      (authState.phase !== "authenticated" && authState.phase !== "anonymous")
      || !selectedAnimaId
    ) return;
    const removeHandler = client.onEvent((event) => {
      if (event.type === "session.ready") {
        resetAvatarGenerationDomain(event.sessionId);
        replyTextCursorRef.current = {
          sessionId: event.sessionId,
          generation: -1,
          nextIndex: 0,
        };
      }
      if (event.type === "reply.phase") replyPhase.value = parseReplyPhase(event.payload.phase);
      if (event.type === "reply.segment.ready" || event.type === "reply.segment.started") {
        const update = mergeReplySegmentText(
          assistantText.value,
          replyTextCursorRef.current,
          event,
        );
        if (!update) return;
        assistantText.value = update.text;
        replyTextCursorRef.current = update.cursor;
        replyPhase.value = "speaking";
      }
      if (event.type === "reply.completed") replyPhase.value = "idle";
      if (event.type === "error" && event.payload.code === "reply_failed") {
        replyPhase.value = "idle";
      }
      if (event.type === "avatar.intent") {
        applyAvatarIntent({
          sessionId: event.sessionId,
          generation: event.generation,
          seq: event.seq,
          payload: parseAvatarIntentPayload(event.payload),
        });
      }
      if (event.type === "asr.partial") transcript.value = String(event.payload.text ?? "");
      if (event.type === "asr.final") transcript.value = String(event.payload.text ?? "");
      if (event.type === "perception.snapshot") visualSummary.value = String(event.payload.summary ?? "");
    });
    let active = true;
    void ensureRealtimeAdmission()
      .then(() => {
        if (active) client.connect();
      })
      .catch((error: unknown) => {
        if (!active) return;
        connectionPhase.value = "error";
        setMediaError(error instanceof Error ? error.message : "连接校验暂时失败，请刷新重试");
      });
    return () => {
      active = false;
      removeHandler();
      media.stop(videoRef.current);
      client.disconnect();
    };
  }, [authState.phase, client, media, selectedAnimaId]);

  useEffect(() => {
    if (!callActive) return;
    const timer = window.setInterval(() => {
      setCallSeconds(Math.floor((Date.now() - callStartedAtRef.current) / 1000));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [callActive]);

  const startCall = async () => {
    if (!videoRef.current || callStarting) return;
    try {
      setCallStarting(true);
      setMediaError("");
      await client.enableReplyAudioStream();
      await media.start(videoRef.current);
      setCameraEnabled(true);
      setMicrophoneEnabled(true);
      setCallSeconds(0);
      callStartedAtRef.current = Date.now();
      setCallActive(true);
      replyPhase.value = "listening";
    } catch (error) {
      setMediaError(error instanceof Error ? error.message : "无法打开摄像头或麦克风");
    } finally {
      setCallStarting(false);
    }
  };

  const endCall = () => {
    media.stop(videoRef.current);
    client.send("turn.cancel", {});
    setCallActive(false);
    setCallSeconds(0);
    replyPhase.value = "idle";
  };

  const toggleCamera = () => {
    const enabled = !cameraEnabled;
    setCameraEnabled(enabled);
    media.setCameraEnabled(enabled);
  };

  const toggleMicrophone = () => {
    const enabled = !microphoneEnabled;
    setMicrophoneEnabled(enabled);
    media.setMicrophoneEnabled(enabled);
  };

  const submit = async () => {
    const text = draft.trim();
    if (!text) return;
    await client.enableReplyAudioStream();
    if (client.send("turn.user_text", { text })) {
      replyPhase.value = "thinking";
      setDraft("");
    }
  };

  if (authState.phase !== "authenticated" && authState.phase !== "anonymous") {
    return (
      <SessionGate
        state={authState}
        onRetry={() => setAuthAttempt((attempt) => attempt + 1)}
      />
    );
  }

  const selectedAnima = authState.animas.find(
    (anima) => anima.id === selectedAnimaId,
  );

  return (
    <main class={`shell ${callActive ? "shell--in-call" : "shell--idle"}`}>
      <header class="topbar">
        <div class="brand">
          <span class="brand__mark">A</span>
          <div><strong>{PRODUCT_NAME}</strong><small>{PRODUCT_VERSION} · multimodal companion</small></div>
        </div>
        <div class="topbar__actions">
          {authState.animas.length > 0 && (
            <label class="anima-picker">
              <span class="sr-only">选择 Anima</span>
              <select
                value={selectedAnimaId}
                disabled={callActive}
                onChange={(event) => setSelectedAnimaId(event.currentTarget.value)}
                aria-label="选择 Anima"
              >
                {authState.animas.map((anima) => (
                  <option value={anima.id} key={anima.id}>{anima.displayName}</option>
                ))}
              </select>
            </label>
          )}
          {callActive && <span class="call-duration"><i />{formatDuration(callSeconds)}</span>}
          <span class={`connection connection--${connectionPhase.value}`}>
            <i />{connectionLabel(connectionPhase.value)}
          </span>
          <button class="icon-button" type="button" onClick={() => { setDrawerView("overview"); drawerOpen.value = true; }} aria-label="打开控制台">
            <span class="icon-button__dots" aria-hidden="true"><i /><i /><i /></span>
          </button>
        </div>
      </header>

      <div class="experience">
        <section class="stage-region" aria-label="陪伴画面">
          <AvatarStage phase={replyPhase} intent={avatarIntent} />
          <CameraPreview videoRef={videoRef} visible={callActive} cameraEnabled={cameraEnabled} />
        </section>

        <section class="conversation-rail" aria-label="陪伴对话">
          <section class="dialogue" aria-live="polite">
            <div class="dialogue__identity"><span>{selectedAnima?.displayName ?? PRODUCT_NAME}</span><small>{PRODUCT_VERSION} · 与你同在</small></div>
            <p>{assistantText.value}</p>
          </section>

          <div class="interaction-deck">
            {mediaError && <p class="media-error" role="alert">{mediaError}</p>}
            <section class={`composer ${callActive ? "composer--in-call" : "composer--pre-call"}`} aria-label="对话输入">
              <button
                class={`voice-button ${callActive && !microphoneEnabled ? "is-off" : ""}`}
                type="button"
                aria-label={callActive ? (microphoneEnabled ? "关闭麦克风" : "打开麦克风") : "开始语音通话"}
                onClick={() => callActive ? toggleMicrophone() : void startCall()}
              ><span aria-hidden="true">{callActive && !microphoneEnabled ? "×" : "◉"}</span></button>
              <label class="composer__field">
                <span class="sr-only">输入想说的话</span>
                <textarea
                  value={draft}
                  onInput={(event) => setDraft(event.currentTarget.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); void submit(); }
                  }}
                  placeholder={transcript.value || "告诉我你正在想什么…"}
                  rows={1}
                />
              </label>
              <button class="send-button" type="button" onClick={() => void submit()} disabled={!draft.trim()}>发送</button>
            </section>

            <div class="call-actions">
              {callActive ? (
                <CallControls
                  cameraEnabled={cameraEnabled}
                  microphoneEnabled={microphoneEnabled}
                  onToggleCamera={toggleCamera}
                  onToggleMicrophone={toggleMicrophone}
                  onEnd={endCall}
                />
              ) : (
                <button class="start-call" type="button" onClick={() => void startCall()} disabled={callStarting || !selectedAnima}>
                  <span aria-hidden="true">◉</span>
                  <strong>{callStarting ? "正在建立通话…" : "开始陪伴通话"}</strong>
                  <small>打开摄像头与麦克风</small>
                </button>
              )}
            </div>
          </div>
        </section>
      </div>

      <aside class={`drawer ${drawerView === "settings" ? "drawer--settings" : ""} ${drawerOpen.value ? "drawer--open" : ""}`} aria-hidden={!drawerOpen.value}>
        <div class="drawer__header"><div><small>CONTROL ROOM</small><h2>感知与连接</h2></div><button type="button" aria-label="关闭控制台" onClick={() => (drawerOpen.value = false)}>×</button></div>
        <div class="drawer__body">
          {drawerView === "settings" ? (
            <AnimaSettingsPanel
              api={authState.phase === "authenticated" ? api : null}
              client={client}
              onBack={() => setDrawerView("overview")}
            />
          ) : (
            <>
              <article class="sense-card"><span>视觉上下文</span><p>{visualSummary.value}</p></article>
              <article class="sense-card"><span>数据边界</span><p>{authState.phase === "anonymous" ? "显式匿名体验空间" : `${authState.user.displayName} 的独立空间`} · 当前 Anima：{selectedAnima?.displayName ?? "尚未选择"}</p></article>
              <div class="drawer__controls">
                <button type="button" onClick={toggleCamera} disabled={!callActive}>{cameraEnabled ? "关闭摄像头" : "打开摄像头"}</button>
                <button type="button" onClick={toggleMicrophone} disabled={!callActive}>{microphoneEnabled ? "关闭麦克风" : "打开麦克风"}</button>
                <button type="button" onClick={() => setDrawerView("settings")}>角色设置</button>
              </div>
            </>
          )}
        </div>
      </aside>
      {drawerOpen.value && <button class="scrim" type="button" aria-label="关闭控制台" onClick={() => (drawerOpen.value = false)} />}
    </main>
  );
}

function SessionGate({
  state,
  onRetry,
}: {
  state: Exclude<AuthState, { phase: "authenticated" } | { phase: "anonymous" }>;
  onRetry: () => void;
}) {
  const loading = state.phase === "loading";
  const unauthenticated = state.phase === "unauthenticated";
  const unavailable = state.phase === "unavailable";
  return (
    <main class="session-gate">
      <section class="session-gate__card" aria-live="polite">
        <span class="brand__mark">A</span>
        <small>ANIMA · PRIVATE MULTIMODAL SPACE</small>
        <h1>{loading ? "正在确认访问方式" : unauthenticated ? "欢迎回到 Anima" : unavailable ? "服务尚未开放" : "连接暂时走神了"}</h1>
        <p>
          {loading
            ? "正在确认安全会话与专属角色…"
            : unauthenticated
              ? "登录后继续你的私人陪伴空间。"
              : unavailable
                ? "服务未配置访问方式，请联系服务管理员。"
              : state.message}
        </p>
        {!loading && !unavailable && (
          unauthenticated
            ? <a class="session-gate__cta" href="/auth/login">安全登录</a>
            : <button class="session-gate__cta" type="button" onClick={onRetry}>重新连接</button>
        )}
      </section>
    </main>
  );
}

function parseReplyPhase(value: unknown): typeof replyPhase.value {
  return value === "listening" || value === "thinking" || value === "speaking" ? value : "idle";
}

export function mergeReplySegmentText(
  currentText: string,
  cursor: ReplyTextCursor,
  event: ServerEvent,
): { text: string; cursor: ReplyTextCursor } | null {
  if (event.type !== "reply.segment.ready" && event.type !== "reply.segment.started") return null;
  const index = event.payload.index;
  const text = event.payload.text;
  if (
    typeof index !== "number"
    || !Number.isSafeInteger(index)
    || index < 0
    || typeof text !== "string"
    || !text
  ) return null;

  const isNewSession = event.sessionId !== cursor.sessionId;
  const isNewGeneration = !isNewSession && event.generation > cursor.generation;
  if (!isNewSession && event.generation < cursor.generation) return null;
  if ((isNewSession || isNewGeneration) && index !== 0) return null;

  const activeCursor: ReplyTextCursor = isNewSession || isNewGeneration
    ? { sessionId: event.sessionId, generation: event.generation, nextIndex: 0 }
    : cursor;
  if (event.generation !== activeCursor.generation || index !== activeCursor.nextIndex) return null;
  return {
    text: index === 0 ? text : currentText + text,
    cursor: {
      sessionId: activeCursor.sessionId,
      generation: activeCursor.generation,
      nextIndex: activeCursor.nextIndex + 1,
    },
  };
}

export function connectionLabel(phase: typeof connectionPhase.value): string {
  if (phase === "online") return "服务节点已连接";
  if (phase === "offline") return "服务节点暂不可用";
  if (phase === "error") return "服务节点连接异常";
  return "正在接入服务节点";
}

function formatDuration(seconds: number): string {
  const minutes = Math.floor(seconds / 60).toString().padStart(2, "0");
  const remainder = (seconds % 60).toString().padStart(2, "0");
  return `${minutes}:${remainder}`;
}
