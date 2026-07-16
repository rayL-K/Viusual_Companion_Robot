import { useEffect } from "preact/hooks";

import { NAV_ITEMS, type SectionId } from "../site-config";
import { Brand } from "./Brand";

type SiteHeaderProps = {
  menuOpen: boolean;
  setMenuOpen: (open: boolean | ((current: boolean) => boolean)) => void;
  jumpTo: (id: SectionId) => void;
};

export function SiteHeader({ menuOpen, setMenuOpen, jumpTo }: SiteHeaderProps) {
  useEffect(() => {
    if (!menuOpen) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setMenuOpen(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [menuOpen, setMenuOpen]);

  return (
    <header class="site-header">
      <a class="brand-link" href="#top" aria-label="VeyraLux 微睿霖光首页" onClick={(event) => {
        event.preventDefault();
        jumpTo("top");
      }}>
        <Brand />
      </a>

      <nav id="primary-navigation" class={`nav ${menuOpen ? "nav--open" : ""}`} aria-label="主要导航">
        {NAV_ITEMS.map((item) => (
          <a href={`#${item.id}`} onClick={(event) => {
            event.preventDefault();
            jumpTo(item.id);
          }}>{item.label}</a>
        ))}
      </nav>

      <div class="site-header__actions">
        <a class="header-entry" href="#products" onClick={(event) => {
          event.preventDefault();
          jumpTo("products");
        }}>
          Anima v0.0.1 <span aria-hidden="true">↓</span>
        </a>
        <button
          class="menu-toggle"
          type="button"
          aria-label={menuOpen ? "关闭导航" : "打开导航"}
          aria-expanded={menuOpen}
          aria-controls="primary-navigation"
          onClick={() => setMenuOpen((value) => !value)}
        >
          <span /><span />
        </button>
      </div>
    </header>
  );
}
