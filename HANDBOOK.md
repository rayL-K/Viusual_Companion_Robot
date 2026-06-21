# Visual Companion Robot — 交接手册

文档版本：2026-06-21
交接目标：让新线程或后续开发者在不读取旧聊天记录的情况下，快速接上当前比赛项目。

## 1. 当前仓库状态

| 项目 | 状态 |
| --- | --- |
| 当前本地路径 | `E:\CODE\Visual_Companion_Robot` |
| 当前分支 | `dev/local-vision-emotion-context` |
| 最近已知基线提交 | `2938eaa docs: 闭环架构图改用 Mermaid 渲染` |
| 已合并 PR | PR #1 `完善 Live2D 控制台与多模态交互`，PR #2 `聊天气泡交互优化：拖拽/缩放/字体 + 角色右键拖拽 + 文件拖拽回画布` |
| 当前主开发区域 | `main/live2d_stage/` |
| 目标运行环境 | Windows 本机开发，Firefly/RK3588 板端迁移 |

当前实际运行的 MediaPipe 资源是：

```text
main/live2d_stage/src/mediapipe/vision_bundle.js
main/live2d_stage/public/mediapipe/vision_bundle.js
```

历史重复文件 `vision_bundle.mjs` 已不在当前运行链路中。

## 2. 项目一句话

这是一个基于 Firefly/RK3588 的多模态虚拟陪伴机器人：浏览器端负责 Live2D 展示、摄像头、麦克风和交互 UI；本地控制服务负责 LLM、VoxCPM2 TTS、记忆和控制计划；后续迁移到 Firefly 时逐步替换为端侧模型。

## 3. 快速启动

PowerShell 7 可选；统一 `.bat` 入口也兼容 Windows 10 自带的 PowerShell 5.1。

统一启动入口：

```bat
tools\launchers\live2d_stage.bat
```

手动启动前端：

```powershell
Push-Location -LiteralPath .\main\live2d_stage
npm install
npm run dev
Pop-Location
```

控制服务由统一启动脚本菜单管理。开发时如果只看前端静态页面，可以先只跑 Vite；如果要 LLM、TTS、语音回复，需要同时启动本地控制服务。

## 4. 验证命令

前端静态检查：

```powershell
Push-Location -LiteralPath .\main\live2d_stage
npm run check
Pop-Location
```

Python 测试：

```powershell
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
conda run -n visual-companion-robot python -m pytest main\tests -q
```

说明：Windows 上 `conda run` 遇到中文或异常字符输出时可能触发 GBK 编码问题，所以测试前显式设置 UTF-8 环境变量。

## 5. 当前模块边界

| 模块 | 位置 | 当前用途 |
| --- | --- | --- |
| Live2D 舞台 | `main/live2d_stage/src/stage.js` | 主渲染循环、UI 状态、动作盘、摄像头/麦克风入口、LLM/TTS 请求。 |
| 浏览器视觉感知 | `main/live2d_stage/src/perception-client.js` | MediaPipe FaceLandmarker，输出头部角度、眨眼、嘴部、微笑和情绪，并向 LLM 提供视觉上下文。 |
| FER+ 情绪适配 | `main/live2d_stage/src/emotion-onnx-client.js` | 把浏览器人脸裁剪发送到本机 8766 服务；服务不可用时沿用 blendshape 规则。 |
| MediaPipe 本地资源 | `main/live2d_stage/src/mediapipe/` 与 `main/live2d_stage/public/mediapipe/` | 离线加载 Tasks Vision JS、WASM 和 face_landmarker 模型。 |
| 控制服务 | `main/scripts/live2d_control_server.py` | 提供 `/chat`、`/tts`、`/voices` 等接口。 |
| VoxCPM2 本地推理 | `main/src/visual_companion_robot/voice/voxcpm_local.py` | 项目内本地 TTS 推理入口，Firefly 迁移时优先沿用。 |
| 记忆模块 | `main/src/visual_companion_robot/brain/memory.py` | SQLite 对话记忆骨架。 |
| 旧 Python 视觉参考 | `main/visual-perception/` | 保留为参考，不是当前主路径。 |

## 6. 视觉感知当前实现

当前视觉方案已经从 Python 后端转为浏览器端 MediaPipe，原因是可以避开 Python 依赖地狱和摄像头占用冲突。

### 6.1 数据流

```text
浏览器摄像头 video
  -> perception-client.js
  -> MediaPipe FaceLandmarker
  -> getLive2DParams()
  -> stage.js updateModelParameters()
  -> Live2D 参数
```

### 6.2 输出字段

`perceptionClient.getLive2DParams()` 返回：

| 字段 | 来源 | 映射目标 |
| --- | --- | --- |
| `angleX` | 鼻尖相对人脸框的横向偏移 | `ParamAngleX` |
| `angleY` | 鼻尖相对人脸框的纵向偏移 | `ParamAngleY` |
| `bodyAngleZ` | 双眼外角连线角度 | `ParamBodyAngleZ` |
| `mouthSmile` | `mouthSmileLeft/Right` blendshape | `ParamMouthSmile` |
| `mouthOpen` | `jawOpen` blendshape | `ParamMouthOpenY` |
| `eyeOpen` | `1 - eyeBlink` | `ParamEyeLOpen`、`ParamEyeROpen` |
| `emotion` | FER+ 或规则打分结果 | 状态栏、Live2D 状态与 LLM 上下文 |
| `emotionSource` | `ferplus` 或 `blendshape_rule` | 调试当前情绪来源 |
| `fullScores` | 归一化情绪分数 | LLM 上下文与后续表情联动 |

### 6.3 与鼠标/音频的关系

在 `stage.js` 的 `updateModelParameters()` 中：

