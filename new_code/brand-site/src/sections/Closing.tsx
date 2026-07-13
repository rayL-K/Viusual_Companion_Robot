import { ExternalLink } from "../components/ExternalLink";
import { SITE_LINKS } from "../site-config";

export function Closing() {
  return (
    <section class="closing section" aria-labelledby="closing-title">
      <div class="closing__orbit" aria-hidden="true"><i /><i /><i /></div>
      <div class="closing__content" data-reveal>
        <p>VeyraLux 微睿霖光</p>
        <h2 id="closing-title">让机器理解世界，<br />让陪伴及时抵达。</h2>
        <div class="closing__actions">
          <ExternalLink
            class="button button--light"
            href={SITE_LINKS.v1}
            ariaLabel="现在进入 V1，打开新窗口"
          >
            现在进入 V1 <span aria-hidden="true">↗</span>
          </ExternalLink>
          <ExternalLink class="button button--outline-light" href={SITE_LINKS.github}>
            查看 GitHub <span aria-hidden="true">↗</span>
          </ExternalLink>
        </div>
      </div>
    </section>
  );
}
