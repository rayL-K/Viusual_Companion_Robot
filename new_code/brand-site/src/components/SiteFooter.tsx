import { SITE_LINKS } from "../site-config";
import { Brand } from "./Brand";
import { ExternalLink } from "./ExternalLink";

export function SiteFooter() {
  return (
    <footer class="site-footer">
      <Brand footer />
      <div class="site-footer__about">
        <p>基于 RK3588 的低时延多模态虚拟陪伴系统</p>
        <small>团队：王文康 · 夏鑫祥</small>
      </div>
      <div class="site-footer__links">
        <a href="#products">Anima / v0.0.1</a>
        <ExternalLink href={SITE_LINKS.github}>GitHub</ExternalLink>
        <a href="/THIRD_PARTY_NOTICES.txt">第三方许可</a>
      </div>
    </footer>
  );
}
