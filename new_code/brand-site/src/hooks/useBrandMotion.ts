import type { RefObject } from "preact";
import { useCallback, useEffect } from "preact/hooks";
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";

import type { SectionId } from "../site-config";

export function useBrandMotion(rootRef: RefObject<HTMLDivElement>, beforeJump: () => void) {
  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;

    gsap.registerPlugin(ScrollTrigger);
    const media = gsap.matchMedia();
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

        gsap.utils.toArray<HTMLElement>("[data-reveal]").forEach((element) => {
          gsap.fromTo(element, { y: 42, autoAlpha: 0.72 }, {
            y: 0,
            autoAlpha: 1,
            duration: 0.95,
            ease: "expo.out",
            scrollTrigger: {
              trigger: element,
              start: "top 84%",
              toggleActions: "play none none reverse",
            },
          });
        });

        gsap.from(".version-panel", {
          x: (index) => index === 0 ? -54 : 54,
          autoAlpha: 0.74,
          duration: 1.05,
          stagger: 0.12,
          ease: "expo.out",
          scrollTrigger: { trigger: ".versions", start: "top 72%" },
        });
      });

      media.add("(min-width: 50.01rem) and (prefers-reduced-motion: no-preference)", () => {
        gsap.to(".hero__signal", {
          yPercent: 20,
          rotate: 9,
          ease: "none",
          scrollTrigger: {
            trigger: ".hero",
            start: "top top",
            end: "bottom top",
            scrub: 1.1,
          },
        });

        gsap.to(".hero__aura--rose", {
          xPercent: 12,
          yPercent: 30,
          ease: "none",
          scrollTrigger: {
            trigger: ".hero",
            start: "top top",
            end: "bottom top",
            scrub: 1.4,
          },
        });

        gsap.fromTo(".signal-flow__progress", { scaleX: 0 }, {
          scaleX: 1,
          ease: "none",
          scrollTrigger: {
            trigger: ".signal-flow",
            start: "top 68%",
            end: "bottom 54%",
            scrub: 0.7,
          },
        });

        gsap.utils.toArray<HTMLElement>(".signal-flow__stage").forEach((stage) => {
          gsap.fromTo(stage, { opacity: 0.45 }, {
            opacity: 1,
            scrollTrigger: {
              trigger: stage,
              start: "top 70%",
              end: "bottom 42%",
              scrub: true,
              toggleClass: { targets: stage, className: "is-active" },
            },
          });
        });

        gsap.fromTo(".board-figure__image", { scale: 1.08, yPercent: -3 }, {
          scale: 1,
          yPercent: 4,
          ease: "none",
          scrollTrigger: {
            trigger: ".board-figure",
            start: "top bottom",
            end: "bottom top",
            scrub: 1.2,
          },
        });
      });
    }, root);

    let frame = 0;
    const updateProgress = () => {
      frame = 0;
      const max = Math.max(document.documentElement.scrollHeight - window.innerHeight, 1);
      root.style.setProperty("--page-progress", String(Math.min(window.scrollY / max, 1)));
    };
    const onScroll = () => {
      if (!frame) frame = window.requestAnimationFrame(updateProgress);
    };
    updateProgress();
    window.addEventListener("scroll", onScroll, { passive: true });

    return () => {
      window.removeEventListener("scroll", onScroll);
      if (frame) window.cancelAnimationFrame(frame);
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
    if (window.location.hash !== nextHash) {
      window.history.pushState(null, "", nextHash);
    }

    if (!reduced) {
      gsap.fromTo(".jump-transition", { scaleX: 0, opacity: 0.8 }, {
        scaleX: 1,
        opacity: 0,
        duration: 0.64,
        ease: "expo.out",
        overwrite: true,
      });
    }
    target.scrollIntoView({ behavior: reduced ? "auto" : "smooth", block: "start" });
  }, [beforeJump]);

  return { jumpTo };
}
