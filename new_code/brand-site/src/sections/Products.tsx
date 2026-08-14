import { ExternalLink } from "../components/ExternalLink";
import { ANIMA_PUBLIC, SITE_LINKS } from "../site-config";

const capabilities = [
  ["01", "低时延会话", "以可取消的事件流衔接语音、理解与回应"],
  ["02", "Provider 边界", "ASR、LLM 与 TTS 可按质量、时延和成本替换"],
  ["03", "隔离上下文", "按用户与 Anima 分离配置、记忆和会话数据"],
] as const;

export function Products() {
  return (
    <section class="products section" id="products" aria-labelledby="products-title">
      <header class="section-heading section-heading--wide" data-motion="products-heading">
        <p>ANIMA / v0.0.1</p>
        <h2 id="products-title">让连续感知，成为一条真正运行的主链路。</h2>
      </header>

      <div class="anima-release">
        <article
          class="release-core"
          data-motion-layer="release-core"
          data-motion-behavior="scrub"
          data-motion-scope="products"
        >
          <div class="release-core__topline"><span>ANIMA · v0.0.1</span><span class="status">当前迭代</span></div>
          <div class="release-core__copy">
            <p>低时延多模态虚拟陪伴</p>
            <h3>不只生成回答，<br />而是理解一个正在发生的瞬间。</h3>
          </div>
          {ANIMA_PUBLIC ? (
            <ExternalLink class="release-core__link" href={SITE_LINKS.anima}>
              进入 Anima <span aria-hidden="true">↗</span>
            </ExternalLink>
          ) : (
            <div class="release-core__link release-core__link--disabled" aria-label="Anima v0.0.1 尚未公开">
              <span>anima.veyralux.org</span><strong>完成生产门禁后开放</strong>
            </div>
          )}
        </article>

        <aside
          class="release-notes"
          data-motion-layer="release-notes"
          data-motion-behavior="scrub"
          data-motion-scope="products"
          aria-label="Anima v0.0.1 核心能力"
        >
          <p>VERSION 0.0.1</p>
          <h3>从可验证的服务端主链路开始，逐步接近“持续在场”。</h3>
          <dl>
            {capabilities.map(([index, name, detail]) => (
              <div>
                <dt><span>{index}</span>{name}</dt>
                <dd>{detail}</dd>
              </div>
            ))}
          </dl>
        </aside>

        <div class="release-signal" aria-hidden="true" data-motion-layer="release-signal" data-motion-behavior="scrub" data-motion-scope="products">
          <i /><span>感知</span><i /><span>理解</span><i /><span>回应</span><i />
        </div>
      </div>

      <figure class="product-visual" data-motion="product-visual" data-motion-layer="product-reveal" data-motion-behavior="scrub" data-motion-scope="products">
        <img
          src="/images/anima-console.webp"
          alt="Anima v0.0.1 桌面端交互界面开发预览"
          width="1440"
          height="900"
          loading="lazy"
        />
        <figcaption>
          <strong>ANIMA / v0.0.1 · 开发预览</strong>
          <span>围绕低时延会话、隔离记忆与可替换 Provider 构建</span>
        </figcaption>
      </figure>
    </section>
  );
}
