export function Architecture() {
  return (
    <section class="architecture section" id="architecture" aria-labelledby="architecture-title">
      <div class="architecture__halo" aria-hidden="true" />
      <div class="architecture__copy" data-motion="architecture-copy" data-motion-layer="architecture-copy" data-motion-behavior="scrub" data-motion-scope="architecture">
        <p class="chapter-label">RK3588 · EDGE CORE</p>
        <h2 id="architecture-title">算力留在身边，<br />连接延伸到远方。</h2>
        <p class="architecture__lead">
          Anima v0.0.1 由 ELF 2 开发板承载视觉、离线语音与服务编排，浏览器负责采集和呈现；
          Cloudflare 提供公网接入、路由、边缘缓存与链路保护，并为后续的记忆与事件流能力保留清晰边界。
        </p>

        <dl class="architecture-list">
          <div>
            <dt>ELF 2 / RK3588</dt>
            <dd>承载视觉、离线语音与运行编排</dd>
          </div>
          <div>
            <dt>Cloudflare Edge</dt>
            <dd>HTTPS / WSS 接入、路由隔离与静态资源分发</dd>
          </div>
          <div>
            <dt>Web Presence</dt>
            <dd>PC 与移动端共享同一套角色交互入口</dd>
          </div>
        </dl>
      </div>

      <figure class="board-figure" data-motion="board-figure" data-motion-layer="board-reveal" data-motion-behavior="scrub" data-motion-scope="architecture">
        <div class="board-figure__frame" data-motion-layer="board-mask" data-motion-behavior="scrub" data-motion-scope="architecture">
          <img
            class="board-figure__image"
            src="/images/elf2-board.webp"
            alt="运行 Anima v0.0.1 端侧服务的 ELF 2 RK3588 开发板实物"
            width="1080"
            height="1440"
            loading="lazy"
            data-motion-layer="board-image"
            data-motion-behavior="scrub"
            data-motion-scope="architecture"
          />
          <span class="board-figure__pulse board-figure__pulse--core" aria-hidden="true" />
          <span class="board-figure__pulse board-figure__pulse--edge" aria-hidden="true" />
        </div>
        <figcaption>
          <span>边缘核心 / ELF 2</span>
          <span>视觉 · 语音 · 服务编排</span>
        </figcaption>
      </figure>
    </section>
  );
}
