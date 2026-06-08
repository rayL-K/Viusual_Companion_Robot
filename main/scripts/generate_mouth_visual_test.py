"""生成嘴型同步可视化测试报告。

报告使用固定文本和固定音素序列，覆盖普通话主要声母、韵母以及英语常见
元音/辅音。每个音的嘴型和临时合成音频都来自 ``config/mouth_shapes.json``，
便于直接调整参数并重新生成报告。
"""

from __future__ import annotations

import argparse
import json
import sys
import webbrowser
from pathlib import Path
from typing import Any, Dict, List, Optional


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = PROJECT_ROOT / "main" / "src"
DEFAULT_REPORT_DIR = PROJECT_ROOT / "main" / "reports"
DEFAULT_HTML_REPORT = DEFAULT_REPORT_DIR / "mouth_visual_test.html"
DEFAULT_JSON_REPORT = DEFAULT_REPORT_DIR / "mouth_visual_test.json"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from visual_companion_robot.runtime.config import load_app_config
from visual_companion_robot.ui.live2d.avatar import load_live2d_avatar
from visual_companion_robot.ui.live2d.mouth_sync import (
    VISEME_SHAPES,
    VISUAL_MOUTH_TEST_TEXT,
    VisemeSample,
    build_mouth_sync_frames,
    build_visual_mouth_test_sequence,
    default_mouth_config_path,
    load_mouth_shape_config,
    summarize_viseme_coverage,
    validate_mouth_shape_config,
)


def sample_to_dict(sample: VisemeSample) -> Dict[str, Any]:
    """把嘴型样本转换为前端可直接使用的 JSON 对象。"""

    shape = sample.shape
    return {
        "soundKey": sample.sound_key,
        "token": sample.token,
        "group": sample.group,
        "viseme": sample.viseme,
        "label": shape.label,
        "durationMs": sample.duration_ms,
        "mouthOpen": shape.mouth_open,
        "mouthWidth": shape.mouth_width,
        "mouthRound": shape.mouth_round,
        "jawDrop": shape.jaw_drop,
        "smile": shape.smile,
        "tension": shape.tension,
        "audio": sample.audio.as_dict(),
        "note": sample.note,
    }


def build_report_payload(samples: List[VisemeSample], mouth_config_path: Optional[Path]) -> Dict[str, Any]:
    """生成 HTML 和 JSON 共享的测试报告数据。

    Raises:
        FileNotFoundError: 配置文件或模型文件缺失。
        ValueError: 配置格式错误。
    """

    try:
        app_config = load_app_config()
        avatar = load_live2d_avatar(
            app_config.live2d_display.manifest_path,
            expected_name=app_config.live2d_display.model_name,
            expected_model3_path=app_config.live2d_display.model_path,
        )
    except (FileNotFoundError, ValueError) as exc:
        raise FileNotFoundError(f"Live2D 模型资源加载失败：{exc}") from exc

    try:
        config_path = mouth_config_path or default_mouth_config_path()
        mouth_config = load_mouth_shape_config(config_path)
    except (OSError, ValueError) as exc:
        raise FileNotFoundError(f"嘴型配置文件加载失败 [{config_path if 'config_path' in dir() else '(未定位)'}]：{exc}") from exc

    frames = build_mouth_sync_frames(samples)
    coverage = summarize_viseme_coverage(samples)

    return {
        "title": "Live2D 嘴型同步可视化测试",
        "avatar": {
            "name": avatar.name,
            "model3": str(avatar.model3_path),
            "expressions": len(avatar.expressions),
            "motions": len(avatar.motions),
        },
        "configPath": str(config_path),
        "parameterGuide": mouth_config.get("parameterGuide", {}),
        "audioGuide": mouth_config.get("audioGuide", {}),
        "sequence": mouth_config.get("sequence", []),
        "text": VISUAL_MOUTH_TEST_TEXT,
        "samples": [sample_to_dict(sample) for sample in samples],
        "frames": [frame.__dict__ for frame in frames],
        "coverage": coverage,
        "shapeNames": {name: shape.label for name, shape in VISEME_SHAPES.items()},
    }


