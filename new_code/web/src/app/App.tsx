import { useEffect, useMemo, useRef, useState } from "preact/hooks";

import { MediaSession } from "../core/media/MediaSession";
import { RealtimeClient, realtimeUrl } from "../core/realtime/RealtimeClient";
import { parseAvatarIntentPayload } from "../core/realtime/protocol";
import {
  applyAvatarIntent,
  assistantText,
  avatarIntent,
  connectionPhase,
  drawerOpen,
  replyPhase,
  transcript,
  visualSummary,
} from "../core/state/session";
import { AvatarStage } from "../features/avatar/AvatarStage";
import { CallControls } from "../features/call/CallControls";
import { CameraPreview } from "../features/call/CameraPreview";

export function App() {
  const [draft, setDraft] = useState("");
  const [callActive, setCallActive] = useState(false);
  const [callStarting, setCallStarting] = useState(false);
  const [cameraEnabled, setCameraEnabled] = useState(true);
  const [microphoneEnabled, setMicrophoneEnabled] = useState(true);
  const [callSeconds, setCallSeconds] = useState(0);
  const [mediaError, setMediaError] = useState("");
  const videoRef = useRef<HTMLVideoElement>(null);
  const callStartedAtRef = useRef(0);
  const client = useMemo(() => new RealtimeClient(realtimeUrl()), []);
  const media = useMemo(() => new MediaSession(client), [client]);

  useEffect(() => {
    const removeHandler = client.onEvent((event) => {
      if (event.type === "reply.phase") replyPhase.value = parseReplyPhase(event.payload.phase);
      if (event.type === "reply.segment.ready") {
        const text = String(event.payload.text ?? "");
        assistantText.value = Number(event.payload.index) === 0 ? text : assistantText.value + text;
        replyPhase.value = "speaking";
      }
      if (event.type === "reply.completed") replyPhase.value = "idle";
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
    client.connect();
    return () => {
      removeHandler();
      media.stop(videoRef.current);
      client.disconnect();
    };
  }, [client, media]);

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

  const submit = () => {
    const text = draft.trim();
    if (!text) return;
    if (client.send("turn.user_text", { text })) {
      replyPhase.value = "thinking";
      setDraft("");
    }
  };

  return (
    <main class="shell">
      <header class="topbar">
        <div class="brand">
          <span class="brand__mark">V</span>
          <div><strong>草莓兔兔</strong><small>VeyraSoul · living companion</small></div>
        </div>
        <div class="topbar__actions">
          {callActive && <span class="call-duration"><i />{formatDuration(callSeconds)}</span>}
          <span class={`connection connection--${connectionPhase.value}`}>
            <i />{connectionLabel(connectionPhase.value)}
          </span>
          <button class="icon-button" type="button" onClick={() => (drawerOpen.value = true)} aria-label="打开控制台">⌁</button>
        </div>
      </header>

      <AvatarStage phase={replyPhase} intent={avatarIntent} />
      <CameraPreview videoRef={videoRef} visible={callActive} cameraEnabled={cameraEnabled} />

      <section class="dialogue" aria-live="polite">
        <div class="dialogue__identity"><span>草莓兔兔</span><small>与你同在</small></div>
        <p>{assistantText.value}</p>
      </section>

      <section class={`composer ${callActive ? "composer--in-call" : "composer--pre-call"}`} aria-label="对话输入">
        <button
          class={`voice-button ${callActive && !microphoneEnabled ? "is-off" : ""}`}
          type="button"
          aria-label={callActive ? (microphoneEnabled ? "关闭麦克风" : "打开麦克风") : "开始语音通话"}
          onClick={() => callActive ? toggleMicrophone() : void startCall()}
        >{callActive && !microphoneEnabled ? "×" : "◉"}</button>
        <label class="composer__field">
          <span class="sr-only">输入想说的话</span>
          <textarea
            value={draft}
            onInput={(event) => setDraft(event.currentTarget.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); submit(); }
            }}
            placeholder={transcript.value || "告诉我你正在想什么…"}
            rows={1}
          />
        </label>
        <button class="send-button" type="button" onClick={submit} disabled={!draft.trim()}>发送</button>
      </section>

      {callActive ? (
        <CallControls
          cameraEnabled={cameraEnabled}
          microphoneEnabled={microphoneEnabled}
          onToggleCamera={toggleCamera}
          onToggleMicrophone={toggleMicrophone}
          onEnd={endCall}
        />
      ) : (
        <button class="start-call" type="button" onClick={() => void startCall()} disabled={callStarting}>
          <span>◉</span><strong>{callStarting ? "正在建立通话…" : "开始陪伴通话"}</strong><small>打开摄像头与麦克风</small>
        </button>
      )}
      {mediaError && <p class="media-error" role="alert">{mediaError}</p>}

      <aside class={`drawer ${drawerOpen.value ? "drawer--open" : ""}`} aria-hidden={!drawerOpen.value}>
        <div class="drawer__header"><div><small>CONTROL ROOM</small><h2>感知与连接</h2></div><button type="button" onClick={() => (drawerOpen.value = false)}>×</button></div>
        <article class="sense-card"><span>视觉上下文</span><p>{visualSummary.value}</p></article>
        <article class="sense-card"><span>隐私边界</span><p>摄像头、语音、记忆与 RAG 均在 ELF2 处理。</p></article>
        <div class="drawer__controls"><button type="button">摄像头</button><button type="button">麦克风</button><button type="button">角色设置</button><button type="button">运行状态</button></div>
      </aside>
      {drawerOpen.value && <button class="scrim" type="button" aria-label="关闭控制台" onClick={() => (drawerOpen.value = false)} />}
    </main>
  );
}

function parseReplyPhase(value: unknown): typeof replyPhase.value {
  return value === "listening" || value === "thinking" || value === "speaking" ? value : "idle";
}

function connectionLabel(phase: typeof connectionPhase.value): string {
  if (phase === "online") return "ELF2 在线";
  if (phase === "offline") return "ELF2 离线";
  if (phase === "error") return "连接异常";
  return "正在连接";
}

function formatDuration(seconds: number): string {
  const minutes = Math.floor(seconds / 60).toString().padStart(2, "0");
  const remainder = (seconds % 60).toString().padStart(2, "0");
  return `${minutes}:${remainder}`;
}
