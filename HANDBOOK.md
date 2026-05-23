# 视觉感知模块 — 工作移交 & 头脑风暴文档

## 一、当前进度

### 1.1 已完成：浏览器端面部追踪 (perception-client.js)

位于 `main/live2d_stage/src/perception-client.js`，完全在浏览器中运行。

**技术栈：**
- MediaPipe FaceLandmarker (Tasks-Vision API) — 478 个 3D 面部关键点
- 52 组 ARKit FACS blendshapes — 表情测量
- 所有模型已下载到 `public/mediapipe/`，完全离线加载

**输入：** `<video>` 元素（摄像头预览）
**输出：** `getLive2DParams()` 返回:

| 参数 | 来源 | 用途 |
|------|------|------|
| `angleX/Y` | 鼻尖相对人脸框偏移 | Live2D ParamAngleX/Y |
| `bodyAngleZ` | 双眼外角连线角度 | Live2D ParamBodyAngleZ |
| `mouthSmile` | mouthSmile blendshape | Live2D ParamMouthSmile |
| `mouthOpen` | jawOpen blendshape | Live2D ParamMouthOpenY |
| `browRaise` | browInnerUp + browOuterUp | (预留) |
| `eyeOpen` | 1 - eyeBlink | Live2D ParamEyeLOpen/ROpen |
| `emotion` | 加权打分 → 7 类 | 状态栏显示 |
| `fullScores` | 7 类情绪完整分数 | 后续 AI 决策 |

**情绪检测：** 基于 52 组 Blendshapes 的加权打分系统

| 情绪 | 正向指标 | 反向抑制 |
|------|---------|---------|
| happy | mouthSmile + cheekSquint ×1.0 | mouthFrown + browDown ×0.5 |
| sad | browDown + mouthFrown + mouthShrugUpper ×1.0 | smile ×0.7 |
| surprise | browUp + jawOpen + eyeWide + mouthStretch ×1.0 | smile + browDown ×0.3 |
| angry | browDown + mouthPress + eyeSquint ×1.0 | smile ×0.5 |
| fear | browUp + eyeWide + jawOpen + mouthShrugUpper ×1.0 | smile + browDown ×0.3 |
| disgust | noseSneer + upperLipRaise + cheekPuff ×1.0 | — |

平滑：5 帧滑动平均，减少 jitter。

### 1.2 Live2D 参数映射 (stage.js)

在 `updateModelParameters()` 中：

```
有摄像头追踪时：
  ParamAngleX/Y      ← 鼻尖偏移（鼠标禁用）
  ParamBodyAngleZ    ← 歪头（鼠标禁用）
  ParamMouthSmile    ← blendshape
  ParamMouthOpenY    ← jawOpen blendshape（覆盖音频口型）
  ParamEyeLOpen/ROpen ← eyeBlink blendshape
  ParamEyeBallX/Y    ← 归零（鼠标禁用）
  ParamBodyAngleX/Y  ← 归零（鼠标禁用）

无摄像头追踪时：
  applyPointerParameters() ← 鼠标跟随（含眼球方向）
  音频口型同步 ParamMouthOpenY
```

### 1.3 构架示意

```
index.html
  └─ /src/stage.js          — Live2D 主循环, Pixi.js 渲染
       ├─ /src/perception-client.js  — MediaPipe 面部追踪
       │    └─ import("./mediapipe/vision_bundle.js")  — 动态加载
       │         └─ /mediapipe/wasm/vision_wasm_internal.* — WASM 引擎
       │         └─ /mediapipe/model/face_landmarker.task  — 3.7MB 模型
       └─ live2dcubismcore.min.js  — Cubism SDK (CDN)
       └─ pixi.js + pixi-live2d-display (CDN)
```

---

## 二、优化历程 & 难点

### 2.1 第一轮：Python 后端方案 (放弃)

**目标：** Python WebSocket 服务，用 ONNX 模型做人脸+情绪+姿态
**问题：** 每个模型都需要单独下载和验证下载链接

| 模型 | 下载链接 | 状态 |
|------|---------|------|
| SCRFD (人脸检测) | 用户已下载 `scrfd_person_2.5g.onnx` | ✅ 可用 |
| PFLD-106 (关键点) | GitHub 仓库已删/改名 → 404 | ❌ 链接失效 |
| Mini-Xception (情绪) | DeepFace 仓库路径变更 → 404 | ❌ 链接失效 |
| MoveNet (姿态) | TF Hub URL 需要翻墙 | ❌ 网络限制 |

**结论：** 手动验证模型下载链接成本高，不可靠。Python 端还要搞定摄像头权限冲突（浏览器已占摄像头）。

### 2.2 第二轮：Python MediaPipe (放弃)

**尝试：** `pip install mediapipe`，用 Python 的 `mp.solutions.face_mesh`
**问题：** 依赖地狱

