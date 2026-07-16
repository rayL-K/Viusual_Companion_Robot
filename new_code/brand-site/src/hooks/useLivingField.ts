import { useEffect, useRef } from "preact/hooks";

export interface LivingFieldOptions {
  /** Overall opacity multiplier for the generated field. */
  intensity?: number;
  /** Upper bound for the canvas backing-store ratio. */
  maxDpr?: number;
}

interface Particle {
  x: number;
  y: number;
  velocityX: number;
  velocityY: number;
  radius: number;
  phase: number;
  tone: 0 | 1 | 2;
}

interface NetworkInformationLike extends EventTarget {
  readonly saveData?: boolean;
}

type NavigatorWithConnection = Navigator & {
  readonly connection?: NetworkInformationLike;
};

const PARTICLE_COLORS = [
  "rgba(255, 135, 196, 0.76)",
  "rgba(132, 244, 207, 0.68)",
  "rgba(176, 143, 255, 0.64)",
] as const;

const clamp = (value: number, min: number, max: number) =>
  Math.min(max, Math.max(min, value));

function createRandom(seed: number) {
  let value = seed >>> 0;
  return () => {
    value = (Math.imul(value, 1_664_525) + 1_013_904_223) >>> 0;
    return value / 4_294_967_296;
  };
}

function makeParticles(count: number) {
  const random = createRandom(0x564c_2026);
  return Array.from<unknown, Particle>({ length: count }, (_, index) => ({
    x: random(),
    y: random(),
    velocityX: (random() - 0.5) * 0.009,
    velocityY: 0.008 + random() * 0.015,
    radius: 0.7 + random() * 1.45,
    phase: random() * Math.PI * 2,
    tone: (index % 3) as Particle["tone"],
  }));
}

/**
 * Drives the site-wide, transparent canvas field. The hook deliberately owns
 * every listener and animation handle so mounting/unmounting it is safe during
 * client-side navigation and hot reloads.
 */
