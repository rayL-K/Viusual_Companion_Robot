import { ExternalLink } from "../components/ExternalLink";
import { SITE_LINKS, type SectionId } from "../site-config";

export function Closing({ jumpTo }: { jumpTo: (id: SectionId) => void }) {
  return (
    <section class="closing section" aria-labelledby="closing-title">
      <div class="closing__orbit" aria-hidden="true" data-motion-layer="closing-orbit" data-motion-behavior="scrub" data-motion-scope="closing"><i /><i /><i /></div>
      <div class="closing__content" data-motion="closing-content" data-motion-layer="closing-copy" data-motion-behavior="scrub" data-motion-scope="closing">
        <p>VeyraLux 微睿霖光</p>
        <h2 id="closing-title">让机器理解世界，<br />让陪伴及时抵达。</h2>
        <div class="closing__actions">
          <a
            class="button button--light"
            href="#products"
            onClick={(event) => {
              event.preventDefault();
              jumpTo("products");
            }}
          >
            了解 Anima v0.0.1 <span aria-hidden="true">↑</span>
          </a>
          <ExternalLink class="button button--outline-light" href={SITE_LINKS.github}>
            查看 GitHub <span aria-hidden="true">↗</span>
          </ExternalLink>
        </div>
      </div>
    </section>
  );
}
