import { useRef, useState } from "preact/hooks";

import { SiteFooter } from "./components/SiteFooter";
import { SiteHeader } from "./components/SiteHeader";
import { useBrandMotion } from "./hooks/useBrandMotion";
import { Architecture } from "./sections/Architecture";
import { Closing } from "./sections/Closing";
import { Hero } from "./sections/Hero";
import { Manifesto } from "./sections/Manifesto";
import { Pipeline } from "./sections/Pipeline";
import { Products } from "./sections/Products";

export function App() {
  const rootRef = useRef<HTMLDivElement>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const { jumpTo } = useBrandMotion(rootRef, () => setMenuOpen(false));

  return (
    <div class="site" ref={rootRef}>
      <a class="skip-link" href="#main-content">跳到主要内容</a>
      <div class="scroll-progress" aria-hidden="true"><span /></div>
      <div class="jump-transition" aria-hidden="true" />

      <SiteHeader menuOpen={menuOpen} setMenuOpen={setMenuOpen} jumpTo={jumpTo} />

      <main id="main-content">
        <Hero jumpTo={jumpTo} />
        <Manifesto />
        <Pipeline />
        <Architecture />
        <Products />
        <Closing />
      </main>

      <SiteFooter />
    </div>
  );
}