def render_html(payload: Dict[str, Any]) -> str:
    """渲染独立 HTML 报告。

    该函数包含完整的 CSS + HTML + JS 模板（约 700 行），长度来自模板字符串拼接而非
    复杂逻辑。模板区域已用注释分隔为 CSS / 结构 / 脚本三段，便于定位维护。
    """

    data_json = json.dumps(payload, ensure_ascii=False, indent=2).replace("</", "<\\/")
    html = _HTML_PREFIX + data_json + _HTML_SUFFIX
    return html


# ---- HTML 模板前半段：DOCTYPE → CSS → 结构 -------------------------------------------------
_HTML_PREFIX = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Live2D 嘴型同步可视化测试</title>
  <style>
    :root {
      --ink: #17211c;
      --muted: #66746d;
      --panel: rgba(255, 252, 244, 0.88);
      --panel-strong: rgba(255, 255, 255, 0.94);
      --line: rgba(34, 42, 38, 0.14);
      --accent: #e05c38;
      --leaf: #287d5a;
      --gold: #d8a23a;
      --bg: #f4eddd;
      --shadow: 0 26px 88px rgba(40, 53, 46, 0.18);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      color: var(--ink);
      font-family: "Microsoft YaHei", "Segoe UI", sans-serif;
      background:
        radial-gradient(circle at 14% 10%, rgba(224, 92, 56, 0.20), transparent 22rem),
        radial-gradient(circle at 86% 8%, rgba(40, 125, 90, 0.20), transparent 24rem),
        linear-gradient(135deg, #fff4dc 0%, #f3eadc 46%, #e6f2df 100%);
    }
    main {
      width: min(1240px, calc(100vw - 36px));
      margin: 0 auto;
      padding: 32px 0 42px;
    }
    h1 {
      margin: 0 0 8px;
      font-size: clamp(30px, 5vw, 58px);
      line-height: 0.98;
      letter-spacing: -0.07em;
    }
    h2 {
      margin: 0 0 12px;
      font-size: 18px;
    }
    .subtitle {
      max-width: 960px;
      margin: 0 0 24px;
      color: var(--muted);
      font-size: 16px;
      line-height: 1.7;
    }
    .layout {
      display: grid;
      grid-template-columns: minmax(340px, 470px) minmax(420px, 1fr);
      gap: 20px;
      align-items: start;
    }
    .card {
      border: 1px solid var(--line);
      border-radius: 30px;
      background: var(--panel);
      box-shadow: var(--shadow);
      backdrop-filter: blur(20px);
    }
    .stage {
      position: sticky;
      top: 18px;
      padding: 22px;
      overflow: hidden;
    }
    .stage::before {
      content: "";
      position: absolute;
      inset: 18px;
      border-radius: 26px;
      background:
        linear-gradient(135deg, rgba(255, 255, 255, 0.62), rgba(255, 255, 255, 0.16)),
        repeating-linear-gradient(90deg, rgba(23, 33, 28, 0.04) 0 1px, transparent 1px 20px);
      pointer-events: none;
    }
    .stage-inner {
      position: relative;
      display: grid;
      gap: 16px;
    }
    .token-panel {
      display: grid;
      gap: 4px;
      justify-items: center;
      padding: 12px;
      border-radius: 22px;
      background: var(--panel-strong);
      border: 1px solid var(--line);
    }
    .mouth-label {
      font-size: clamp(40px, 7vw, 72px);
      font-weight: 900;
      letter-spacing: -0.08em;
    }
    .mouth-meta {
      color: var(--muted);
      line-height: 1.5;
      text-align: center;
    }
    .avatar {
      display: grid;
      place-items: center;
      min-height: 390px;
    }
    svg {
      width: min(380px, 86vw);
      max-height: 420px;
      overflow: visible;
      filter: drop-shadow(0 28px 42px rgba(64, 49, 38, 0.20));
    }
    .controls,
    .play-options {
      display: flex;
      flex-wrap: wrap;
      justify-content: center;
      gap: 10px;
    }
    button {
      border: 0;
      border-radius: 999px;
      padding: 10px 17px;
      color: #fff;
      background: var(--ink);
      cursor: pointer;
      font-weight: 800;
    }
    button.secondary {
      color: var(--ink);
      background: rgba(23, 33, 28, 0.09);
    }
    button.accent {
      background: var(--accent);
    }
    label.option {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 9px 13px;
      border-radius: 999px;
      color: var(--muted);
      background: rgba(255, 255, 255, 0.58);
      border: 1px solid var(--line);
      font-size: 13px;
    }
    .bar {
      height: 10px;
      border-radius: 999px;
      background: rgba(23, 33, 28, 0.10);
      overflow: hidden;
    }
    .bar > span {
      display: block;
      width: 0%;
      height: 100%;
      border-radius: inherit;
      background: linear-gradient(90deg, var(--accent), var(--gold), var(--leaf));
      transition: width 160ms ease;
    }
    .side {
      display: grid;
      gap: 16px;
    }
    .section {
      padding: 20px;
    }
    .text-box,
    .export-box {
      padding: 15px;
      border: 1px solid var(--line);
      border-radius: 18px;
      background: rgba(255, 255, 255, 0.64);
      color: #34423b;
      line-height: 1.8;
    }
    .timeline {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(58px, 1fr));
      gap: 8px;
      max-height: 244px;
      overflow: auto;
      padding: 2px 4px 2px 0;
    }
    .chip {
      border: 1px solid var(--line);
      border-radius: 15px;
      padding: 8px 5px;
      text-align: center;
      background: rgba(255, 255, 255, 0.72);
      color: var(--muted);
      transition: transform 140ms ease, background 140ms ease, color 140ms ease, box-shadow 140ms ease;
    }
    .chip.active {
      transform: translateY(-3px);
      color: #fff;
      background: var(--ink);
      box-shadow: 0 10px 24px rgba(23, 33, 28, 0.24);
    }
    .editor {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
    }
    .slider {
      padding: 12px;
      border-radius: 18px;
      border: 1px solid var(--line);
      background: rgba(255, 255, 255, 0.66);
    }
    .slider-row {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 8px;
      color: var(--muted);
      font-size: 13px;
    }
    input[type="range"] {
      width: 100%;
      accent-color: var(--accent);
    }
    .coverage {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 10px;
    }
    .coverage-item {
      padding: 12px;
      border-radius: 16px;
      background: rgba(255, 255, 255, 0.68);
      border: 1px solid var(--line);
      color: var(--muted);
      line-height: 1.5;
    }
    .coverage-item strong {
      display: block;
      color: var(--ink);
      margin-bottom: 5px;
    }
    textarea {
      width: 100%;
      min-height: 148px;
      resize: vertical;
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 12px;
      background: #fffef9;
      color: #26312c;
      font-family: Consolas, "Cascadia Mono", monospace;
      font-size: 12px;
      line-height: 1.55;
    }
    .hint {
      margin: 8px 0 0;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.6;
    }
    @media (max-width: 960px) {
      .layout {
        grid-template-columns: 1fr;
      }
      .stage {
        position: static;
      }
    }
  </style>
