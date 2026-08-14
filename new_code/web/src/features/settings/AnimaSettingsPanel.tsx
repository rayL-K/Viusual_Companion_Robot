import { useEffect, useState } from "preact/hooks";

import {
  PROVIDER_CAPABILITIES,
  type ProviderCapability,
  type ProviderCatalog,
  type PublicProvider,
  type TocApiClient,
} from "../../core/api/toc";
import type { RealtimeClient } from "../../core/realtime/RealtimeClient";
import {
  catalogProviders,
  DEFAULT_ANIMA_SETTINGS,
  parseAnimaSettings,
  selectionFromCatalog,
  settingsPatch,
  type AnimaSettings,
  validateProviderSelections,
} from "./model";

type SaveState = "loading" | "ready" | "saving" | "saved" | "error";
type CatalogState =
  | { phase: "loading" }
  | { phase: "ready"; catalog: ProviderCatalog }
  | { phase: "unavailable" }
  | { phase: "error"; message: string };

const CAPABILITY_COPY: Record<ProviderCapability, {
  code: string;
  label: string;
  description: string;
}> = {
  llm: { code: "LLM", label: "对话", description: "理解上下文并组织回复" },
  asr: { code: "ASR", label: "听觉", description: "把实时语音转成文字" },
  tts: { code: "TTS", label: "声音", description: "生成 Anima 的说话声音" },
  vision: { code: "VISION", label: "视觉", description: "理解人物、动作与环境" },
};