```
mediapipe 0.10.35
  └─ import mediapipe.tasks.python
       └─ import tensorflow.tools.docs   ← 仅为 doc_controls！
            └─ import keras → import scipy
                 └─ scipy.special._multiufuncs 崩溃
                      └─ numpy 版本 ABI 不匹配 → RecursionError
```

**修复尝试：**
1. 升级 scipy → 新版本仍不兼容 ❌
2. 降级 scipy → 1.10.1 可行 ✅
3. 但 `pip install mediapipe` 被锁定到特定版本，升级 scipy 导致其他包损坏
4. 最终方案：修改 `mediapipe/tasks/python/core/optional_dependencies.py`，把 `except ModuleNotFoundError` 改为 `except (ModuleNotFoundError, Exception)` 使其在递归崩溃时静默降级

**🔴 隐藏难点：** Python 端的 Camera 与浏览器端 Camera 冲突。Windows 下 `cv2.VideoCapture(0)` 和 `navigator.mediaDevices.getUserMedia()` 同时访问同一摄像头可能失败（取决于驱动）。Firefly 上同为 Linux 系统，这个冲突会更加严重（v4l2 不允许同时打开设备）。

### 2.3 第三轮：浏览器端 MediaPipe (当前方案)

**切换原因：** 彻底消除 Python 依赖 + 摄像头进程冲突。

| 尝试方案 | 结果 |
|---------|------|
| `@mediapipe/tasks-vision` npm 包 → Vite import | Vite 无法正确处理 WASM 模块 |
| CDN `<script>` 加载 → 全局 `Vision` 对象 | 下载的文件为 ESM 格式，`<script>` 加载时报 `Unexpected token 'export'` |
| 存入 `public/` → dynamic `import()` | Vite 阻止从 `/public` import |
| 存入 `src/mediapipe/` → `import("./mediapipe/vision_bundle.js")` | **✅ 最终方案** |

**🔴 隐藏难点：** `FaceDetector` (浏览器原生 API) 在 Chrome/Edge 中可能被策略禁用。本项目中用户浏览器不支持，所以必须用 MediaPipe。

### 2.4 第四轮：集成调优

| 问题 | 原因 | 解决方案 |
|------|------|---------|
| 角色仍然朝向鼠标 | `applyPointerParameters()` 在感知前执行 | 把感知检测提升到鼠标跟随前，追踪时清空眼/体参数 |
| MediaPipe 内部日志刷屏 | WASM C++ 日志通过 Emscripten stdout 输出 | 在 `<script>` 中 hook `console.warn`/`console.log` 过滤 |
| 打开摄像头时闪烁 | 视频流未稳定就启动检测，状态栏频繁更新 | +500ms 启动延迟 + 情绪变化才更新状态栏 |
| `bs is not iterable` | `faceBlendshapes[0]` 是 `{categories: [...]}` 而非数组 | 改为 `faceBlendshapes[0]?.categories` |
| 情绪不准确/抖动 | 阈值法太粗糙 | 加权打分 + 5 帧滑动平均 + 互斥抑制 |

---

## 三、隐藏难点 & 边界

### 3.1 尚未解决的问题

1. **❌ 情绪精度有限** — 当前基于 Blendshapes 加权规则，远不如端到端 CNN 模型（如 Mini-Xception ONNX）准确。建议引入 `onnxruntime-web` + Mini-Xception ONNX 模型做真正 CNN 推理。

2. **⚠️ WASM 兼容性** — MediaPipe vision_bundle.js 依赖 WebAssembly + WebGL 2.0。部分老设备可能不支持。建议加 fallback 到 OpenCV Haar。

3. **⚠️ MediaPipe 版本锁定** — `vision_bundle.js` 和 `wasm/` 已下载到本地，如果升级 MediaPipe 版本需要重新下载。

4. **⚠️ `public/mediapipe/vision_bundle.js` 和 `src/mediapipe/vision_bundle.js` 是同一文件的两个副本** — 前者用于静态服务，后者用于 Vite import。如果更新其中一个需要同步另一个。

### 3.2 已知边界

- **单人追踪：** `numFaces: 1`，只追踪第一个人脸
- **光照敏感：** MediaPipe FaceLandmarker 在强背光/全黑环境下检测率下降
- **大角度转头：** 侧脸 > 45° 时关键点精度下降
- **速度：** 15fps 检测间隔（66ms），不影响 60fps Live2D 渲染

---

## 四、未来规划 & 优先级 (Codex 任务)

### 4.1 Firefly 迁移架构建议

```
Firefly (RK3588, 6 TOPS NPU)
  ┌─────────────────────────────────────┐
  │  Web Browser (Chromium, 硬件加速)     │
  │  ├─ MediaPipe FaceLandmarker (GPU)   │ ← 当前功能
  │  ├─ Live2D 渲染 (WebGL)             │
  │  └─ onnxruntime-web 推理             │
  │       ├─ Mini-Xception ONNX (情绪)   │ ← 待接入
  │       └─ YOLOv8n ONNX (物体检测)     │ ← 待接入
  │                                     │
  │  Web Worker                          │
  │  ├─ 音频采集 → Whisper base STT      │ ← 待接入
  │  └─ TinyLLaMA 1.1B (推理对话)        │ ← 待接入
  └─────────────────────────────────────┘
```

