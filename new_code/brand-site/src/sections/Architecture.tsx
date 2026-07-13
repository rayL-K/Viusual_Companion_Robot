export function Architecture() {
  return (
    <section class="architecture section" id="architecture" aria-labelledby="architecture-title">
      <div class="architecture__copy" data-reveal>
        <p class="chapter-label">RK3588 · EDGE CORE</p>
        <h2 id="architecture-title">算力留在身边，<br />连接延伸到远方。</h2>
        <p class="architecture__lead">
          已运行的 V1 链路由 ELF 2 开发板承载视觉、离线语音与服务编排，浏览器负责采集和呈现；
          Cloudflare 提供公网接入、路由、边缘缓存与链路保护。V2 将在完成实机门禁后继续扩展记忆与事件流能力。
        </p>

        <dl class="architecture-list">
          <div>
            <dt>ELF 2 / RK3588</dt>
            <dd>已验证 V1 的视觉、离线语音与运行编排</dd>
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

      <figure class="board-figure" data-reveal>
        <div class="board-figure__frame">
          <img
            class="board-figure__image"
            src="/images/elf2-board.webp"
            alt="运行 VeyraLux V1 端侧服务的 ELF 2 RK3588 开发板实物"
            width="1080"
            height="1440"
            loading="lazy"
          />
        </div>
        <figcaption>
          <span>边缘核心 / ELF 2</span>
          <span>视觉 · 语音 · 服务编排</span>
        </figcaption>
      </figure>
    </section>
  );
}
