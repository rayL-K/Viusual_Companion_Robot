import assert from "node:assert/strict";
import { access, mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { chromium } from "playwright-core";

const qaDirectory = path.dirname(fileURLToPath(import.meta.url));
const repositoryRoot = path.resolve(qaDirectory, "../../..");
const artifactDirectory = path.join(repositoryRoot, "output/playwright/brand-motion");
const baseUrl = new URL(process.env.BASE_URL ?? "http://127.0.0.1:4173/").href;
const chromePath = process.env.CHROME_PATH ?? "C:/Program Files/Google/Chrome/Application/chrome.exe";

await access(chromePath);
await mkdir(artifactDirectory, { recursive: true });

const results = [];
const failures = [];

function percentile(values, ratio) {
  if (values.length === 0) return Number.POSITIVE_INFINITY;
  const sorted = [...values].sort((left, right) => left - right);
  return sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * ratio))];
}

function median(values) {
  return percentile(values, 0.5);
}

function recordBrowserErrors(page) {
  const errors = [];
  page.on("pageerror", (error) => errors.push(`pageerror: ${error.message}`));
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(`console: ${message.text()}`);
  });
  return errors;
}

async function installRuntimeProbe(context, initialSaveData = false) {
  await context.addInitScript(({ saveData }) => {
    let dataSaverEnabled = saveData;
    const connection = new EventTarget();
    Object.defineProperty(connection, "saveData", {
      configurable: true,
      get: () => dataSaverEnabled,
    });
    Object.defineProperty(navigator, "connection", {
      configurable: true,
      get: () => connection,
    });
    window.__qaSetSaveData = (enabled) => {
      dataSaverEnabled = Boolean(enabled);
      connection.dispatchEvent(new Event("change"));
    };
    window.__qaLongTasks = [];
    try {
      const observer = new PerformanceObserver((list) => {
        for (const entry of list.getEntries()) window.__qaLongTasks.push(entry.duration);
      });
      observer.observe({ type: "longtask", buffered: true });
    } catch {
      // Long Tasks are an optional browser capability. RAF cadence remains mandatory.
    }
  }, { saveData: initialSaveData });
}

async function openPage(context) {
  const page = await context.newPage();
  const browserErrors = recordBrowserErrors(page);
  const response = await page.goto(baseUrl, { waitUntil: "networkidle", timeout: 30_000 });
  assert.ok(response, `No navigation response for ${baseUrl}`);
  assert.ok(response.status() < 400, `Navigation returned HTTP ${response.status()}`);
  await page.evaluate(async () => {
    if (document.fonts?.ready) await document.fonts.ready;
  });
  return { page, browserErrors };
}

async function canvasChecksum(page) {
  return page.evaluate(() => {
    const source = document.querySelector("canvas[data-motion-layer='living-field']");
    if (!(source instanceof HTMLCanvasElement) || source.width < 1 || source.height < 1) return null;
    const sample = document.createElement("canvas");
    sample.width = 24;
    sample.height = 24;
    const context = sample.getContext("2d", { willReadFrequently: true });
    if (!context) return null;
    context.drawImage(source, 0, 0, sample.width, sample.height);
    const bytes = context.getImageData(0, 0, sample.width, sample.height).data;
    let hash = 2_166_136_261;
    let energy = 0;
    for (let index = 0; index < bytes.length; index += 1) {
      hash ^= bytes[index];
      hash = Math.imul(hash, 16_777_619) >>> 0;
      energy += bytes[index];
    }
    return { hash, energy, width: source.width, height: source.height };
  });
}

async function setSyntheticVisibility(page, state) {
  await page.evaluate((nextState) => {
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      get: () => nextState,
    });
    Object.defineProperty(document, "hidden", {
      configurable: true,
      get: () => nextState !== "visible",
    });
    document.dispatchEvent(new Event("visibilitychange"));
  }, state);
}