```text
如果摄像头追踪有效：
  使用视觉参数驱动头部、嘴、眼睛；
  禁用鼠标头部/眼球跟随；
  摄像头嘴部开合会覆盖音频口型。

如果摄像头追踪无效：
  使用鼠标跟随和自然晃动；
  使用音频口型同步。
```

这个策略可以避免“摄像头驱动”和“鼠标驱动”互相抢参数。

## 7. 已经踩过的坑

### 7.1 Python 视觉后端暂时不要作为主线

曾尝试 Python WebSocket + ONNX 模型方案，但每个模型下载源都需要单独验证，成本高且不稳定。还尝试过 Python MediaPipe，但 `mediapipe -> tensorflow docs -> keras -> scipy/numpy ABI` 链路在当前 Windows 环境出现依赖冲突。

更关键的问题是摄像头占用：浏览器 `getUserMedia()` 和 Python `cv2.VideoCapture()` 同时抢同一个摄像头，在 Windows 与 Linux 上都可能失败。当前主线应继续使用浏览器端摄像头。

### 7.2 MediaPipe 资源有两个位置

当前 `perception-client.js` 通过动态 import 加载：

```text
main/live2d_stage/src/mediapipe/vision_bundle.js
```

WASM 与模型通过浏览器静态路径加载：

```text
main/live2d_stage/public/mediapipe/wasm/
main/live2d_stage/public/mediapipe/model/face_landmarker.task
```

如果升级 MediaPipe，需要同时确认 `src/mediapipe/` 与 `public/mediapipe/` 两侧资源是否匹配。

### 7.3 情绪识别使用本机 FER+ 服务

当前主路径是：浏览器用 MediaPipe 定位人脸，将 64×64 裁剪发送到 `http://127.0.0.1:8766/emotion`；Python 服务使用 FER+ ONNX 推理。如果服务未启动、模型缺失或请求失败，前端继续使用 blendshape 规则，不中断 Live2D。

当前前端预处理约定：

```text
输入：1 x 1 x 64 x 64
颜色：灰度
归一化：0..1
输出：neutral, happy, surprise, sad, angry（由 FER+ 8 类合并）
```

## 8. 近期优先级

| 优先级 | 任务 | 说明 |
| --- | --- | --- |
| P0 | 真实浏览器回归 | 启动 Live2D 舞台，验证摄像头开启、面部追踪、鼠标回退、TTS 与聊天链路。 |
| P0 | 真实浏览器情绪回归 | 下载 FER+ 模型、启动 8766 服务，用真实摄像头观察不同表情下的识别稳定性。 |
| P1 | 情绪联动 Live2D 表情 | 将 `emotion/fullScores` 映射到 Live2D 表情或动作盘效果。 |
| P1 | 物体检测 | 浏览器端接入轻量 YOLO/RT-DETR ONNX，让角色能看见桌面物品。 |
| P1 | 视觉上下文提示词优化 | 当前 `/chat` 已收到视觉上下文，后续需要让 LLM 更稳定地利用这些字段。 |
| P2 | Firefly 迁移验证 | 在 Firefly Chromium 或替代前端环境中验证 WebGL、WASM、摄像头和音频权限。 |

## 9. 建议的下一步开发顺序

1. 跑 `npm run check`、Vite build 和 Python 测试，确认 FER+ 适配与视觉上下文链路没有破坏现有功能。
2. 启动 Live2D 舞台，打开摄像头，人工验证头部、眼神、表情和麦克风输入。
3. 用真实摄像头测试 `emotionSource=ferplus` 时的情绪稳定性，必要时增加置信度阈值或时间平滑。
4. 将视觉上下文写进 LLM 提示词策略，让角色能主动提到用户表情、是否看向屏幕、是否正在说话。
5. 再接入物体检测，先做少量可解释物体，例如人、手机、杯子、书。

## 10. 关键设计取舍

### 10.1 为什么当前主线在浏览器端做视觉

浏览器已经拥有摄像头视频流，直接在浏览器端做 FaceLandmarker 可以避免跨进程传帧和摄像头抢占。对当前比赛展示来说，这是更稳的路线。

### 10.2 为什么不立刻上 RKNN/NPU

RK3588 NPU 是最终亮点之一，但现在项目还在交互闭环打磨阶段。先在浏览器和本地服务中把“看见用户 -> 理解状态 -> 角色反馈”跑顺，再迁移模型到 RKNN，风险更低。

### 10.3 为什么保留 `main/visual-perception/`

它是 Python 视觉路线的参考代码和失败经验记录。短期不要删除，除非新视觉方案完全稳定并有文档替代。

## 11. 常用路径

```text
README.md
HANDBOOK.md
main/live2d_stage/src/stage.js
main/live2d_stage/src/perception-client.js
main/live2d_stage/src/emotion-onnx-client.js
main/live2d_stage/src/mediapipe/vision_bundle.js
main/live2d_stage/public/mediapipe/model/face_landmarker.task
main/src/visual_companion_robot/perception/emotion.py
main/src/visual_companion_robot/perception/emotion_server.py
main/live2d_stage/public/mediapipe/wasm/
main/scripts/live2d_control_server.py
main/src/visual_companion_robot/voice/voxcpm_local.py
main/src/visual_companion_robot/brain/memory.py
main/docs/tasks.md
```

## 12. 给新线程的第一句话

可以直接这样开新线程：

```text
请读取 E:\CODE\Visual_Companion_Robot\HANDBOOK.md，并接手 Visual Companion Robot。先检查 git 状态，然后验证浏览器端视觉上下文链路：摄像头 -> perception-client.js -> emotion-onnx-client.js/规则情绪 -> stage.js /chat 请求 -> live2d_control_server.py sanitize_vision_context。
```
