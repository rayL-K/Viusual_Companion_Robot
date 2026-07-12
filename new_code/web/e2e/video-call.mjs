import { spawn } from "node:child_process";
import { existsSync, mkdirSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { chromium } from "playwright-core";

const webRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const v2Root = resolve(webRoot, "..");
const backendRoot = resolve(v2Root, "backend");
const origin = "http://127.0.0.1:8875";
const python = process.env.PYTHON || (process.platform === "win32" ? "python" : "python3");
const server = spawn(python, ["-m", "veyrasoul.gateway.demo"], {
  cwd: backendRoot,
  env: { ...process.env, VEYRASOUL_E2E_PORT: "8875" },
  stdio: ["ignore", "pipe", "pipe"],
});
let serverLog = "";
server.stdout.on("data", (chunk) => { serverLog += chunk; });
server.stderr.on("data", (chunk) => { serverLog += chunk; });

let browser;
try {
  await waitForHealth();
  browser = await chromium.launch({
    executablePath: findBrowser(),
    headless: true,
    args: [
      "--use-fake-device-for-media-stream",
      "--use-fake-ui-for-media-stream",
      "--autoplay-policy=no-user-gesture-required",
      "--disable-background-timer-throttling",
    ],
  });
  const desktop = await verifyViewport(browser, { width: 1440, height: 900, label: "desktop" });
  const mobile = await verifyViewport(browser, {
    width: 390,
    height: 844,
    label: "mobile",
    isMobile: true,
    hasTouch: true,
  });
  const landscape = await verifyViewport(browser, {
    width: 844,
    height: 390,
    label: "mobile-landscape",
    isMobile: true,
    hasTouch: true,
  });
  const artifact = resolve(v2Root, "artifacts", "e2e-local.json");
  mkdirSync(dirname(artifact), { recursive: true });
  writeFileSync(
    artifact,
    `${JSON.stringify({ checkedAt: new Date().toISOString(), desktop, mobile, landscape }, null, 2)}\n`,
  );
  process.stdout.write(`VeyraSoul local browser E2E passed: ${artifact}\n`);
} catch (error) {
  process.stderr.write(`${error?.stack || error}\n--- demo gateway ---\n${serverLog}\n`);
  process.exitCode = 1;
} finally {
  await browser?.close();
  server.kill("SIGINT");
  await Promise.race([new Promise((resolveExit) => server.once("exit", resolveExit)), delay(2_000)]);
  if (server.exitCode === null) server.kill("SIGKILL");
}

async function verifyViewport(browserInstance, options) {
  const context = await browserInstance.newContext({
    viewport: { width: options.width, height: options.height },
    isMobile: options.isMobile ?? false,
    hasTouch: options.hasTouch ?? false,
    permissions: ["camera", "microphone"],
  });
  const page = await context.newPage();
  const pageErrors = [];
  const navigationStartedAt = Date.now();
  page.on("pageerror", (error) => pageErrors.push(String(error)));
  await page.goto(origin, { waitUntil: "domcontentloaded" });
  await page.locator(".presence--ready").waitFor({ timeout: 30_000 });
  await page.getByRole("button", { name: /开始陪伴通话/ }).click();
  await page.locator(".camera-pip video").waitFor({ state: "visible" });
  await page.waitForFunction(() => {
    const video = document.querySelector(".camera-pip video");
    return video instanceof HTMLVideoElement && video.readyState >= 2 && !video.paused;
  });
  const cameraReadyMs = Date.now() - navigationStartedAt;
  await page.locator("textarea").fill("请回应本机端到端测试");
  const replyStartedAt = Date.now();
  await page.getByRole("button", { name: "发送" }).click();
  await page.locator(".dialogue p").filter({ hasText: "顺畅流动" }).waitFor({ timeout: 15_000 });
  const replyVisibleMs = Date.now() - replyStartedAt;
  await page.locator(".stage-presence-label").filter({ hasText: "陪伴中" }).waitFor({ timeout: 15_000 });
  await page.getByRole("button", { name: "打开控制台" }).click();
  await page.locator(".sense-card").filter({ hasText: "视频通话参与者" }).waitFor({ timeout: 10_000 });

  const layout = await page.evaluate(() => ({
    viewportWidth: document.documentElement.clientWidth,
    viewportHeight: document.documentElement.clientHeight,
    scrollWidth: document.documentElement.scrollWidth,
    scrollHeight: document.documentElement.scrollHeight,
    live2dReady: Boolean(document.querySelector(".presence--ready canvas")),
    callButtons: [...document.querySelectorAll(".call-controls button")].map((element) => ({
      clientWidth: element.clientWidth,
      scrollWidth: element.scrollWidth,
      clientHeight: element.clientHeight,
      scrollHeight: element.scrollHeight,
    })),
  }));
  assert(layout.scrollWidth <= layout.viewportWidth, `${options.label}: horizontal overflow`);
  assert(layout.scrollHeight <= layout.viewportHeight, `${options.label}: vertical overflow`);
  assert(layout.live2dReady, `${options.label}: Live2D not ready`);
  assert(layout.callButtons.length === 3, `${options.label}: call controls missing`);
  assert(
    layout.callButtons.every((button) => button.scrollWidth <= button.clientWidth && button.scrollHeight <= button.clientHeight),
    `${options.label}: call control content clipped`,
  );
  assert(pageErrors.length === 0, `${options.label}: pageerror ${pageErrors.join(" | ")}`);
  await context.close();
  return { ...layout, cameraReadyMs, replyVisibleMs, pageErrors };
}

async function waitForHealth() {
  for (let attempt = 0; attempt < 80; attempt += 1) {
    if (server.exitCode !== null) throw new Error(`demo gateway exited (${server.exitCode})`);
    try {
      const response = await fetch(`${origin}/v2/health`);
      if (response.ok) return;
    } catch {
      // 启动窗口内继续轮询。
    }
    await delay(100);
  }
  throw new Error("demo gateway health timeout");
}

function findBrowser() {
  const candidates = [
    process.env.CHROME_PATH,
    "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
    "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
  ].filter(Boolean);
  const executable = candidates.find((candidate) => existsSync(candidate));
  if (!executable) throw new Error("找不到 Chrome/Chromium；请设置 CHROME_PATH");
  return executable;
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function delay(milliseconds) {
  return new Promise((resolveDelay) => setTimeout(resolveDelay, milliseconds));
}