async function runCase(name, callback) {
  const startedAt = Date.now();
  try {
    const details = await callback();
    results.push({ name, status: "passed", durationMs: Date.now() - startedAt, details });
    console.log(`PASS ${name}`);
  } catch (error) {
    const message = error instanceof Error ? `${error.name}: ${error.message}` : String(error);
    failures.push({ name, message });
    results.push({ name, status: "failed", durationMs: Date.now() - startedAt, error: message });
    console.error(`FAIL ${name}: ${message}`);
  }
}

const browser = await chromium.launch({
  headless: true,
  executablePath: chromePath,
  args: ["--disable-background-timer-throttling"],
});

try {
  const layoutCases = [
    ["desktop", 1440, 900],
    ["phone", 390, 844],
    ["small", 320, 568],
  ];

  for (const [name, width, height] of layoutCases) {
    await runCase(`layout-${name}`, async () => {
      const context = await browser.newContext({
        viewport: { width, height },
        deviceScaleFactor: 1,
        reducedMotion: "reduce",
      });
      await installRuntimeProbe(context);
      const { page, browserErrors } = await openPage(context);
      await page.waitForTimeout(180);

      const audit = await page.evaluate(() => {
        const allElements = [...document.querySelectorAll("*")];
        const snapping = allElements.flatMap((element) => {
          const style = getComputedStyle(element);
          if (style.scrollSnapType === "none" && style.scrollSnapAlign === "none") return [];
          return [{
            element: `${element.tagName.toLowerCase()}${element.id ? `#${element.id}` : ""}`,
            type: style.scrollSnapType,
            align: style.scrollSnapAlign,
          }];
        });

        const contentSelector = "h1,h2,h3,p,li,a,button,dt,dd,figcaption,strong,small,img";
        const contentElements = [...document.querySelectorAll(contentSelector)];
        const offscreen = [];
        const clipped = [];
        for (const element of contentElements) {
          if (!(element instanceof HTMLElement)) continue;
          if (element.closest("[aria-hidden='true'],[data-allow-bleed]")) continue;
          const style = getComputedStyle(element);
          const rectangle = element.getBoundingClientRect();
          if (style.display === "none" || style.visibility === "hidden" || rectangle.width < 1 || rectangle.height < 1) continue;
          const label = (element.textContent ?? element.getAttribute("alt") ?? "").trim().replace(/\s+/g, " ").slice(0, 72);
          if (rectangle.left < -2 || rectangle.right > innerWidth + 2) {
            offscreen.push({ tag: element.tagName, label, left: Math.round(rectangle.left), right: Math.round(rectangle.right) });
          }
          const clipsX = ["hidden", "clip"].includes(style.overflowX) && element.scrollWidth > element.clientWidth + 2;
          const clipsY = ["hidden", "clip"].includes(style.overflowY) && element.scrollHeight > element.clientHeight + 2;
          if (clipsX || clipsY) {
            clipped.push({
              tag: element.tagName,
              label,
              client: [element.clientWidth, element.clientHeight],
              scroll: [element.scrollWidth, element.scrollHeight],
              overflow: [style.overflowX, style.overflowY],
            });
          }
        }

        const root = document.scrollingElement ?? document.documentElement;
        return {
          overflow: root.scrollWidth - root.clientWidth,
          snapping,
          offscreen,
          clipped,
          pinSpacers: document.querySelectorAll(".pin-spacer").length,
          maxScroll: Math.max(root.scrollHeight - innerHeight, 0),
          h1: document.querySelectorAll("h1").length,
        };
      });

      await page.evaluate(() => scrollTo({ top: 0, behavior: "instant" }));
      await page.screenshot({ path: path.join(artifactDirectory, `${name}.png`), fullPage: false });

      assert.ok(audit.overflow <= 1, `${name}: horizontal overflow is ${audit.overflow}px`);
      assert.deepEqual(audit.snapping, [], `${name}: scroll snapping must not be used`);
      assert.deepEqual(audit.offscreen, [], `${name}: content escapes the viewport: ${JSON.stringify(audit.offscreen)}`);
      assert.deepEqual(audit.clipped, [], `${name}: readable content is clipped: ${JSON.stringify(audit.clipped)}`);
      assert.equal(audit.pinSpacers, 0, `${name}: GSAP pin spacers are not allowed`);
      assert.equal(audit.h1, 1, `${name}: exactly one H1 is required`);
      assert.ok(audit.maxScroll > height, `${name}: the narrative should be a continuous scroll document`);

      const arbitraryTarget = Math.round(audit.maxScroll * 0.373);
      await page.evaluate((top) => scrollTo({ top, behavior: "instant" }), arbitraryTarget);
      await page.waitForTimeout(450);
      const settledPosition = await page.evaluate(() => Math.round(scrollY));
      assert.ok(Math.abs(settledPosition - arbitraryTarget) <= 2, `${name}: scroll position was snapped from ${arbitraryTarget} to ${settledPosition}`);
      assert.deepEqual(browserErrors, [], `${name}: browser errors: ${browserErrors.join(" | ")}`);
      await context.close();
      return audit;
    });
  }

  await runCase("desktop-motion-performance-and-anchor", async () => {
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });
    await installRuntimeProbe(context);
    const { page, browserErrors } = await openPage(context);
    await page.waitForTimeout(1_450);
    await page.evaluate(() => { window.__qaLongTasks.length = 0; });

    const probe = await page.evaluate(async () => {
      const layerElements = [...document.querySelectorAll("[data-motion-layer]")];
      const layerId = (element) => element.getAttribute("data-motion-layer") ?? "unknown";
      const signature = (element) => {
        const nodes = [element, ...element.querySelectorAll("*")].slice(0, 36);
        return nodes.map((node) => {
          const style = getComputedStyle(node);
          return `${style.transform}|${style.opacity}|${style.clipPath}`;
        }).join(";");
      };
      const snapshots = [];
      const baselineFrames = [];
      const scrollFrames = [];
      let previous = performance.now();
      await new Promise((resolve) => {
        const started = performance.now();
        const tick = (now) => {
          baselineFrames.push(now - previous);
          previous = now;
          if (now - started >= 420) resolve();
          else requestAnimationFrame(tick);
        };
        requestAnimationFrame(tick);
      });

      const maxScroll = Math.max(document.documentElement.scrollHeight - innerHeight, 1);
      previous = performance.now();
      await new Promise((resolve) => {
        const started = performance.now();
        let lastSample = -Infinity;
        const duration = 2_650;
        const tick = (now) => {
          scrollFrames.push(now - previous);
          previous = now;
          const progress = Math.min((now - started) / duration, 1);
          scrollTo(0, maxScroll * progress);
          if (now - lastSample >= 105 || progress === 1) {
            lastSample = now;
            snapshots.push({
              progress,
              layers: Object.fromEntries(layerElements.map((element) => [layerId(element), signature(element)])),
            });
          }
          if (progress < 1) requestAnimationFrame(tick);
          else resolve();
        };
        requestAnimationFrame(tick);
      });

      return {
        snapshots,
        baselineFrames: baselineFrames.slice(2),
        scrollFrames: scrollFrames.slice(2),
        metadata: layerElements.map((element) => ({
          id: layerId(element),
          scope: element.getAttribute("data-motion-scope") ?? "unknown",
          behavior: element.getAttribute("data-motion-behavior") ?? "unknown",
        })),
        longTasks: [...window.__qaLongTasks],
      };
    });

    const distinctStates = Object.fromEntries(probe.metadata.map(({ id }) => [
      id,
      new Set(probe.snapshots.map((sample) => sample.layers[id])).size,
    ]));
    for (const wash of ["wash-rose", "wash-violet", "wash-mint"]) {
      assert.ok((distinctStates[wash] ?? 0) >= 5, `${wash} is not continuously scroll-linked: ${distinctStates[wash] ?? 0} states`);
    }

    const activeByScope = new Map();
    for (const layer of probe.metadata) {
      if (layer.behavior !== "scrub" || layer.scope === "global") continue;
      if ((distinctStates[layer.id] ?? 0) < 3) continue;
      activeByScope.set(layer.scope, (activeByScope.get(layer.scope) ?? 0) + 1);
    }
    for (const scope of ["hero", "manifesto", "pipeline", "architecture", "products", "closing"]) {
      assert.ok((activeByScope.get(scope) ?? 0) >= 1, `${scope} has no proven local scroll-linked layer`);
    }
    const multiLayerScopes = [...activeByScope.values()].filter((count) => count >= 2).length;
    assert.ok(multiLayerScopes >= 4, `Only ${multiLayerScopes} scopes prove multi-layer movement; expected at least 4`);

    const baselineMedian = median(probe.baselineFrames);
    const scrollP95 = percentile(probe.scrollFrames, 0.95);
    const severeThreshold = Math.max(50, baselineMedian * 4);
    const severeRatio = probe.scrollFrames.filter((duration) => duration > severeThreshold).length / Math.max(probe.scrollFrames.length, 1);
    const longTaskMaximum = Math.max(0, ...probe.longTasks);
    const longTaskTotal = probe.longTasks.reduce((total, duration) => total + duration, 0);
    assert.ok(probe.scrollFrames.length >= 90, `Too few RAF samples: ${probe.scrollFrames.length}`);
    assert.ok(scrollP95 <= Math.max(32, baselineMedian * 2.5), `RAF p95 ${scrollP95.toFixed(1)}ms exceeds the adaptive frame budget`);
    assert.ok(severeRatio <= 0.05, `Severe frame ratio ${(severeRatio * 100).toFixed(1)}% exceeds 5%`);
    assert.ok(longTaskMaximum <= 150, `Longest main-thread task is ${longTaskMaximum.toFixed(1)}ms`);
    assert.ok(longTaskTotal <= 400, `Long tasks total ${longTaskTotal.toFixed(1)}ms during the short scroll`);

    const animatedCanvasBefore = await canvasChecksum(page);
    await page.waitForTimeout(320);
    const animatedCanvasAfter = await canvasChecksum(page);
    assert.ok(animatedCanvasBefore && animatedCanvasAfter, "LivingField canvas is missing or has no backing store");
    assert.ok(animatedCanvasBefore.energy > 0, "LivingField canvas rendered no visible signal");
    assert.notEqual(animatedCanvasBefore.hash, animatedCanvasAfter.hash, "LivingField canvas is not animating while visible");

    await page.evaluate(() => scrollTo({ top: 0, behavior: "instant" }));
    await page.waitForTimeout(100);
    await page.evaluate(() => {
      window.__qaScrollPositions = [scrollY];
      window.__qaScrollListener = () => window.__qaScrollPositions.push(scrollY);
      addEventListener("scroll", window.__qaScrollListener, { passive: true });
    });
    await page.getByRole("link", { name: "边云协同" }).click();
    await page.waitForTimeout(1_100);
    const anchor = await page.evaluate(() => {
      removeEventListener("scroll", window.__qaScrollListener);
      const headerHeight = document.querySelector(".site-header")?.getBoundingClientRect().height ?? 0;
      const targetTop = document.querySelector("#architecture")?.getBoundingClientRect().top ?? -1;
      return { positions: window.__qaScrollPositions, headerHeight, targetTop, hash: location.hash };
    });
    const distinctPositions = new Set(anchor.positions.map((value) => Math.round(value))).size;
    const monotonic = anchor.positions.every((value, index, values) => index === 0 || value >= values[index - 1] - 2);
    assert.ok(distinctPositions >= 6, `Anchor jump exposed only ${distinctPositions} intermediate positions`);
    assert.ok(monotonic, "Anchor jump reversed direction during its transition");
    assert.equal(anchor.hash, "#architecture", "Anchor jump did not update the URL hash");
    assert.ok(anchor.targetTop >= anchor.headerHeight + 4 && anchor.targetTop <= anchor.headerHeight + 24,
      `Anchor target top ${anchor.targetTop.toFixed(1)}px is not safely below the ${anchor.headerHeight.toFixed(1)}px header`);

    assert.deepEqual(browserErrors, [], `desktop motion browser errors: ${browserErrors.join(" | ")}`);
    await page.screenshot({ path: path.join(artifactDirectory, "desktop-motion.png"), fullPage: false });
    await context.close();
    return {
      distinctStates,
      activeByScope: Object.fromEntries(activeByScope),
      performance: { baselineMedian, scrollP95, severeRatio, longTaskMaximum, longTaskTotal },
      anchor,
    };
  });

  await runCase("reduced-motion", async () => {
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, reducedMotion: "reduce" });
    await installRuntimeProbe(context);
    const { page, browserErrors } = await openPage(context);
    await page.waitForTimeout(120);
    const before = await canvasChecksum(page);
    await page.waitForTimeout(320);
    const after = await canvasChecksum(page);
    assert.ok(before && after, "Reduced-motion LivingField canvas is missing");
    assert.equal(before.hash, after.hash, "LivingField must remain static under reduced motion");

    const policy = await page.evaluate(() => ({
      hiddenContent: [...document.querySelectorAll("[data-motion]")].filter((element) => Number(getComputedStyle(element).opacity) < 0.99).length,
      animatedLoops: [...document.querySelectorAll(".signal-presence__orbit,.chapter-next i")].filter((element) => {
        const style = getComputedStyle(element, element.matches("i") ? "::after" : undefined);
        return style.animationName !== "none" && Number.parseFloat(style.animationDuration) > 0.02;
      }).length,
    }));
    assert.equal(policy.hiddenContent, 0, "Reduced motion leaves content hidden");
    assert.equal(policy.animatedLoops, 0, "Reduced motion leaves decorative loops running");

    await page.getByRole("link", { name: "边云协同" }).click();
    await page.waitForTimeout(80);
    const anchor = await page.evaluate(() => ({
      header: document.querySelector(".site-header")?.getBoundingClientRect().height ?? 0,
      top: document.querySelector("#architecture")?.getBoundingClientRect().top ?? -1,
    }));
    assert.ok(anchor.top >= anchor.header - 2 && anchor.top <= anchor.header + 24,
      `Reduced-motion anchor top ${anchor.top.toFixed(1)}px is not below header ${anchor.header.toFixed(1)}px`);
    assert.deepEqual(browserErrors, [], `reduced-motion browser errors: ${browserErrors.join(" | ")}`);
    await context.close();
    return { canvasHash: before.hash, policy, anchor };
  });

  await runCase("save-data-initial-and-dynamic", async () => {
    const initialContext = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    await installRuntimeProbe(initialContext, true);
    const initial = await openPage(initialContext);
    await initial.page.waitForTimeout(180);
    assert.ok(await initial.page.locator(".site").evaluate((element) => element.classList.contains("is-data-saver")), "Initial Save-Data mode was not applied");
    const initialPolicy = await initial.page.evaluate(() => ({
      pipelinePosition: getComputedStyle(document.querySelector(".pipeline__scene")).position,
      transformedStages: [...document.querySelectorAll(".signal-flow__stage")].filter((element) => getComputedStyle(element).transform !== "none").length,
    }));
    assert.notEqual(initialPolicy.pipelinePosition, "sticky", "Initial Save-Data must disable the long sticky scene");
    assert.equal(initialPolicy.transformedStages, 0, "Initial Save-Data must not leave staged transforms active");
    const initialCanvasBefore = await canvasChecksum(initial.page);
    await initial.page.waitForTimeout(320);
    const initialCanvasAfter = await canvasChecksum(initial.page);
    assert.ok(initialCanvasBefore && initialCanvasAfter, "Save-Data LivingField canvas is missing");
    assert.equal(initialCanvasBefore.hash, initialCanvasAfter.hash, "Initial Save-Data must freeze LivingField animation");
    assert.deepEqual(initial.browserErrors, [], `initial Save-Data browser errors: ${initial.browserErrors.join(" | ")}`);
    await initialContext.close();

    const dynamicContext = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    await installRuntimeProbe(dynamicContext, false);
    const dynamic = await openPage(dynamicContext);
    await dynamic.page.waitForTimeout(1_350);
    const movingBefore = await canvasChecksum(dynamic.page);
    await dynamic.page.waitForTimeout(320);
    const movingAfter = await canvasChecksum(dynamic.page);
    assert.ok(movingBefore && movingAfter, "Dynamic Save-Data LivingField canvas is missing");
    assert.notEqual(movingBefore.hash, movingAfter.hash, "LivingField was not moving before dynamic Save-Data activation");

    await dynamic.page.evaluate(() => window.__qaSetSaveData(true));
    await dynamic.page.waitForTimeout(120);
    assert.ok(await dynamic.page.locator(".site").evaluate((element) => element.classList.contains("is-data-saver")), "Dynamic Save-Data class was not applied");
    const frozenBefore = await canvasChecksum(dynamic.page);
    await dynamic.page.waitForTimeout(320);
    const frozenAfter = await canvasChecksum(dynamic.page);
    assert.equal(frozenBefore?.hash, frozenAfter?.hash, "Dynamic Save-Data did not pause LivingField");

    await dynamic.page.evaluate(() => window.__qaSetSaveData(false));
    await dynamic.page.waitForTimeout(120);
    assert.ok(!await dynamic.page.locator(".site").evaluate((element) => element.classList.contains("is-data-saver")), "Dynamic Save-Data class did not clear");
    const resumedBefore = await canvasChecksum(dynamic.page);
    await dynamic.page.waitForTimeout(320);
    const resumedAfter = await canvasChecksum(dynamic.page);
    assert.notEqual(resumedBefore?.hash, resumedAfter?.hash, "LivingField did not resume after Save-Data cleared");
    assert.deepEqual(dynamic.browserErrors, [], `dynamic Save-Data browser errors: ${dynamic.browserErrors.join(" | ")}`);
    await dynamicContext.close();
    return { initialPolicy };
  });

  await runCase("visibility-pause-and-resume", async () => {
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    await installRuntimeProbe(context);
    const { page, browserErrors } = await openPage(context);
    await page.waitForTimeout(1_250);
    await setSyntheticVisibility(page, "hidden");
    await page.waitForTimeout(100);
    assert.ok(await page.locator(".site").evaluate((element) => element.classList.contains("is-page-hidden")), "Hidden page state class was not applied");
    const hiddenBefore = await canvasChecksum(page);
    await page.waitForTimeout(320);
    const hiddenAfter = await canvasChecksum(page);
    assert.ok(hiddenBefore && hiddenAfter, "Visibility LivingField canvas is missing");
    assert.equal(hiddenBefore.hash, hiddenAfter.hash, "LivingField kept animating while the page was hidden");

    await setSyntheticVisibility(page, "visible");
    await page.waitForTimeout(100);
    assert.ok(!await page.locator(".site").evaluate((element) => element.classList.contains("is-page-hidden")), "Visible page state class did not clear");
    const visibleBefore = await canvasChecksum(page);
    await page.waitForTimeout(320);
    const visibleAfter = await canvasChecksum(page);
    assert.notEqual(visibleBefore?.hash, visibleAfter?.hash, "LivingField did not resume after visibility returned");
    assert.deepEqual(browserErrors, [], `visibility browser errors: ${browserErrors.join(" | ")}`);
    await context.close();
    return { hiddenHash: hiddenBefore.hash, resumedHash: visibleAfter?.hash };
  });
} finally {
  await browser.close();
}

const report = {
  generatedAt: new Date().toISOString(),
  baseUrl,
  chromePath,
  passed: results.filter((result) => result.status === "passed").length,
  failed: failures.length,
  results,
};
await writeFile(path.join(artifactDirectory, "report.json"), `${JSON.stringify(report, null, 2)}\n`, "utf8");

console.log(`Motion contract: ${report.passed} passed, ${report.failed} failed`);
console.log(`Artifacts: ${artifactDirectory}`);
if (failures.length > 0) {
  console.error(failures.map((failure) => `- ${failure.name}: ${failure.message}`).join("\n"));
  process.exitCode = 1;
}
