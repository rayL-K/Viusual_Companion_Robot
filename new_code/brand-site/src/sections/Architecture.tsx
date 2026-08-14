const runtimeNodes = [
  { className: "gateway", eyebrow: "CLIENT", label: "HTTPS / WSS Gateway" },
  { className: "speech", eyebrow: "SPEECH", label: "ASR / TTS Providers" },
  { className: "intelligence", eyebrow: "INTELLIGENCE", label: "LLM Provider" },
  { className: "context", eyebrow: "CONTEXT", label: "Memory / RAG" },
  { className: "vision", eyebrow: "VISION", label: "Provider / sidecar · 接入中" },
] as const;

export function Architecture() {
  return (
    <section class="architecture section" id="architecture" aria-labelledby="architecture-title">
      <div class="architecture__halo" aria-hidden="true" />
      <div class="architecture__copy" data-motion="architecture-copy" data-motion-layer="architecture-copy" data-motion-behavior="scrub" data-motion-scope="architecture">
        <p class="chapter-label">API-FIRST · LINUX RUNTIME</p>
        <h2 id="architecture-title">编排保持稳定，<br />能力按需生长。</h2>
        <p class="architecture__lead">
          Anima v0.0.1 将浏览器交互层、会话编排和外部能力拆开：通用 Linux Server 承载实时网关、
          记忆 / RAG 与代际控制，ASR、LLM、TTS 通过 Provider contract 接入。视觉保留同一边界，
          当前处于 Provider / sidecar 接入阶段。
        </p>

        <dl class="architecture-list">
          <div>
            <dt>Realtime Gateway</dt>
            <dd>鉴权、可取消事件流与同一代际内的有序交付</dd>
          </div>
          <div>
            <dt>Conversation Core</dt>
            <dd>组织人设、实时上下文、隔离记忆与检索结果</dd>
          </div>
          <div>
            <dt>Provider Plane</dt>
            <dd>语音与语言能力独立替换；视觉 Provider / sidecar 接入中</dd>
          </div>
          <div>
            <dt>Isolation Boundary</dt>
            <dd>用户、Anima、配置和数据拥有清晰的归属边界</dd>
          </div>
        </dl>
      </div>

      <figure
        class="runtime-map"
        aria-labelledby="runtime-map-caption"
        data-motion="runtime-map"
        data-motion-layer="runtime-reveal"
        data-motion-behavior="scrub"
        data-motion-scope="architecture"
      >
        <div class="runtime-map__frame" data-motion-layer="runtime-mask" data-motion-behavior="scrub" data-motion-scope="architecture">
          <div class="runtime-map__grid" aria-hidden="true" />
          <div class="runtime-map__topline">
            <span>ANIMA RUNTIME</span>
            <span class="runtime-map__health"><i aria-hidden="true" /> STANDARD LINUX</span>
          </div>

          <div
            class="runtime-map__topology"
            data-motion-layer="runtime-topology"
            data-motion-behavior="scrub"
            data-motion-scope="architecture"
          >
            <span class="runtime-map__orbit runtime-map__orbit--outer" aria-hidden="true" />
            <span class="runtime-map__orbit runtime-map__orbit--inner" aria-hidden="true" />
            <span class="runtime-map__axis runtime-map__axis--horizontal" aria-hidden="true" />
            <span class="runtime-map__axis runtime-map__axis--vertical" aria-hidden="true" />

            <div class="runtime-map__core">
              <small>ORCHESTRATION</small>
              <strong>Conversation Core</strong>
              <span>session · context · memory</span>
            </div>

            <ul class="runtime-map__nodes" aria-label="Anima 服务能力边界">
              {runtimeNodes.map((node) => (
                <li key={node.className} class={`runtime-map__node runtime-map__node--${node.className}`}>
                  <small>{node.eyebrow}</small>
                  <strong>{node.label}</strong>
                </li>
              ))}
            </ul>
          </div>

          <div class="runtime-map__status" aria-label="当前接口状态">
            <span><i aria-hidden="true" /> Gateway ready</span>
            <span><i aria-hidden="true" /> Provider-bound</span>
            <span class="is-pending"><i aria-hidden="true" /> Vision integrating</span>
          </div>
        </div>
        <figcaption id="runtime-map-caption">
          <span>API-first / 可迁移运行时</span>
          <span>Browser · Linux Server · Providers</span>
        </figcaption>
      </figure>
    </section>
  );
}
