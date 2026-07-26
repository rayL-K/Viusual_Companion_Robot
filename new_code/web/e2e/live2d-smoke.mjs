import { spawn } from "node:child_process";
import { existsSync, mkdirSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { chromium } from "playwright-core";

const webRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const newCodeRoot = resolve(webRoot, "..");
const repositoryRoot = resolve(newCodeRoot, "..");
const backendRoot = resolve(newCodeRoot, "backend");
// Keep dated runs separate: screenshots are review evidence, not web build output.
const artifactRoot = resolve(
  repositoryRoot,
  "output",
  "playwright",
  process.env.VEYRASOUL_LIVE2D_ARTIFACT_DIR || "anima-live2d-20260724",
);
const port =
  process.env.ANIMA_LIVE2D_SMOKE_PORT
  || process.env.VEYRASOUL_LIVE2D_SMOKE_PORT
  || "8876";
const origin = (process.env.BASE_URL || `http://127.0.0.1:${port}`).replace(/\/+$/, "");
const python = process.env.PYTHON || (process.platform === "win32" ? "python" : "python3");
const ownsServer = !process.env.BASE_URL;
const server = ownsServer
  ? spawn(python, ["-m", "veyrasoul.gateway.demo"], {
      cwd: backendRoot,
      // The deterministic local demo never calls an upstream provider.  Do not
      // inherit a developer's SOCKS proxy: httpx validates proxy transports at
      // construction time, which can make an otherwise disabled-admission E2E
      // run fail when socksio is intentionally absent.
      env: demoEnvironment(),
      stdio: ["ignore", "pipe", "pipe"],
    })
  : null;

let serverLog = "";
server?.stdout.on("data", (chunk) => { serverLog += chunk; });
server?.stderr.on("data", (chunk) => { serverLog += chunk; });

let browser;
try {
  mkdirSync(artifactRoot, { recursive: true });
  await waitForService();
  browser = await chromium.launch({
    executablePath: findBrowser(),
    headless: true,
    args: [
      "--autoplay-policy=no-user-gesture-required",
      "--disable-background-timer-throttling",
      "--enable-webgl",
      "--ignore-gpu-blocklist",
    ],
  });

  const cases = [
    {
      label: "desktop",
      viewport: { width: 1440, height: 900 },
      expectedModel: "/live2d/Strawberry_Rabbit/Strawberry_Rabbit.model3.json",
    },
    {
      label: "mobile-390",
      viewport: { width: 390, height: 844 },
      isMobile: true,
      hasTouch: true,
      expectedModel: "/live2d/Strawberry_Rabbit/Strawberry_Rabbit.mobile-1024-r2.model3.json",
    },
    {
      label: "tablet-768",
      viewport: { width: 768, height: 1024 },
      isMobile: true,
      hasTouch: true,
      expectedModel: "/live2d/Strawberry_Rabbit/Strawberry_Rabbit.mobile-1024-r2.model3.json",
    },
  ];
  const viewports = {};
  for (const smokeCase of cases) {
    viewports[smokeCase.label] = await verifyViewport(browser, smokeCase);
  }

  const reportPath = resolve(artifactRoot, "report.json");
  writeFileSync(reportPath, `${JSON.stringify({
    checkedAt: new Date().toISOString(),
    origin,
    viewports,
  }, null, 2)}\n`);
  process.stdout.write(`Anima Live2D browser smoke passed: ${reportPath}\n`);
} catch (error) {
  process.stderr.write(`${error?.stack || error}\n`);
  if (serverLog.trim()) process.stderr.write(`--- demo gateway ---\n${serverLog}\n`);
  process.exitCode = 1;
} finally {
  await browser?.close();
  await stopOwnedServer();
}

async function verifyViewport(browserInstance, smokeCase) {
  const context = await browserInstance.newContext({
    viewport: smokeCase.viewport,
    isMobile: smokeCase.isMobile ?? false,
    hasTouch: smokeCase.hasTouch ?? false,
  });
  const page = await context.newPage();
  const consoleErrors = [];
  const pageErrors = [];
  const failedModelRequests = [];
  const modelResponses = [];

  page.on("console", (message) => {
    if (message.type() === "error") {
      const location = message.location();
      consoleErrors.push(`${message.text()} @ ${location.url || "unknown"}:${location.lineNumber ?? 0}`);
    }
  });
  page.on("pageerror", (error) => pageErrors.push(String(error)));
  page.on("requestfailed", (request) => {
    if (isModelAsset(request.url())) {
      failedModelRequests.push(`${request.url()} :: ${request.failure()?.errorText || "unknown failure"}`);
    }
  });
  page.on("response", (response) => {
    if (isModelAsset(response.url())) {
      modelResponses.push({ url: response.url(), status: response.status() });
    }
  });

  try {
    const startedAt = Date.now();
    const navigation = await page.goto(origin, { waitUntil: "domcontentloaded", timeout: 30_000 });
    assert(navigation?.ok(), `${smokeCase.label}: navigation failed (${navigation?.status() ?? "no response"})`);
    const admissionResponse = await page.request.get(`${origin}/v2/admission/status`, {
      headers: { Accept: "application/json" },
    });
    assert(admissionResponse.ok(), `${smokeCase.label}: local admission status failed`);
    const admission = await admissionResponse.json();
    assert(admission?.required === false && admission?.ready === true,
      `${smokeCase.label}: local disabled admission must not block realtime startup: ${JSON.stringify(admission)}`);
    await page.locator(".presence--ready").waitFor({ state: "attached", timeout: 45_000 });
    await page.locator(".connection--online").waitFor({ state: "attached", timeout: 15_000 });
    assert(await page.locator(".presence--fallback").count() === 0,
      `${smokeCase.label}: fallback avatar was rendered`);

    const canvas = await page.locator("#live2d-canvas").evaluate((element) => {
      if (!(element instanceof HTMLCanvasElement)) throw new Error("#live2d-canvas is not a canvas");
      const rect = element.getBoundingClientRect();
      return {
        clientWidth: element.clientWidth,
        clientHeight: element.clientHeight,
        backingWidth: element.width,
        backingHeight: element.height,
        boundingWidth: rect.width,
        boundingHeight: rect.height,
      };
    });
    assert(Object.values(canvas).every((value) => value > 0),
      `${smokeCase.label}: Live2D canvas has a zero dimension ${JSON.stringify(canvas)}`);

    const expectedResponse = modelResponses.find(({ url }) => new URL(url).pathname === smokeCase.expectedModel);
    assert(expectedResponse,
      `${smokeCase.label}: expected model request was not observed (${smokeCase.expectedModel})`);
    assert(expectedResponse.status === 200,
      `${smokeCase.label}: model manifest returned ${expectedResponse.status}, expected 200`);
    assert(modelResponses.every(({ status }) => status === 200),
      `${smokeCase.label}: model asset response was not 200: ${JSON.stringify(modelResponses.filter(({ status }) => status !== 200))}`);
    assert(failedModelRequests.length === 0,
      `${smokeCase.label}: model request failed: ${failedModelRequests.join(" | ")}`);
    const overflow = await page.evaluate(() => {
      const selectors = [
        ".topbar",
        ".experience",
        ".stage-region",
        ".conversation-rail",
        ".dialogue",
        ".composer",
        ".voice-button",
        ".send-button",
        ".start-call",
      ];
      const topbar = document.querySelector(".topbar");
      const brand = document.querySelector(".brand");
      const viewport = { width: window.innerWidth, height: window.innerHeight };
      const issues = selectors.flatMap((selector) => Array.from(document.querySelectorAll(selector))
        .map((element) => {
          const rect = element.getBoundingClientRect();
          return {
            selector,
            left: Math.round(rect.left),
            top: Math.round(rect.top),
            right: Math.round(rect.right),
            bottom: Math.round(rect.bottom),
            width: Math.round(rect.width),
            height: Math.round(rect.height),
          };
        })
        .filter((rect) => rect.width < 1 || rect.height < 1
          || rect.left < -1 || rect.top < -1
          || rect.right > viewport.width + 1 || rect.bottom > viewport.height + 1));
      return {
        documentScrollWidth: document.documentElement.scrollWidth,
        viewport,
        issues,
        header: topbar && brand ? (() => {
          const topbarRect = topbar.getBoundingClientRect();
          const brandRect = brand.getBoundingClientRect();
          const topmost = document.elementFromPoint(
            brandRect.left + brandRect.width / 2,
            brandRect.top + brandRect.height / 2,
          );
          return {
            topbar: [topbarRect.left, topbarRect.top, topbarRect.width, topbarRect.height],
            brand: [brandRect.left, brandRect.top, brandRect.width, brandRect.height],
            isTopmost: topmost?.closest(".topbar") !== null,
          };
        })() : null,
      };
    });
    assert(overflow.documentScrollWidth <= overflow.viewport.width + 1,
      `${smokeCase.label}: horizontal page overflow ${JSON.stringify(overflow)}`);
    assert(overflow.issues.length === 0,
      `${smokeCase.label}: primary control overflow ${JSON.stringify(overflow.issues)}`);
    assert(overflow.header?.isTopmost === true,
      `${smokeCase.label}: top navigation is hidden behind the stage ${JSON.stringify(overflow.header)}`);

    const identity = await page.evaluate(() => ({
      title: document.title,
      text: document.body.innerText,
    }));
    assert(identity.title === "Anima · v0.0.1",
      `${smokeCase.label}: unexpected title ${JSON.stringify(identity.title)}`);
    assert(identity.text.includes("Anima") && identity.text.includes("v0.0.1"),
      `${smokeCase.label}: canonical product identity is missing`);
    for (const legacy of ["草莓兔兔", "VeyraSoul", "ELF2", "V2 仍未部署"]) {
      assert(!identity.text.includes(legacy), `${smokeCase.label}: legacy identity is visible (${legacy})`);
    }

    await page.screenshot({
      path: resolve(artifactRoot, `${smokeCase.label}.png`),
      fullPage: false,
    });
    assert(pageErrors.length === 0, `${smokeCase.label}: pageerror: ${pageErrors.join(" | ")}`);
    assert(consoleErrors.length === 0, `${smokeCase.label}: console error: ${consoleErrors.join(" | ")}`);

    return {
      readyMs: Date.now() - startedAt,
      viewport: smokeCase.viewport,
      canvas,
      expectedModel: smokeCase.expectedModel,
      admission,
      overflow,
      modelResponses,
      pageErrors,
      consoleErrors,
      screenshot: resolve(artifactRoot, `${smokeCase.label}.png`),
    };
  } finally {
    await context.close();
  }
}

function isModelAsset(rawUrl) {
  try {
    return new URL(rawUrl).pathname.startsWith("/live2d/Strawberry_Rabbit/");
  } catch {
    return false;
  }
}

async function waitForService() {
  for (let attempt = 0; attempt < 120; attempt += 1) {
    if (server && server.exitCode !== null) {
      throw new Error(`demo gateway exited before health check (${server.exitCode})`);
    }
    try {
      const response = await fetch(`${origin}/v2/health`);
      if (response.ok) return;
    } catch {
      // The demo server may still be starting.
    }
    await delay(100);
  }
  throw new Error(`service health timeout: ${origin}/v2/health`);
}

async function stopOwnedServer() {
  if (!server || server.exitCode !== null) return;
  server.kill();
  await Promise.race([
    new Promise((resolveExit) => server.once("exit", resolveExit)),
    delay(2_000),
  ]);
  if (server.exitCode === null) server.kill("SIGKILL");
}

function findBrowser() {
  const candidates = [
    process.env.CHROME_PATH,
    "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
    "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
    "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
    "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
  ].filter(Boolean);
  const executable = candidates.find((candidate) => existsSync(candidate));
  if (!executable) throw new Error("找不到 Chrome/Chromium；请设置 CHROME_PATH");
  return executable;
}

function demoEnvironment() {
  const env = { ...process.env, ANIMA_E2E_PORT: port };
  for (const key of ["ALL_PROXY", "HTTP_PROXY", "HTTPS_PROXY", "all_proxy", "http_proxy", "https_proxy"]) {
    delete env[key];
  }
  return env;
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function delay(milliseconds) {
  return new Promise((resolveDelay) => setTimeout(resolveDelay, milliseconds));
}
