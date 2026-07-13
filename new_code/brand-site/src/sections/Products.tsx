import { ExternalLink } from "../components/ExternalLink";
import { SITE_LINKS, V2_PUBLIC } from "../site-config";

export function Products() {
  return (
    <section class="products section" id="products" aria-labelledby="products-title">
      <header class="section-heading section-heading--wide" data-reveal>
        <p>同一愿景，两代实践</p>
        <h2 id="products-title">从可用的陪伴，到真正连续的在场。</h2>
      </header>

      <div class="versions">
        <article class="version-panel version-panel--v1">
          <div class="version-panel__topline"><span>V1</span><span class="status">公开演示</span></div>
          <div>
            <p>草莓兔兔</p>
            <h3>已经连通的端侧多模态陪伴。</h3>
            <ul>
              <li>RK3588 本地视觉、ASR 与 TTS</li>
              <li>Live2D 表情、动作与唇形反馈</li>
              <li>PC / 移动端公网直接访问</li>
            </ul>
          </div>
          <ExternalLink
            class="version-panel__link"
            href={SITE_LINKS.v1}
            ariaLabel="进入 V1 草莓兔兔，打开新窗口"
          >
            进入 V1 <span aria-hidden="true">↗</span>
          </ExternalLink>
        </article>

        <article class="version-panel version-panel--v2">
          <div class="version-panel__topline"><span>V2 · ANIMA</span><span class="status">持续研发</span></div>
          <div>
            <p>下一代交互架构</p>
            <h3>让视觉、记忆与角色行为成为一条事件流。</h3>
            <ul>
              <li>目标：全双工会话与可中断交互</li>
              <li>目标：连续视觉语义与人物上下文</li>
              <li>目标：模块化能力与多用户隔离</li>
            </ul>
          </div>
          {V2_PUBLIC ? (
            <ExternalLink class="version-panel__link" href={SITE_LINKS.v2}>
              探索 V2 <span aria-hidden="true">↗</span>
            </ExternalLink>
          ) : (
            <div class="version-panel__link version-panel__link--disabled" aria-label="Anima V2 尚未公开">
              <span>anima.veyralux.org</span><strong>完成实机门禁后开放</strong>
            </div>
          )}
        </article>
      </div>

      <figure class="product-visual" data-reveal>
        <img
          src="/images/anima-console.webp"
          alt="Anima V2 桌面端交互界面开发预览"
          width="1440"
          height="900"
          loading="lazy"
        />
        <figcaption>
          <strong>ANIMA / V2 · 开发预览</strong>
          <span>以“在场”为核心重构的下一代交互面，暂未公开上线</span>
        </figcaption>
      </figure>
    </section>
  );
}