### 4.2 优先级列表

| 优先级 | 任务 | 说明 |
|--------|------|------|
| **P0** | 情绪模型升级 | **改用手写规则 → ONNX Runtime Web + Mini-Xception**。详见第 4.3 节 |
| **P1** | YOLOv8n 物体检测 | 让角色"看懂"桌面物品。`onnxruntime-web` 加载 `yolov8n.onnx` |
| **P1** | 情绪 → Live2D 表情联动 | 将 7 种情绪分数直接映射到 Live2D 表情参数 |
| **P2** | 空间深度估计 | MediaPipe Iris / Depth 估计人脸距离，角色距离响应 |
| **P2** | CLIP 场景理解 | MobileCLIP 对摄像头帧做零样本场景分类 |
| **P3** | 手势识别 | MediaPipe Hands + gesture classification |
| **P3** | Firefly NPU 加速 | RK3588 NPU 跑 ONNX 模型 (RKNN 转换) |

### 4.3 情绪模型接入步骤 (P0)

```js
// 1. npm install onnxruntime-web
// 2. 下载 Mini-Xception ONNX 模型到 public/mediapipe/model/emotion.onnx
//    模型来源: https://github.com/serengil/deepface (模型路径已变)
//    或直接用这个: pip install deepface 后从 site-packages 找 mini_xception.onnx
// 3. 在 perception-client.js 中添加:
import * as ort from "onnxruntime-web";
// 4. 每帧取 MediaPipe 检测到的人脸 crop (48x48 gray)
// 5. ort.InferenceSession.create("emotion.onnx") → run()
// 6. 输出: [angry, disgust, fear, happy, sad, surprise, neutral] 概率
```

### 4.4 YOLOv8n 接入步骤 (P1)

```js
// 1. npm install onnxruntime-web
// 2. 下载 https://github.com/ultralytics/assets/releases/download/v8.3.0/yolov8n.onnx
// 3. 新建 src/perception-objects.js (独立模块，不阻塞面部追踪)
// 4. 每 N 帧 (e.g. 每 30 帧) 跑一次检测
// 5. 输出: [{class: "cell phone", confidence: 0.85, bbox: [x,y,w,h]}, ...]
// 6. 将此信息传给 LLM 用于场景理解
```

### 4.5 LLM 对话接入 (P2)

Firefly 硬件限制：
- 只适合跑 1.1B~1.5B 量化模型
- 建议: TinyLLaMA 1.1B Q4 / Qwen 1.5B Q4
- 推理框架: llama.cpp 或 MLX (如迁移到 Mac)
- 不通过 ONNX Runtime Web 跑（太慢），用本地 Python 服务或 cpp 独立进程

输入上下文应包括：
```
当前时间: 下午 3:00
用户面部: {head_pose: {yaw: 15, pitch: -5}, emotion: "happy", emotion_scores: {...}}
场景物品: ["cell phone", "coffee cup", "book"]
最近对话: ["你好", "今天天气怎么样"]
响应策略: 根据情绪调整语气（happy → 活泼, sad → 温柔）
```

---

## 五、项目结构快照

```
Visual_Companion_Robot/
├── .gitignore
├── main/
│   ├── live2d_stage/                 ← 当前活跃工作目录
│   │   ├── index.html                ← 入口 (加了 console 日志过滤)
│   │   ├── vite.config.mjs           ← Vite 配置 (移除了 Python 插件)
│   │   ├── package.json
│   │   └── src/
│   │       ├── stage.js              ← Live2D 主循环
│   │       ├── perception-client.js  ← 面部追踪 + 情绪
│   │       ├── mediapipe/
│   │       │   └── vision_bundle.js  ← MediaPipe 库 (dynamic import)
│   │       └── ... (其他原始 UI 文件)
│   │   └── public/
│   │       └── mediapipe/
│   │           ├── vision_bundle.js
│   │           ├── model/face_landmarker.task
│   │           └── wasm/vision_wasm_internal.{js,wasm}
│   │
│   └── visual-perception/            ← 旧 Python 参考代码
│       ├── server.py                 ← 原 WebSocket 服务端
│       ├── pipeline.py               ← 原推理管线 (已重写为 MediaPipe)
│       └── models/                   ← 原 ONNX 模型代码 (无权重)
```

---

## 六、快速启动

```bash
# 当前开发环境 (本地 PC)
npm --prefix main/live2d_stage run dev
# 打开 http://127.0.0.1:5174
# 点击 检测摄像头 → 开启摄像头

# Vite 配置
cd main/live2d_stage
npm install   # 安装依赖 (如 playwright)
npm run dev   # 启动开发服务器 (localhost:5174)
```

---

*文档版本: 2026-05-24*
*移交目标: Codex / 后续开发者*
*原始作者: Reasonix Code (visual-perception 子代理)*
