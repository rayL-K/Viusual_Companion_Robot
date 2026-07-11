import { useEffect, useMemo, useState } from "preact/hooks";

import { RealtimeClient, realtimeUrl } from "../core/realtime/RealtimeClient";
import {
  assistantText,
  connectionPhase,
  drawerOpen,
  replyPhase,
  transcript,
  visualSummary,
} from "../core/state/session";
import { AvatarStage } from "../features/avatar/AvatarStage";

export function App() {
  const [draft, setDraft] = useState("");
  const client = useMemo(() => new RealtimeClient(realtimeUrl()), []);

  useEffect(() => {
    const removeHandler = client.onEvent((event) => {
      if (event.type === "reply.phase") replyPhase.value = String(event.payload.phase) as typeof replyPhase.value;
      if (event.type === "reply.segment.ready") assistantText.value = String(event.payload.text ?? "");
      if (event.type === "asr.partial") transcript.value = String(event.payload.text ?? "");
      if (event.type === "perception.snapshot") visualSummary.value = String(event.payload.summary ?? "");
    });
    client.connect();
    return () => {
      removeHandler();
      client.disconnect();
    };
  }, [client]);

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
          <span class={`connection connection--${connectionPhase.value}`}>
            <i />{connectionPhase.value === "online" ? "ELF2 在线" : "正在连接"}
          </span>
          <button class="icon-button" type="button" onClick={() => (drawerOpen.value = true)} aria-label="打开控制台">⌁</button>
        </div>
      </header>

      <AvatarStage phase={replyPhase} />

      <section class="dialogue" aria-live="polite">
        <div class="dialogue__identity"><span>草莓兔兔</span><small>与你同在</small></div>
        <p>{assistantText.value}</p>
      </section>

      <section class="composer" aria-label="对话输入">
        <button class="voice-button" type="button" aria-label="开始语音">◉</button>
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
