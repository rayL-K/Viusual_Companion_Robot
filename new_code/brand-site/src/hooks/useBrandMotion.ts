import type { RefObject } from "preact";
import { useCallback, useEffect } from "preact/hooks";
import gsap from "gsap";
import { ScrollToPlugin } from "gsap/ScrollToPlugin";
import { ScrollTrigger } from "gsap/ScrollTrigger";

import type { SectionId } from "../site-config";

interface NetworkInformationLike extends EventTarget {
  readonly saveData?: boolean;
}

type NavigatorWithConnection = Navigator & {
  readonly connection?: NetworkInformationLike;
};

const clamp = (value: number, minimum: number, maximum: number) =>
  Math.min(maximum, Math.max(minimum, value));

export function useBrandMotion(rootRef: RefObject<HTMLDivElement>, beforeJump: () => void) {
  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;

    gsap.registerPlugin(ScrollTrigger, ScrollToPlugin);
    const media = gsap.matchMedia();
    const connection = (navigator as NavigatorWithConnection).connection;
    let saveData = connection?.saveData === true;
    root.classList.toggle("is-data-saver", saveData);
    const context = gsap.context(() => {
      media.add("(prefers-reduced-motion: no-preference)", () => {
        const intro = gsap.timeline({ defaults: { ease: "expo.out" } });
        intro
          .from(".site-header", { y: -24, autoAlpha: 0, duration: 0.7 })
          .from(".hero__signal", { scale: 0.72, autoAlpha: 0, duration: 1.25 }, 0.08)
          .from(".hero__line > *", { yPercent: 110, duration: 1.05, stagger: 0.1 }, 0.18)
          .from(".hero__support, .hero__actions, .hero__proof", {
            y: 22,
            autoAlpha: 0,
            duration: 0.8,
            stagger: 0.1,
          }, 0.52);
        if (saveData) intro.progress(1);

        gsap.timeline({
          scrollTrigger: {
            trigger: root,
            start: "top top",
            end: "bottom bottom",
            scrub: 0.8,
          },
        })
          .to(".ambient-stage__wash--rose", { xPercent: 18, yPercent: 38, scale: 1.18, ease: "none" }, 0)
          .to(".ambient-stage__wash--violet", { xPercent: -22, yPercent: -32, scale: 0.86, ease: "none" }, 0)
          .to(".ambient-stage__wash--mint", { xPercent: 14, yPercent: -48, scale: 1.12, ease: "none" }, 0);
      });

      media.add("(min-width: 50.01rem) and (prefers-reduced-motion: no-preference)", () => {
        gsap.timeline({
          scrollTrigger: {
            trigger: ".hero",
            start: "top top",
            end: "bottom top",
            scrub: 0.9,
          },
        })
          .to(".hero__signal", { yPercent: 24, rotate: 8, scale: 0.9, ease: "none" }, 0)
          .to(".hero__content", { yPercent: 12, autoAlpha: 0.48, ease: "none" }, 0)
          .to(".hero__aura--rose", { xPercent: 14, yPercent: 36, ease: "none" }, 0);

        gsap.timeline({
          scrollTrigger: {
            trigger: ".manifesto",
            start: "top 82%",
            end: "bottom 28%",
            scrub: 0.55,
          },
        })
          .fromTo(".manifesto__index i", { scaleY: 0 }, { scaleY: 1, ease: "none", duration: 0.75 }, 0)
          .fromTo(".manifesto__copy", { y: 70 }, { y: -28, ease: "none", duration: 1 }, 0)
          .fromTo(".presence-stream li", { x: 58, autoAlpha: 0.22 }, {
            x: 0,
            autoAlpha: 1,
            duration: 0.55,
            stagger: 0.11,
            ease: "power2.out",
          }, 0.13);

        const pipelineStages = gsap.utils.toArray<HTMLElement>(".signal-flow__stage");
        const setActiveStage = (progress: number) => {
          const activeIndex = clamp(Math.floor(progress * pipelineStages.length), 0, pipelineStages.length - 1);
          pipelineStages.forEach((stage, index) => stage.classList.toggle("is-active", index === activeIndex));
        };
        const pipelineTimeline = gsap.timeline({
          scrollTrigger: {
            trigger: ".pipeline",
            start: "top top",
            end: "bottom bottom",
            scrub: 0.4,
            onUpdate: ({ progress }) => setActiveStage(progress),
          },
        });
        pipelineTimeline.fromTo(".signal-flow__progress", { scaleY: 0 }, {
          scaleY: 1,
          duration: 1,
          ease: "none",
        }, 0);
        pipelineStages.forEach((stage, index) => {
          const position = index / Math.max(pipelineStages.length - 1, 1) * 0.82;
          pipelineTimeline.fromTo(stage, { x: 44, autoAlpha: 0.26 }, {
            x: 0,
            autoAlpha: 1,
            duration: 0.18,
            ease: "power2.out",
          }, position);
        });

        gsap.timeline({
          scrollTrigger: {
            trigger: ".architecture",
            start: "top 78%",
            end: "bottom 24%",
            scrub: 0.65,
          },
        })
          .fromTo(".architecture__copy", { y: 90 }, { y: -30, ease: "none" }, 0)
          .fromTo(".board-figure__frame", { clipPath: "inset(16% 12% 16% 12% round 9rem)" }, {
            clipPath: "inset(0% 0% 0% 0% round 1.4rem)",
            ease: "none",
          }, 0)
          .fromTo(".board-figure__image", { scale: 1.14, yPercent: -4, rotate: -1.6 }, {
            scale: 1.01,
            yPercent: 4,
            rotate: 0,
            ease: "none",
          }, 0);

        gsap.timeline({
          scrollTrigger: {
            trigger: ".products",
            start: "top 76%",
            end: "bottom 22%",
            scrub: 0.7,
          },
        })
          .fromTo(".release-core", { xPercent: -9, y: 75, rotate: -1.2 }, {
            xPercent: 0,
            y: -28,
            rotate: 0,
            ease: "none",
          }, 0)
          .fromTo(".release-signal", { scaleX: 0, autoAlpha: 0 }, {
            scaleX: 1,
            autoAlpha: 1,
            ease: "none",
          }, 0.16)
          .fromTo(".release-notes", { xPercent: 9, y: 135 }, {
            xPercent: 0,
            y: 20,
            ease: "none",
          }, 0.22)
          .fromTo(".product-visual", { clipPath: "inset(12% 8% 12% 8% round 4rem)", scale: 0.96 }, {
            clipPath: "inset(0% 0% 0% 0% round 1rem)",
            scale: 1,
            ease: "none",
          }, 0.38);

        gsap.timeline({
          scrollTrigger: {
            trigger: ".closing",
            start: "top bottom",
            end: "bottom bottom",
            scrub: 0.75,
          },
        })
          .fromTo(".closing__orbit", { scale: 0.58, rotate: -34, autoAlpha: 0.2 }, {
            scale: 1,
            rotate: 0,
            autoAlpha: 1,
            ease: "none",
          }, 0)
          .fromTo(".closing__content", { y: 76, autoAlpha: 0.2 }, {
            y: 0,
            autoAlpha: 1,
            ease: "power2.out",
          }, 0.25);
      });

      media.add("(max-width: 50rem) and (prefers-reduced-motion: no-preference)", () => {
        gsap.utils.toArray<HTMLElement>("[data-motion]").forEach((element) => {
          gsap.fromTo(element, { y: 28, autoAlpha: 0.66 }, {
            y: 0,
            autoAlpha: 1,
            duration: 0.72,
            ease: "power3.out",
            scrollTrigger: { trigger: element, start: "top 88%", once: true },
          });
        });

        gsap.fromTo(".signal-flow__progress", { scaleY: 0 }, {
          scaleY: 1,
          ease: "none",
          scrollTrigger: {
            trigger: ".signal-flow",
            start: "top 82%",
            end: "bottom 42%",
            scrub: 0.55,
          },
        });
      });
    }, root);

    const localTriggers = ScrollTrigger.getAll().filter((trigger) => {
      const element = trigger.trigger;
      return element instanceof Element && (element === root || root.contains(element));
    });
    const syncDataPreference = () => {
      saveData = connection?.saveData === true;
      root.classList.toggle("is-data-saver", saveData);
      localTriggers.forEach((trigger) => {
        if (saveData) trigger.disable(false, true);
        else trigger.enable(false, true);
      });
      if (!saveData) ScrollTrigger.refresh();
    };
    syncDataPreference();
    connection?.addEventListener("change", syncDataPreference);

    let frame = 0;
    let disposed = false;
    const updateProgress = () => {
      frame = 0;
      const max = Math.max(document.documentElement.scrollHeight - window.innerHeight, 1);
      const progress = clamp(window.scrollY / max, 0, 1);
      root.style.setProperty("--page-progress", String(progress));
      root.style.setProperty("--spine-y", `${8 + progress * 84}%`);
    };
    const onScroll = () => {
      if (!frame) frame = window.requestAnimationFrame(updateProgress);
    };
    const onVisibilityChange = () => {
      root.classList.toggle("is-page-hidden", document.visibilityState !== "visible");
    };

    updateProgress();
    onVisibilityChange();
    window.addEventListener("scroll", onScroll, { passive: true });
    document.addEventListener("visibilitychange", onVisibilityChange);

    void document.fonts?.ready.then(() => {
      if (!disposed) ScrollTrigger.refresh();
    });

    return () => {
      disposed = true;
      window.removeEventListener("scroll", onScroll);
      document.removeEventListener("visibilitychange", onVisibilityChange);
      connection?.removeEventListener("change", syncDataPreference);
      if (frame) window.cancelAnimationFrame(frame);
      root.classList.remove("is-data-saver", "is-page-hidden");
      media.revert();
      context.revert();
    };
  }, [rootRef]);

  const jumpTo = useCallback((id: SectionId) => {
    beforeJump();
    const target = document.getElementById(id);
    if (!target) return;

    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const nextHash = `#${id}`;
    if (window.location.hash !== nextHash) window.history.pushState(null, "", nextHash);

    if (reduced) {
      target.scrollIntoView({ behavior: "auto", block: "start" });
      return;
    }

    gsap.registerPlugin(ScrollToPlugin);
    const distance = Math.abs(target.getBoundingClientRect().top);
    const duration = clamp(distance / Math.max(window.innerHeight * 2.4, 1), 0.48, 0.92);
    gsap.fromTo(".jump-transition", { scaleX: 0, opacity: 0.8 }, {
      scaleX: 1,
      opacity: 0,
      duration: 0.64,
      ease: "expo.out",
      overwrite: true,
    });
    gsap.to(window, {
      duration,
      ease: "power3.inOut",
      overwrite: "auto",
      scrollTo: {
        y: target,
        offsetY: (document.querySelector<HTMLElement>(".site-header")?.getBoundingClientRect().height ?? 0) + 8,
        autoKill: true,
      },
    });
  }, [beforeJump]);

  return { jumpTo };
}
