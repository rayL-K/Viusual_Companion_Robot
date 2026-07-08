import { execFileSync } from "node:child_process";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative, resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const requiredFiles = [
  "game.js",
  "game.json",
  "project.config.json",
  "game/main.js",
  "game/companion-game.js",
  "game/layout.js",
  "game/view.js",
  "core/api-client.js",
  "core/audio-controller.js",
  "core/avatar-controller.js",
  "core/perception-controller.js",
  "libs/pixi.miniprogram.js",
  "libs/live2dcubismcore.min.js",
  "libs/pixi-live2d-display.js",
];

for (const file of requiredFiles) {
  if (!statSync(join(root, file)).isFile()) {
    throw new Error(`缺少小游戏运行文件：${file}`);
  }
}

for (const file of ["game.json", "project.config.json"]) {
  JSON.parse(readFileSync(join(root, file), "utf8"));
}

const projectConfig = JSON.parse(readFileSync(join(root, "project.config.json"), "utf8"));
if (projectConfig.compileType !== "game" || !/^wx[a-zA-Z0-9]{16}$/.test(projectConfig.appid)) {
  throw new Error("project.config.json 必须绑定正式小游戏 AppID 并使用 game 编译类型。");
}

function walk(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name);
    return entry.isDirectory() ? walk(path) : [path];
  });
}

const sourceFiles = walk(root).filter((file) => file.endsWith(".js") && !file.includes(`${join(root, "libs")}\\`));
for (const file of sourceFiles) {
  execFileSync(process.execPath, ["--check", file], { stdio: "pipe" });
}

const gameSource = readFileSync(join(root, "game/companion-game.js"), "utf8");
const perceptionSource = readFileSync(join(root, "core/perception-controller.js"), "utf8");
const apiSource = readFileSync(join(root, "core/api-client.js"), "utf8");
for (const marker of [
  "_loadAvatar",
  "submitText",
  "handleAudioSegment",
  "_triggerAction",
  "_previewVoice",
  "refreshRuntime",
  "_saveDevice",
]) {
  if (!gameSource.includes(marker)) {
    throw new Error(`小游戏主控制器缺少功能入口：${marker}`);
  }
}

if (!perceptionSource.includes("wx.createCamera(") || perceptionSource.includes("createCameraContext")) {
  throw new Error("小游戏视觉必须使用 wx.createCamera，不能误用小程序 camera 组件接口。");
}
if (!apiSource.includes('this.request("/vision"') || !apiSource.includes('this.request("/vision-health"')) {
  throw new Error("小游戏必须通过统一板端视觉接口传输摄像头帧。");
}
if (gameSource.includes('const vision = { emotion: "neutral"')) {
  throw new Error("小游戏对话不能再使用固定 neutral 伪造视觉上下文。");
}

const allTrackedSource = sourceFiles.map((file) => readFileSync(file, "utf8")).join("\n");
if (/sk-[A-Za-z0-9_-]{16,}|eyJ[A-Za-z0-9_-]{80,}|-----BEGIN (?:RSA |EC )?PRIVATE KEY-----/.test(allTrackedSource)) {
  throw new Error("小程序源码中禁止保存模型服务密钥、Tunnel token 或私钥。");
}

const ignored = projectConfig.packOptions?.ignore || [];
function isIgnored(file) {
  const relativePath = relative(root, file).replaceAll("\\", "/");
  return ignored.some((entry) => {
    const value = String(entry.value || "").replaceAll("\\", "/").replace(/^\.\//, "").replace(/\/$/, "");
    return entry.type === "folder" ? relativePath === value || relativePath.startsWith(`${value}/`) : relativePath === value;
  });
}

const runtimeBytes = walk(root)
  .filter((file) => !isIgnored(file))
  .reduce((total, file) => total + statSync(file).size, 0);
if (runtimeBytes > 2 * 1024 * 1024) {
  throw new Error(`小游戏主包超过 2 MiB：${runtimeBytes} bytes`);
}

console.log(`小游戏静态检查通过，运行包约 ${(runtimeBytes / 1024).toFixed(1)} KiB。`);
