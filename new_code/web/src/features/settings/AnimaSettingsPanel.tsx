import { useEffect, useState } from "preact/hooks";

import type { RealtimeClient } from "../../core/realtime/RealtimeClient";
import {
  DEFAULT_ANIMA_SETTINGS,
  parseAnimaSettings,
  settingsPatch,
  type AnimaSettings,
} from "./model";

type SaveState = "loading" | "ready" | "saving" | "saved" | "error";

export function AnimaSettingsPanel({ client, onBack }: {
  client: RealtimeClient;
  onBack: () => void;
}) {
  const [draft, setDraft] = useState<AnimaSettings>(DEFAULT_ANIMA_SETTINGS);
  const [saveState, setSaveState] = useState<SaveState>("loading");
  const [message, setMessage] = useState("正在读取独立 Anima 配置…");

  useEffect(() => {
    const removeHandler = client.onEvent((event) => {
      if (event.type === "session.ready") {
        setSaveState("loading");
        setMessage("正在读取独立 Anima 配置…");
        client.send("settings.get", {});
        return;
      }
      if (event.type === "settings.current") {
        try {
          const settings = parseAnimaSettings(event.payload);
          setDraft(settings);
          setSaveState(event.payload.updated === true ? "saved" : "ready");
          setMessage(event.payload.updated === true ? "设置已保存，将从下一轮回复生效。" : "配置已载入。");
        } catch {
          setSaveState("error");
          setMessage("服务端返回了无法识别的设置格式。");
        }
        return;
      }
      if (event.type === "error" && (
      event.payload.code === "invalid_settings"
        || event.payload.code === "settings_conflict"
        || event.payload.code === "settings_read_failed"
        || event.payload.code === "settings_persistence_failed"
      )) {
        setSaveState("error");
        setMessage(String(event.payload.message || "设置保存失败。"));
      }
    });
    client.send("settings.get", {});
    return removeHandler;
  }, [client]);

  const update = <K extends keyof AnimaSettings>(key: K, value: AnimaSettings[K]) => {
    setDraft((current) => ({ ...current, [key]: value }));
    setSaveState("ready");
    setMessage("有尚未保存的更改。");
  };

  const save = () => {
    if (!draft.personaMarkdown.trim()) {
      setSaveState("error");
      setMessage("Anima.md 不能为空。");
      return;
    }
    if (!client.send("settings.update", settingsPatch(draft))) {
      setSaveState("error");
      setMessage("实时连接尚未就绪，请稍后重试。");
      return;
    }
    setSaveState("saving");
    setMessage("正在保存…");
  };

  const reload = () => {
    if (!client.send("settings.get", {})) {
      setSaveState("error");
      setMessage("实时连接尚未就绪，请稍后重试。");
      return;
    }
    setSaveState("loading");
    setMessage("正在重新载入…");
  };

  return (
    <section class="anima-settings" aria-labelledby="anima-settings-title">
      <div class="anima-settings__nav">
        <button type="button" onClick={onBack} aria-label="返回感知与连接">←</button>
        <div><small>ANIMA PROFILE</small><h3 id="anima-settings-title">角色设置</h3></div>
        <span>r{draft.revision || "–"}</span>
      </div>

      <label class="settings-field settings-field--persona">
        <span>Anima.md 人设</span>
        <small>只影响你的 Anima 实例；系统安全约束不会被覆盖。</small>
        <textarea
          value={draft.personaMarkdown}
          maxLength={20_000}
          rows={9}
          onInput={(event) => update("personaMarkdown", event.currentTarget.value)}
          disabled={saveState === "loading"}
        />
      </label>

      <div class="settings-grid">
        <label class="settings-field">
          <span>回复上限</span>
          <small>8–2000 字符</small>
          <input
            type="number"
            min="8"
            max="2000"
            step="1"
            value={draft.maxReplyChars}
            onInput={(event) => update("maxReplyChars", event.currentTarget.valueAsNumber)}
            disabled={saveState === "loading"}
          />
        </label>
        <label class="settings-field">
          <span>回复延迟</span>
          <small>0–10000 毫秒</small>
          <input
            type="number"
            min="0"
            max="10000"
            step="50"
            value={draft.replyDelayMs}
            onInput={(event) => update("replyDelayMs", event.currentTarget.valueAsNumber)}
            disabled={saveState === "loading"}
          />
        </label>
      </div>

      <label class="settings-field">
        <span>音色 ID</span>
        <small>由当前 TTS Port 验证；不会自动切换到 Vox。</small>
        <input
          type="text"
          value={draft.voiceId}
          maxLength={80}
          spellcheck={false}
          onInput={(event) => update("voiceId", event.currentTarget.value)}
          disabled={saveState === "loading"}
        />
      </label>

      <p class={`settings-status settings-status--${saveState}`} role="status">{message}</p>
      <div class="settings-actions">
        <button
          class="settings-reload"
          type="button"
          onClick={reload}
          disabled={saveState === "loading" || saveState === "saving"}
        >重新载入</button>
        <button
          class="settings-save"
          type="button"
          onClick={save}
          disabled={saveState === "loading" || saveState === "saving"}
        >{saveState === "saving" ? "正在保存…" : "保存设置"}</button>
      </div>
    </section>
  );
}
