import { SignalPresence } from "../components/SignalPresence";
import type { SectionId } from "../site-config";

export function Hero({ jumpTo }: { jumpTo: (id: SectionId) => void }) {
  return (
    <section class="hero" id="top" aria-labelledby="hero-title">
      <div class="hero__aura hero__aura--rose" aria-hidden="true" data-motion-layer="hero-aura" data-motion-behavior="scrub" data-motion-scope="hero" />
      <div class="hero__aura hero__aura--violet" aria-hidden="true" />
      <div class="hero__content" data-motion-layer="hero-copy" data-motion-behavior="scrub" data-motion-scope="hero">
        <p class="hero__brandline">VeyraLux 微睿霖光 · 多模态虚拟陪伴</p>
        <h1 id="hero-title" class="hero__title">
          <span class="hero__line"><span>让陪伴</span></span>
          <span class="hero__line hero__line--accent"><span>不再等待。</span></span>
        </h1>
        <p class="hero__support">
          让视觉、声音、记忆与角色动作在同一条低时延链路上汇合。以 RK3588 为端侧核心，
          让每一次回应更及时，也更懂此刻的你。
        </p>
        <div class="hero__actions">
          <a
            class="button button--primary"
            href="#products"
            onClick={(event) => {
              event.preventDefault();
              jumpTo("products");
            }}
          >
            认识 Anima · v0.0.1 <span aria-hidden="true">↓</span>
          </a>
          <a class="button button--quiet" href="#pipeline" onClick={(event) => {
            event.preventDefault();
            jumpTo("pipeline");
          }}>
            查看实时链路 <span aria-hidden="true">↓</span>
          </a>
        </div>
        <div class="hero__proof" aria-label="系统特征">
          <span>端侧推理</span><i aria-hidden="true" /><span>实时上下文</span><i aria-hidden="true" /><span>跨端访问</span>
        </div>
      </div>

      <SignalPresence />
      <a class="chapter-next" href="#vision" onClick={(event) => {
        event.preventDefault();
        jumpTo("vision");
      }}>
        <span>向下了解系统</span><i aria-hidden="true" />
      </a>
    </section>
  );
}