</head>
<body>
  <main>
    <h1>Live2D 嘴型同步可视化测试</h1>
    <p class="subtitle">固定文本覆盖普通话主要声母/韵母和英语常见元辅音。左侧会播放临时合成声音，右侧可以实时调每个音的嘴型参数；嘴部绘制已限制在脸部安全区域内，不再因为参数过大穿出脸外。</p>
    <section class="layout">
      <article class="card stage">
        <div class="stage-inner">
          <div class="token-panel">
            <div class="mouth-label" id="token">准备</div>
            <div class="mouth-meta" id="meta">点击播放后浏览器会启用临时合成声音。</div>
          </div>
          <div class="avatar">
            <svg viewBox="0 0 420 460" role="img" aria-label="嘴型动画示意">
              <defs>
                <linearGradient id="hair" x1="0" x2="1" y1="0" y2="1">
                  <stop offset="0%" stop-color="#ffcfbd"/>
                  <stop offset="52%" stop-color="#f49b83"/>
                  <stop offset="100%" stop-color="#d9795b"/>
                </linearGradient>
                <linearGradient id="skin" x1="0" x2="0" y1="0" y2="1">
                  <stop offset="0%" stop-color="#ffe3c8"/>
                  <stop offset="100%" stop-color="#ffcaa9"/>
                </linearGradient>
                <clipPath id="mouthClip">
                  <ellipse cx="210" cy="303" rx="74" ry="42"></ellipse>
                </clipPath>
              </defs>
              <path d="M104 247 C78 108, 150 44, 210 44 C282 44, 344 110, 316 248 C290 350, 137 350, 104 247Z" fill="url(#hair)"></path>
              <ellipse cx="210" cy="235" rx="116" ry="143" fill="url(#skin)"></ellipse>
              <path d="M94 202 C112 76, 300 68, 326 202 C288 112, 132 112, 94 202Z" fill="url(#hair)"></path>
              <path d="M108 236 C86 238, 79 262, 95 280 C109 294, 126 286, 125 266" fill="#ffcaa9"></path>
              <path d="M312 236 C334 238, 341 262, 325 280 C311 294, 294 286, 295 266" fill="#ffcaa9"></path>
              <ellipse cx="165" cy="226" rx="18" ry="24" fill="#22312b"></ellipse>
              <ellipse cx="255" cy="226" rx="18" ry="24" fill="#22312b"></ellipse>
              <circle cx="171" cy="216" r="6" fill="#fffaf0"></circle>
              <circle cx="261" cy="216" r="6" fill="#fffaf0"></circle>
              <path d="M188 265 Q210 278 232 265" fill="none" stroke="#d7796f" stroke-width="7" stroke-linecap="round"></path>
              <g id="mouthGroup" clip-path="url(#mouthClip)">
                <path id="lipTop" d="" fill="none" stroke="#a83d3d" stroke-width="7" stroke-linecap="round"></path>
                <ellipse id="mouthInner" cx="210" cy="303" rx="24" ry="4" fill="#4f1d28"></ellipse>
                <rect id="teeth" x="182" y="293" width="56" height="9" rx="4" fill="#fff7e8"></rect>
                <ellipse id="mouthLight" cx="200" cy="299" rx="8" ry="2" fill="#ffb3aa" opacity="0.5"></ellipse>
                <path id="lipBottom" d="" fill="none" stroke="#d05b54" stroke-width="7" stroke-linecap="round"></path>
              </g>
              <text id="shapeName" x="210" y="413" text-anchor="middle" fill="#66746d" font-size="18">闭合/停顿</text>
            </svg>
          </div>
          <div class="bar"><span id="progress"></span></div>
          <div class="play-options">
            <label class="option"><input id="audioEnabled" type="checkbox" checked> 播放临时合成声音</label>
            <label class="option"><input id="loopEnabled" type="checkbox" checked> 循环播放</label>
          </div>
          <div class="controls">
            <button id="play" class="accent">播放</button>
            <button id="pause" class="secondary">暂停</button>
            <button id="prev" class="secondary">上一个</button>
            <button id="next" class="secondary">下一个</button>
            <button id="sound" class="secondary">只播当前音</button>
          </div>
        </div>
      </article>
      <div class="side">
        <section class="card section">
          <h2>固定测试文本</h2>
          <div class="text-box" id="testText"></div>
          <p class="hint" id="configPath"></p>
        </section>
        <section class="card section">
          <h2>当前音嘴型参数</h2>
          <div class="editor" id="editor"></div>
          <p class="hint">滑块只影响当前报告中的预览。确认参数后，把下方 JSON 中对应音的 mouth/audio 写回配置文件即可永久生效。</p>
        </section>
        <section class="card section">
          <h2>音素时间线</h2>
          <div class="timeline" id="timeline"></div>
        </section>
        <section class="card section">
          <h2>嘴型覆盖</h2>
          <div class="coverage" id="coverage"></div>
        </section>
        <section class="card section">
          <h2>参数导出</h2>
          <textarea id="configOut" readonly></textarea>
          <p class="hint" id="saveState">尚未保存本页调整。</p>
          <div class="controls">
            <button id="saveLocal" class="accent">保存调整值</button>
            <button id="restoreCurrent" class="secondary">恢复当前音初始值</button>
            <button id="restoreAll" class="secondary">恢复全部初始值</button>
            <button id="downloadAll" class="secondary">下载完整配置</button>
          </div>
        </section>
      </div>
    </section>
  </main>
  <script id="report-data" type="application/json">"""

# ---- HTML 模板后半段：脚本 ----------------------------------------------------------------
_HTML_SUFFIX = """</script>
  <script>
    const report = JSON.parse(document.getElementById("report-data").textContent);
    const initialSamples = report.samples.map((sample) => JSON.parse(JSON.stringify(sample)));
    const samples = report.samples.map((sample) => JSON.parse(JSON.stringify(sample)));
    const storageKey = `visual-companion-mouth-shapes:${report.configPath}`;
    const PARAMS = [
      ["mouthOpen", "张嘴 open"],
      ["mouthWidth", "横向 width"],
      ["mouthRound", "圆唇 round"],
      ["jawDrop", "下颌 jaw"],
      ["smile", "微笑 smile"],
      ["tension", "紧张 tension"]
    ];

    let index = 0;
    let timer = null;
    let audioContext = null;

    const token = document.getElementById("token");
    const meta = document.getElementById("meta");
    const mouthInner = document.getElementById("mouthInner");
    const mouthLight = document.getElementById("mouthLight");
    const lipTop = document.getElementById("lipTop");
    const lipBottom = document.getElementById("lipBottom");
    const teeth = document.getElementById("teeth");
    const shapeName = document.getElementById("shapeName");
    const progress = document.getElementById("progress");
    const timeline = document.getElementById("timeline");
    const coverage = document.getElementById("coverage");
    const editor = document.getElementById("editor");
    const configOut = document.getElementById("configOut");
    const audioEnabled = document.getElementById("audioEnabled");
    const loopEnabled = document.getElementById("loopEnabled");
    const saveState = document.getElementById("saveState");

    document.getElementById("testText").textContent = report.text;
    document.getElementById("configPath").textContent = "参数配置文件：" + report.configPath;

    function clamp(value, min, max) {
      return Math.min(max, Math.max(min, Number(value)));
    }

    function rounded(value) {
      return Number(value).toFixed(2);
    }

    function buildTimeline() {
      timeline.innerHTML = "";
      samples.forEach((sample, sampleIndex) => {
        const chip = document.createElement("button");
        chip.className = "chip";
        chip.textContent = sample.token;
        chip.title = `${sample.group} / ${sample.label} / ${sample.note}`;
        chip.addEventListener("click", () => {
          pause();
          show(sampleIndex, false);
        });
        timeline.appendChild(chip);
      });
    }

    function buildEditor() {
      editor.innerHTML = "";
      PARAMS.forEach(([key, label]) => {
        const wrapper = document.createElement("label");
        wrapper.className = "slider";
        wrapper.innerHTML = `
          <div class="slider-row"><span>${label}</span><strong id="${key}Value">0.00</strong></div>
          <input id="${key}Input" type="range" min="0" max="1" step="0.01">
        `;
        editor.appendChild(wrapper);
        wrapper.querySelector("input").addEventListener("input", (event) => {
          updateCurrentParam(key, Number(event.target.value));
        });
      });
    }

    function buildCoverage() {
      coverage.innerHTML = "";
      Object.entries(report.coverage).forEach(([viseme, tokens]) => {
        const item = document.createElement("div");
        item.className = "coverage-item";
        item.innerHTML = `<strong>${report.shapeNames[viseme] || viseme}</strong><span>${tokens.join(" ")}</span>`;
        coverage.appendChild(item);
      });
    }

    function applySavedSamples() {
      const savedText = localStorage.getItem(storageKey);
      if (!savedText) {
        return;
      }
      try {
        const savedSamples = JSON.parse(savedText);
        if (!Array.isArray(savedSamples)) {
          return;
        }
        const savedByKey = new Map(savedSamples.map((sample) => [sample.soundKey, sample]));
        samples.forEach((sample) => {
          const saved = savedByKey.get(sample.soundKey);
          if (!saved) {
            return;
          }
          PARAMS.forEach(([key]) => {
            if (typeof saved[key] === "number") {
              sample[key] = clamp(saved[key], 0, 1);
            }
          });
        });
        saveState.textContent = "已加载上次保存在本浏览器中的调整值。";
      } catch (error) {
        saveState.textContent = "浏览器保存值读取失败，已使用配置初始值。";
      }
    }

    function updateEditorValues(sample) {
      PARAMS.forEach(([key]) => {
        const input = document.getElementById(`${key}Input`);
        const value = document.getElementById(`${key}Value`);
        input.value = sample[key];
        value.textContent = rounded(sample[key]);
      });
    }

    function updateCurrentParam(key, value) {
      const safeValue = clamp(value, 0, 1);
      const soundKey = samples[index].soundKey;
      samples.forEach((sample) => {
        if (sample.soundKey === soundKey) {
          sample[key] = safeValue;
        }
      });
      show(index, false);
    }

    function saveLocalAdjustments() {
      const payload = samples.map((sample) => ({
        soundKey: sample.soundKey,
        mouthOpen: sample.mouthOpen,
        mouthWidth: sample.mouthWidth,
        mouthRound: sample.mouthRound,
        jawDrop: sample.jawDrop,
        smile: sample.smile,
        tension: sample.tension
      }));
      localStorage.setItem(storageKey, JSON.stringify(payload));
      saveState.textContent = `已保存到本浏览器：${new Date().toLocaleString()}`;
    }

    function restoreCurrentInitial() {
      const soundKey = samples[index].soundKey;
      const initial = initialSamples.find((sample) => sample.soundKey === soundKey);
      if (!initial) {
        return;
      }
      samples.forEach((sample) => {
        if (sample.soundKey !== soundKey) {
          return;
        }
        PARAMS.forEach(([key]) => {
          sample[key] = initial[key];
        });
      });
      show(index, false);
      saveState.textContent = `已恢复 ${soundKey} 的初始嘴型参数，点击“保存调整值”后才会写入浏览器缓存。`;
    }

    function restoreAllInitial() {
      const initialByKey = new Map(initialSamples.map((sample) => [sample.soundKey, sample]));
      samples.forEach((sample) => {
        const initial = initialByKey.get(sample.soundKey);
        if (!initial) {
          return;
        }
        PARAMS.forEach(([key]) => {
          sample[key] = initial[key];
        });
      });
      localStorage.removeItem(storageKey);
      show(index, false);
      saveState.textContent = "已恢复全部初始值，并清除了本浏览器保存值。";
    }

    function drawMouth(sample) {
      const open = clamp(sample.mouthOpen, 0, 1);
      const width = clamp(sample.mouthWidth, 0, 1);
      const round = clamp(sample.mouthRound, 0, 1);
      const jaw = clamp(sample.jawDrop, 0, 1);
      const smile = clamp(sample.smile, 0, 1);
      const tension = clamp(sample.tension, 0, 1);

      const cx = 210;
      const cy = 303 + jaw * 8;
      const rx = clamp(20 + width * 38 - round * 8, 16, 58);
      const ry = clamp(4 + open * 20 + jaw * 11, 3, 34);
      const upperLift = 8 + smile * 10 - tension * 2;
      const lowerDrop = ry + 5 + jaw * 8;

      mouthInner.setAttribute("cx", cx);
      mouthInner.setAttribute("cy", cy);
      mouthInner.setAttribute("rx", rx);
      mouthInner.setAttribute("ry", ry);
      mouthInner.setAttribute("fill", round > 0.68 ? "#3d1825" : "#4f1d28");
      mouthLight.setAttribute("cx", cx - rx * 0.28);
      mouthLight.setAttribute("cy", cy - ry * 0.28);
      mouthLight.setAttribute("rx", clamp(rx * 0.22, 5, 14));
      mouthLight.setAttribute("ry", clamp(ry * 0.18, 1.5, 6));
      lipTop.setAttribute("d", `M ${cx - rx - 8} ${cy - 2} Q ${cx} ${cy - upperLift} ${cx + rx + 8} ${cy - 2}`);
      lipBottom.setAttribute("d", `M ${cx - rx - 7} ${cy + 2} Q ${cx} ${cy + lowerDrop} ${cx + rx + 7} ${cy + 2}`);
      teeth.setAttribute("x", cx - rx * 0.58);
      teeth.setAttribute("y", cy - ry * 0.64);
      teeth.setAttribute("width", rx * 1.16);
      teeth.setAttribute("height", clamp(ry * 0.34, 4, 12));
      teeth.setAttribute("opacity", tension > 0.62 && open > 0.08 ? "0.92" : "0");
    }

    function show(nextIndex, shouldPlayAudio) {
      index = (nextIndex + samples.length) % samples.length;
      const sample = samples[index];
      token.textContent = sample.token;
      shapeName.textContent = sample.label;
      meta.textContent = `${sample.group} · ${sample.viseme} · ${sample.note} · 声音 ${sample.audio.mode}/${sample.audio.syllable}`;
      drawMouth(sample);
      updateEditorValues(sample);
      updateExport();
      progress.style.width = `${((index + 1) / samples.length) * 100}%`;
      [...timeline.children].forEach((child, childIndex) => child.classList.toggle("active", childIndex === index));
      timeline.children[index].scrollIntoView({ block: "nearest", inline: "center" });
      if (shouldPlayAudio) {
        playAudio(sample);
      }
    }

    function ensureAudioContext() {
      if (!audioContext) {
        audioContext = new (window.AudioContext || window.webkitAudioContext)();
      }
      if (audioContext.state === "suspended") {
        audioContext.resume();
      }
      return audioContext;
    }

    function playAudio(sample) {
      if (!audioEnabled.checked || sample.audio.mode === "silence") {
        return;
      }
      const context = ensureAudioContext();
      const now = context.currentTime;
      const duration = Math.max(0.06, sample.durationMs / 1000 * 0.82);
      const gain = context.createGain();
      gain.gain.setValueAtTime(0.0001, now);
      gain.gain.exponentialRampToValueAtTime(Math.max(0.0002, sample.audio.gain), now + 0.018);
      gain.gain.exponentialRampToValueAtTime(0.0001, now + duration);
      gain.connect(context.destination);

      if (sample.audio.mode === "tone" || sample.audio.mode === "mixed") {
        const oscillator = context.createOscillator();
        oscillator.type = sample.mouthRound > 0.65 ? "sine" : "triangle";
        oscillator.frequency.setValueAtTime(Math.max(40, sample.audio.frequencyHz || 220), now);
        oscillator.connect(gain);
        oscillator.start(now);
        oscillator.stop(now + duration);

        if (sample.audio.secondFrequencyHz > 0) {
          const second = context.createOscillator();
          second.type = "sine";
          second.frequency.setValueAtTime(sample.audio.secondFrequencyHz, now);
          const secondGain = context.createGain();
          secondGain.gain.setValueAtTime(Math.max(0.0001, sample.audio.gain * 0.32), now);
          second.connect(secondGain);
          secondGain.connect(context.destination);
          second.start(now);
          second.stop(now + duration);
        }
      }

      if ((sample.audio.mode === "noise" || sample.audio.mode === "mixed") && sample.audio.noise > 0) {
        const bufferSize = Math.max(1, Math.floor(context.sampleRate * duration));
        const buffer = context.createBuffer(1, bufferSize, context.sampleRate);
        const data = buffer.getChannelData(0);
        for (let i = 0; i < bufferSize; i += 1) {
          data[i] = (Math.random() * 2 - 1) * sample.audio.noise;
        }
        const noise = context.createBufferSource();
        const filter = context.createBiquadFilter();
        filter.type = "highpass";
        filter.frequency.setValueAtTime(900 + sample.tension * 1800, now);
        noise.buffer = buffer;
        noise.connect(filter);
        filter.connect(gain);
        noise.start(now);
        noise.stop(now + duration);
      }
    }

    function play() {
      pause();
      ensureAudioContext();
      show(index, true);
      scheduleNext();
    }

    function scheduleNext() {
      timer = window.setTimeout(() => {
        const nextIndex = index + 1;
        if (nextIndex >= samples.length && !loopEnabled.checked) {
          pause();
          return;
        }
        show(nextIndex, true);
        scheduleNext();
      }, samples[index].durationMs);
    }

    function pause() {
      if (timer) {
        window.clearTimeout(timer);
        timer = null;
      }
    }

    function currentSoundConfig(sample) {
      return {
        token: sample.token,
        group: sample.group,
        viseme: sample.viseme,
        label: sample.label,
        note: sample.note,
        mouth: {
          open: Number(sample.mouthOpen.toFixed(2)),
          width: Number(sample.mouthWidth.toFixed(2)),
          round: Number(sample.mouthRound.toFixed(2)),
          jaw: Number(sample.jawDrop.toFixed(2)),
          smile: Number(sample.smile.toFixed(2)),
          tension: Number(sample.tension.toFixed(2))
        },
        audio: sample.audio
      };
    }

    function allSoundConfig() {
      const sounds = {};
      samples.forEach((sample) => {
        sounds[sample.soundKey] = currentSoundConfig(sample);
      });
      return {
        version: 1,
        description: "由嘴型可视化报告导出的调整值。复制或下载后可覆盖 main/config/mouth_shapes.json 中对应字段。",
        parameterGuide: report.parameterGuide,
        audioGuide: report.audioGuide,
        defaultDurationMs: samples[0]?.durationMs || 180,
        sequence: report.sequence,
        sounds
      };
    }

    function updateExport() {
      const sample = samples[index];
      configOut.value = JSON.stringify({
        soundKey: sample.soundKey,
        config: currentSoundConfig(sample)
      }, null, 2);
    }

    async function copyText(text) {
      configOut.value = text;
      configOut.select();
      if (navigator.clipboard) {
        await navigator.clipboard.writeText(text);
      } else {
        document.execCommand("copy");
      }
    }

    function downloadConfig() {
      const text = JSON.stringify(allSoundConfig(), null, 2);
      const blob = new Blob([text + "\\n"], { type: "application/json;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "mouth_shapes_adjusted.json";
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
      saveState.textContent = "已下载 mouth_shapes_adjusted.json，可检查后覆盖配置文件。";
    }

    buildTimeline();
    buildEditor();
    buildCoverage();
    applySavedSamples();
    show(0, false);

    document.getElementById("play").addEventListener("click", play);
    document.getElementById("pause").addEventListener("click", pause);
    document.getElementById("prev").addEventListener("click", () => {
      pause();
      show(index - 1, true);
    });
    document.getElementById("next").addEventListener("click", () => {
      pause();
      show(index + 1, true);
    });
    document.getElementById("sound").addEventListener("click", () => playAudio(samples[index]));
    document.getElementById("saveLocal").addEventListener("click", saveLocalAdjustments);
    document.getElementById("restoreCurrent").addEventListener("click", restoreCurrentInitial);
    document.getElementById("restoreAll").addEventListener("click", restoreAllInitial);
    document.getElementById("downloadAll").addEventListener("click", downloadConfig);
  </script>
</body>
</html>
"""


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""

    parser = argparse.ArgumentParser(description="生成 Live2D 嘴型同步可视化测试报告。")
    parser.add_argument("--html-report", type=Path, default=DEFAULT_HTML_REPORT, help="HTML 报告输出路径")
    parser.add_argument("--json-report", type=Path, default=DEFAULT_JSON_REPORT, help="JSON 报告输出路径")
    parser.add_argument("--mouth-config", type=Path, default=None, help="嘴型和临时声音配置路径")
    parser.add_argument("--open", action="store_true", help="生成后自动打开 HTML 报告")
    parser.add_argument("--duration-ms", type=int, default=None, help="每个音素片段的播放时长，默认读取配置")
    return parser.parse_args()


def main() -> int:
    """脚本入口。"""

    args = parse_args()
    if args.duration_ms is not None and args.duration_ms <= 0:
        print("duration-ms 必须大于 0。")
        return 2

    errors = validate_mouth_shape_config(args.mouth_config)
    if errors:
        print("嘴型配置校验失败：")
        for error in errors:
            print("- {0}".format(error))
        return 1

    samples = build_visual_mouth_test_sequence(duration_ms=args.duration_ms, config_path=args.mouth_config)
    payload = build_report_payload(samples, args.mouth_config)

    try:
        args.html_report.parent.mkdir(parents=True, exist_ok=True)
        args.json_report.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"错误：无法创建报告目录：{exc}", file=sys.stderr)
        return 1

    try:
        args.html_report.write_text(render_html(payload), encoding="utf-8")
    except OSError as exc:
        print(f"错误：HTML 报告写入失败 [{args.html_report}]：{exc}", file=sys.stderr)
        return 1

    try:
        args.json_report.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        print(f"错误：JSON 报告写入失败 [{args.json_report}]：{exc}", file=sys.stderr)
        return 1

    print("=== Live2D 嘴型可视化测试 ===")
    print("HTML 报告：{0}".format(args.html_report))
    print("JSON 报告：{0}".format(args.json_report))
    print("嘴型配置：{0}".format(args.mouth_config or default_mouth_config_path()))
    print("测试片段：{0}".format(len(samples)))
    print("固定文本：{0}".format(VISUAL_MOUTH_TEST_TEXT))

    if args.open:
        webbrowser.open(args.html_report.resolve().as_uri())
    return 0


if __name__ == "__main__":
    sys.exit(main())