export function AnimaSettingsPanel({ api, client, onBack }: {
  api: TocApiClient | null;
  client: RealtimeClient;
  onBack: () => void;
}) {
  const [draft, setDraft] = useState<AnimaSettings>(DEFAULT_ANIMA_SETTINGS);
  const [saveState, setSaveState] = useState<SaveState>("loading");
  const [message, setMessage] = useState("正在读取独立 Anima 配置…");
  const [providerDirty, setProviderDirty] = useState(false);
  const [catalogState, setCatalogState] = useState<CatalogState>(
    api ? { phase: "loading" } : { phase: "unavailable" },
  );

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
          setProviderDirty(false);
          setSaveState(event.payload.updated === true ? "saved" : "ready");
          setMessage(event.payload.updated === true
            ? "设置已保存。人设与回复偏好从下一轮生效；服务与音色在下次重新连接后生效。"
            : "配置已载入。");
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

  useEffect(() => {
    if (!api) {
      setCatalogState({ phase: "unavailable" });
      return;
    }
    let active = true;
    setCatalogState({ phase: "loading" });
    void api.providerCatalog()
      .then((catalog) => {
        if (active) setCatalogState({ phase: "ready", catalog });
      })
      .catch((error: unknown) => {
        if (!active) return;
        setCatalogState({
          phase: "error",
          message: error instanceof Error ? error.message : "暂时无法读取服务能力目录",
        });
      });
    return () => { active = false; };
  }, [api]);

  const update = <K extends keyof AnimaSettings>(key: K, value: AnimaSettings[K]) => {
    setDraft((current) => ({ ...current, [key]: value }));
    setSaveState("ready");
    setMessage("有尚未保存的更改。");
  };

  const updateProvider = (
    capability: ProviderCapability,
    provider: PublicProvider,
  ) => {
    setDraft((current) => {
      const selection = selectionFromCatalog(current.providers[capability], provider);
      return {
        ...current,
        voiceId: capability === "tts" && selection.voice
          ? selection.voice
          : current.voiceId,
        providers: {
          ...current.providers,
          [capability]: selection,
        },
      };
    });
    setProviderDirty(true);
    setSaveState("ready");
    setMessage("有尚未保存的服务更改。");
  };

  const updateProviderOption = (
    capability: ProviderCapability,
    field: "model" | "voice",
    value: string,
  ) => {
    setDraft((current) => ({
      ...current,
      voiceId: capability === "tts" && field === "voice" ? value : current.voiceId,
      providers: {
        ...current.providers,
        [capability]: {
          ...current.providers[capability],
          [field]: value,
        },
      },
    }));
    setProviderDirty(true);
    setSaveState("ready");
    setMessage("有尚未保存的服务更改。");
  };

  const disableProvider = (capability: "asr" | "vision") => {
    setDraft((current) => ({
      ...current,
      providers: {
        ...current.providers,
        [capability]: { alias: "disabled", model: "", voice: "" },
      },
    }));
    setProviderDirty(true);
    setSaveState("ready");
    setMessage(`有尚未保存的${CAPABILITY_COPY[capability].label}服务更改。`);
  };

  const save = () => {
    if (!draft.personaMarkdown.trim()) {
      setSaveState("error");
      setMessage("Anima.md 不能为空。");
      return;
    }
    if (providerDirty && catalogState.phase !== "ready") {
      setSaveState("error");
      setMessage("服务目录尚未就绪，暂时不能切换服务。");
      return;
    }
    if (providerDirty && catalogState.phase === "ready") {
      const providerError = validateProviderSelections(draft, catalogState.catalog);
      if (providerError) {
        setSaveState("error");
        setMessage(providerError);
        return;
      }
    }
    if (!client.send(
      "settings.update",
      settingsPatch(draft, { includeProviders: providerDirty }),
    )) {
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
          disabled={saveState === "loading" || saveState === "saving"}
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
            disabled={saveState === "loading" || saveState === "saving"}
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
            disabled={saveState === "loading" || saveState === "saving"}
          />
        </label>
      </div>

      <section class="provider-settings" aria-labelledby="provider-settings-title">
        <div class="provider-settings__heading">
          <div>
            <small>RUNTIME PROVIDERS</small>
            <h4 id="provider-settings-title">感知与表达服务</h4>
          </div>
          <span class={`catalog-state catalog-state--${catalogState.phase}`}>
            {catalogState.phase === "ready"
              ? `目录 r${catalogState.catalog.revision}`
              : catalogState.phase === "loading"
                ? "正在同步"
                : "只读"}
          </span>
        </div>
        <p class="provider-settings__privacy">
          这里只显示服务器公开并已启用的别名、模型和音色。密钥与服务地址始终留在服务器。
        </p>

        {catalogState.phase === "ready" ? (
          <div class="provider-grid">
            {PROVIDER_CAPABILITIES.map((capability) => (
              <ProviderCard
                key={capability}
                capability={capability}
                catalog={catalogState.catalog}
                settings={draft}
                disabled={saveState === "loading" || saveState === "saving"}
                onProvider={updateProvider}
                onOption={updateProviderOption}
                onDisabled={disableProvider}
              />
            ))}
          </div>
        ) : (
          <div class={`catalog-notice catalog-notice--${catalogState.phase}`} role="status">
            <strong>
              {catalogState.phase === "loading"
                ? "正在读取可用服务"
                : catalogState.phase === "unavailable"
                  ? "匿名体验不开放服务切换"
                  : "服务目录暂时不可用"}
            </strong>
            <span>
              {catalogState.phase === "error"
                ? catalogState.message
                : catalogState.phase === "unavailable"
                  ? "人设与回复偏好仍可保存；登录后可以为每个 Anima 单独选择服务。"
                  : "只会载入当前服务器实际启用的能力。"}
            </span>
          </div>
        )}
      </section>

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

function ProviderCard({
  capability,
  catalog,
  settings,
  disabled,
  onProvider,
  onOption,
  onDisabled,
}: {
  capability: ProviderCapability;
  catalog: ProviderCatalog;
  settings: AnimaSettings;
  disabled: boolean;
  onProvider: (capability: ProviderCapability, provider: PublicProvider) => void;
  onOption: (
    capability: ProviderCapability,
    field: "model" | "voice",
    value: string,
  ) => void;
  onDisabled: (capability: "asr" | "vision") => void;
}) {
  const copy = CAPABILITY_COPY[capability];
  const providers = catalogProviders(catalog, capability);
  const selection = settings.providers[capability];
  const selected = providers.find((provider) => provider.alias === selection.alias);
  const canDisable = capability === "asr" || capability === "vision";
  return (
    <fieldset
      class="provider-card"
      disabled={disabled || (providers.length === 0 && !canDisable)}
    >
      <legend class="sr-only">{copy.label}服务</legend>
      <div class="provider-card__header">
        <span>{copy.code}</span>
        <div><strong>{copy.label}</strong><small>{copy.description}</small></div>
        {selected && (
          <i class={`provider-locality provider-locality--${selected.locality}`}>
            {selected.locality === "cloud" ? "云端" : "本地"}
            {selected.streaming ? " · 流式" : ""}
          </i>
        )}
      </div>

      <label class="settings-field settings-field--compact">
        <span>服务别名</span>
        <select
          value={selection.alias === "disabled" ? "disabled" : (selected?.alias ?? "")}
          onChange={(event) => {
            if (event.currentTarget.value === "disabled" && canDisable) {
              onDisabled(capability);
              return;
            }
            const provider = providers.find(
              (item) => item.alias === event.currentTarget.value,
            );
            if (provider) onProvider(capability, provider);
          }}
          aria-label={`${copy.label}服务别名`}
        >
          {!selected && <option value="">请选择已启用服务</option>}
          {canDisable && <option value="disabled">关闭此能力</option>}
          {providers.map((provider) => (
            <option value={provider.alias} key={provider.alias}>{provider.alias}</option>
          ))}
        </select>
      </label>

      {selected && selected.models.length > 0 && (
        <label class="settings-field settings-field--compact">
          <span>模型</span>
          <select
            value={selected.models.includes(selection.model) ? selection.model : ""}
            onChange={(event) => onOption(capability, "model", event.currentTarget.value)}
            aria-label={`${copy.label}模型`}
          >
            {!selected.models.includes(selection.model) && (
              <option value="">请选择模型</option>
            )}
            {selected.models.map((model) => <option value={model} key={model}>{model}</option>)}
          </select>
        </label>
      )}

      {selected && capability === "tts" && selected.voices.length > 0 && (
        <label class="settings-field settings-field--compact">
          <span>音色</span>
          <select
            value={selected.voices.includes(selection.voice) ? selection.voice : ""}
            onChange={(event) => onOption(capability, "voice", event.currentTarget.value)}
            aria-label="TTS 音色"
          >
            {!selected.voices.includes(selection.voice) && (
              <option value="">请选择音色</option>
            )}
            {selected.voices.map((voice) => <option value={voice} key={voice}>{voice}</option>)}
          </select>
        </label>
      )}

      {providers.length === 0 && (
        <p class="provider-card__empty">
          {canDisable ? "服务器暂未启用此能力；当前保持关闭。" : "服务器暂未启用此能力。"}
        </p>
      )}
    </fieldset>
  );
}
