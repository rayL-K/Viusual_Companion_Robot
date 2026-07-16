import { useRef, useState } from "preact/hooks";

import { LivingField } from "./components/LivingField";
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
      <LivingField className="living-field" />
      <div class="ambient-stage" aria-hidden="true">
        <span class="ambient-stage__wash ambient-stage__wash--rose" data-motion-layer="wash-rose" data-motion-behavior="scrub" data-motion-scope="global" />
        <span class="ambient-stage__wash ambient-stage__wash--violet" data-motion-layer="wash-violet" data-motion-behavior="scrub" data-motion-scope="global" />
        <span class="ambient-stage__wash ambient-stage__wash--mint" data-motion-layer="wash-mint" data-motion-behavior="scrub" data-motion-scope="global" />
      </div>
      <div class="signal-spine" aria-hidden="true" data-motion-layer="signal-spine" data-motion-behavior="scroll-progress" data-motion-scope="global">
        <span class="signal-spine__track" />
        <span class="signal-spine__progress" />
        <span class="signal-spine__pulse" />
      </div>
      <div class="scroll-progress" aria-hidden="true"><span /></div>
      <div class="jump-transition" aria-hidden="true" />

      <SiteHeader menuOpen={menuOpen} setMenuOpen={setMenuOpen} jumpTo={jumpTo} />

      <main id="main-content" class="continuous-story">
        <Hero jumpTo={jumpTo} />
        <Manifesto />
        <Pipeline />
        <Architecture />
        <Products />
        <Closing jumpTo={jumpTo} />
      </main>

      <SiteFooter />
    </div>
  );
}