export function useLivingField(options: LivingFieldOptions = {}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const intensity = clamp(options.intensity ?? 1, 0, 1.5);
  const maxDpr = clamp(options.maxDpr ?? 1.75, 1, 2.5);

  useEffect(() => {
    const canvas = canvasRef.current;
    const context = canvas?.getContext("2d", { alpha: true });
    if (!canvas || !context) return;

    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
    const compactViewport = window.matchMedia("(max-width: 48rem), (pointer: coarse)");
    const connection = (navigator as NavigatorWithConnection).connection;

    let width = 1;
    let height = 1;
    let particles: Particle[] = [];
    let projected = new Float32Array(0);
    let connectionGradient: CanvasGradient | string = PARTICLE_COLORS[0];
    let streamGradients: Array<CanvasGradient | string> = [];
    let animationFrame = 0;
    let lastFrameTime = 0;
    let intersectsViewport = true;
    let saveData = connection?.saveData === true;
    let scrollProgress = 0;
    let targetScrollProgress = 0;
    let scrollEnergy = 0;
    let previousScrollY = window.scrollY;
    let pointerTargetX = width * 0.5;
    let pointerTargetY = height * 0.5;
    let pointerX = pointerTargetX;
    let pointerY = pointerTargetY;
    let pointerPresence = 0;

    const shouldAnimate = () =>
      document.visibilityState === "visible"
      && intersectsViewport
      && !reducedMotion.matches
      && !saveData;

    const updateParticleBudget = () => {
      const count = saveData ? 12 : compactViewport.matches ? 24 : 48;
      if (particles.length === count) return;
      particles = makeParticles(count);
      projected = new Float32Array(count * 2);
    };

    const rebuildGradients = () => {
      const links = context.createLinearGradient(0, 0, width, height);
      links.addColorStop(0, "rgba(255, 111, 183, 0.22)");
      links.addColorStop(0.52, "rgba(162, 135, 255, 0.16)");
      links.addColorStop(1, "rgba(123, 241, 201, 0.2)");
      connectionGradient = links;

      streamGradients = [0, 1, 2].map((index) => {
        const gradient = context.createLinearGradient(0, 0, width, 0);
        gradient.addColorStop(0, "rgba(255, 111, 183, 0)");
        gradient.addColorStop(0.24 + index * 0.08, "rgba(255, 111, 183, 0.2)");
        gradient.addColorStop(0.64, "rgba(165, 133, 255, 0.14)");
        gradient.addColorStop(1, "rgba(123, 241, 201, 0)");
        return gradient;
      });
    };

    const resize = () => {
      width = Math.max(1, window.innerWidth);
      height = Math.max(1, window.innerHeight);
      const deviceRatio = window.devicePixelRatio || 1;
      const viewportLimit = compactViewport.matches ? 1.4 : maxDpr;
      const dataLimit = saveData ? 1 : viewportLimit;
      const dpr = Math.min(deviceRatio, viewportLimit, dataLimit);
      const backingWidth = Math.round(width * dpr);
      const backingHeight = Math.round(height * dpr);

      if (canvas.width !== backingWidth || canvas.height !== backingHeight) {
        canvas.width = backingWidth;
        canvas.height = backingHeight;
      }
      context.setTransform(dpr, 0, 0, dpr, 0, 0);
      pointerTargetX = clamp(pointerTargetX, 0, width);
      pointerTargetY = clamp(pointerTargetY, 0, height);
      pointerX = clamp(pointerX, 0, width);
      pointerY = clamp(pointerY, 0, height);
      updateParticleBudget();
      rebuildGradients();
    };

    const updateScrollTarget = () => {
      const scrollRange = Math.max(
        document.documentElement.scrollHeight - window.innerHeight,
        1,
      );
      const currentScrollY = window.scrollY;
      targetScrollProgress = clamp(currentScrollY / scrollRange, 0, 1);
      scrollEnergy = clamp(
        scrollEnergy + (currentScrollY - previousScrollY) / Math.max(height, 1),
        -1.5,
        1.5,
      );
      previousScrollY = currentScrollY;
    };

    const projectParticles = (elapsed: number, deltaSeconds: number, moving: boolean) => {
      const pointerRadius = compactViewport.matches ? 100 : 165;
      const pointerRadiusSquared = pointerRadius * pointerRadius;

      particles.forEach((particle, index) => {
        if (moving) {
          particle.x += particle.velocityX * deltaSeconds + scrollEnergy * 0.0004;
          particle.y += (particle.velocityY + scrollEnergy * 0.018) * deltaSeconds;
          if (particle.x < -0.04) particle.x += 1.08;
          if (particle.x > 1.04) particle.x -= 1.08;
          if (particle.y > 1.05) particle.y -= 1.1;
          if (particle.y < -0.05) particle.y += 1.1;
        }

        let x = particle.x * width
          + Math.sin(elapsed * 0.00024 + particle.phase) * (5 + particle.radius * 2);
        let y = particle.y * height
          + Math.cos(elapsed * 0.00019 + particle.phase) * (4 + particle.radius * 2)
          + (scrollProgress - 0.5) * (index % 2 === 0 ? 18 : -14);

        const dx = x - pointerX;
        const dy = y - pointerY;
        const distanceSquared = dx * dx + dy * dy;
        if (pointerPresence > 0.01 && distanceSquared < pointerRadiusSquared) {
          const distance = Math.sqrt(Math.max(distanceSquared, 0.001));
          const influence = (1 - distance / pointerRadius) * pointerPresence;
          x += (dx / distance) * influence * 12;
          y += (dy / distance) * influence * 12;
        }

        projected[index * 2] = x;
        projected[index * 2 + 1] = y;
      });
    };

    const drawStreams = (elapsed: number) => {
      const samples = compactViewport.matches ? 18 : 30;
      streamGradients.forEach((gradient, streamIndex) => {
        context.beginPath();
        for (let sample = 0; sample <= samples; sample += 1) {
          const ratio = sample / samples;
          const x = ratio * width;
          const wave = Math.sin(
            ratio * Math.PI * (2.1 + streamIndex * 0.32)
            + elapsed * (0.00012 + streamIndex * 0.00002)
            + scrollProgress * Math.PI * 1.6,
          );
          const pointerDistance = Math.abs(x - pointerX);
          const pointerBend = pointerPresence
            * Math.max(0, 1 - pointerDistance / Math.max(width * 0.28, 1))
            * (pointerY - height * 0.5)
            * 0.055;
          const y = height * (0.2 + streamIndex * 0.29)
            + wave * (18 + streamIndex * 7)
            + pointerBend
            + scrollEnergy * (24 + streamIndex * 7);
          if (sample === 0) context.moveTo(x, y);
          else context.lineTo(x, y);
        }
        context.strokeStyle = gradient;
        context.lineWidth = 0.7 + streamIndex * 0.25;
        context.globalAlpha = intensity * (0.62 - streamIndex * 0.08);
        context.stroke();
      });
    };

    const drawConnections = () => {
      const maxDistance = compactViewport.matches ? 106 : 148;
      const maxDistanceSquared = maxDistance * maxDistance;
      context.beginPath();
      for (let first = 0; first < particles.length; first += 1) {
        const firstX = projected[first * 2] ?? 0;
        const firstY = projected[first * 2 + 1] ?? 0;
        for (let second = first + 1; second < particles.length; second += 1) {
          const secondX = projected[second * 2] ?? 0;
          const secondY = projected[second * 2 + 1] ?? 0;
          const dx = secondX - firstX;
          const dy = secondY - firstY;
          if (dx * dx + dy * dy > maxDistanceSquared) continue;
          context.moveTo(firstX, firstY);
          context.lineTo(secondX, secondY);
        }
      }
      context.strokeStyle = connectionGradient;
      context.lineWidth = 0.55;
      context.globalAlpha = intensity * 0.58;
      context.stroke();
    };

    const drawParticles = (elapsed: number) => {
      PARTICLE_COLORS.forEach((color, tone) => {
        context.beginPath();
        particles.forEach((particle, index) => {
          if (particle.tone !== tone) return;
          const pulse = 0.88 + Math.sin(elapsed * 0.001 + particle.phase) * 0.12;
          const radius = particle.radius * pulse;
          const x = projected[index * 2] ?? 0;
          const y = projected[index * 2 + 1] ?? 0;
          context.moveTo(x + radius, y);
          context.arc(x, y, radius, 0, Math.PI * 2);
        });
        context.fillStyle = color;
        context.globalAlpha = intensity;
        context.fill();
      });
    };

    const drawPointerHalo = () => {
      if (pointerPresence < 0.02) return;
      const radius = compactViewport.matches ? 90 : 135;
      const halo = context.createRadialGradient(
        pointerX,
        pointerY,
        0,
        pointerX,
        pointerY,
        radius,
      );
      halo.addColorStop(0, "rgba(255, 132, 194, 0.08)");
      halo.addColorStop(0.5, "rgba(163, 137, 255, 0.035)");
      halo.addColorStop(1, "rgba(123, 241, 201, 0)");
      context.fillStyle = halo;
      context.globalAlpha = pointerPresence * intensity;
      context.fillRect(pointerX - radius, pointerY - radius, radius * 2, radius * 2);
    };

    const render = (elapsed: number, deltaSeconds: number, moving: boolean) => {
      context.clearRect(0, 0, width, height);
      if (moving) {
        scrollProgress += (targetScrollProgress - scrollProgress) * 0.075;
        scrollEnergy *= 0.9;
        pointerX += (pointerTargetX - pointerX) * 0.11;
        pointerY += (pointerTargetY - pointerY) * 0.11;
        pointerPresence *= 0.994;
      } else {
        scrollProgress = targetScrollProgress;
        pointerX = pointerTargetX;
        pointerY = pointerTargetY;
      }

      context.save();
      context.globalCompositeOperation = "lighter";
      drawStreams(elapsed);
      projectParticles(elapsed, deltaSeconds, moving);
      drawConnections();
      drawParticles(elapsed);
      drawPointerHalo();
      context.restore();
    };

    const stop = () => {
      if (animationFrame) window.cancelAnimationFrame(animationFrame);
      animationFrame = 0;
      lastFrameTime = 0;
    };

    const tick = (time: number) => {
      animationFrame = 0;
      if (!shouldAnimate()) return;
      const deltaSeconds = lastFrameTime
        ? Math.min((time - lastFrameTime) / 1_000, 0.05)
        : 0;
      lastFrameTime = time;
      render(time, deltaSeconds, true);
      animationFrame = window.requestAnimationFrame(tick);
    };

    const syncAnimation = () => {
      stop();
      if (shouldAnimate()) {
        animationFrame = window.requestAnimationFrame(tick);
      } else if (document.visibilityState === "visible" && intersectsViewport) {
        render(0, 0, false);
      }
    };

    const onPointerMove = (event: PointerEvent) => {
      pointerTargetX = event.clientX;
      pointerTargetY = event.clientY;
      pointerPresence = event.pointerType === "touch" ? 0.48 : 1;
      if (!shouldAnimate() && !reducedMotion.matches && intersectsViewport) {
        render(0, 0, false);
      }
    };

    const onPointerLeave = () => {
      pointerPresence = 0;
      if (!shouldAnimate() && intersectsViewport) render(0, 0, false);
    };

    const onScroll = () => {
      updateScrollTarget();
      if (!shouldAnimate() && !reducedMotion.matches && intersectsViewport) {
        render(0, 0, false);
      }
    };

    const onViewportChange = () => {
      resize();
      syncAnimation();
    };

    const onPreferenceChange = () => {
      updateParticleBudget();
      resize();
      syncAnimation();
    };

    const onConnectionChange = () => {
      saveData = connection?.saveData === true;
      onPreferenceChange();
    };

    const observer = typeof IntersectionObserver === "undefined"
      ? null
      : new IntersectionObserver(([entry]) => {
        intersectsViewport = entry?.isIntersecting ?? false;
        syncAnimation();
      });

    resize();
    updateScrollTarget();
    scrollProgress = targetScrollProgress;
    observer?.observe(canvas);
    document.addEventListener("visibilitychange", syncAnimation);
    window.addEventListener("pointermove", onPointerMove, { passive: true });
    window.addEventListener("pointerleave", onPointerLeave);
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onViewportChange, { passive: true });
    window.visualViewport?.addEventListener("resize", onViewportChange, { passive: true });
    reducedMotion.addEventListener("change", onPreferenceChange);
    compactViewport.addEventListener("change", onPreferenceChange);
    connection?.addEventListener("change", onConnectionChange);
    syncAnimation();

    return () => {
      stop();
      observer?.disconnect();
      document.removeEventListener("visibilitychange", syncAnimation);
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerleave", onPointerLeave);
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onViewportChange);
      window.visualViewport?.removeEventListener("resize", onViewportChange);
      reducedMotion.removeEventListener("change", onPreferenceChange);
      compactViewport.removeEventListener("change", onPreferenceChange);
      connection?.removeEventListener("change", onConnectionChange);
    };
  }, [intensity, maxDpr]);

  return canvasRef;
}
