# VeyraSoul V2

`new_code/` 是虚拟陪伴机器人 V2 的独立实现。旧系统保持冻结，只作为行为参照与模型资源迁移来源；V2 不在旧代码上继续叠加功能。

> **当前运行边界：** 评委访问的 `robot.veyralux.org` 与 ELF2 必须继续运行 V1。V2 只允许在开发电脑和自动化环境中开发验证，暂不上传、安装或切换到开发板。仓库内的 V2 systemd/Cloudflare 文件仅是未来部署草案，激活脚本默认拒绝切换。

## 产品目标

让角色表现为持续存在、能感知、能记住、具有情绪连续性的“虚拟生命体”，同时满足 RK3588 单板运行、公网访问和低等待感交互。

设计不变量：

1. **感知持续、回答取快照**：对话使用当下可用的最新感知，不为一轮回答阻塞等待新的视觉推理。
2. **最新值优先**：视频、姿态和语义不排长队；过期输入直接被新输入覆盖。
3. **可取消代际**：每轮回复拥有 `generation`；新一轮或取消事件使旧 LLM、TTS、音频和提交结果失效。
4. **文字与声音同步**：对应音频可播放时才展示该段文字，不采用“全文先显示、TTS 很久后跟上”。
5. **本地预览与机器感知解耦**：摄像头 `<video>` 请求最高 60 FPS 本地预览；上传关键帧和语义更新使用更低频率，不能拖慢预览。
6. **情绪是连续状态**：用 valence/arousal/dominance/affinity/trust 驱动语气和参数曲线，而不是随机硬切表情。
7. **板端隐私优先**：视觉、ASR、TTS、记忆和 RAG 目标部署在 ELF2；云端 LLM 只接收裁剪后的语言上下文。
8. **VoxCPM 永不自动切换**：只有用户主动选择后才允许加载。

## 当前实现状态（以代码为准）

### 已实现并有自动化测试覆盖

- SQLite WAL 记忆、FTS5 trigram 检索、向量候选融合、事实 revision；
- 确定性 Memory Curator：事实/偏好规范化去重、来源可靠度、弱冲突保护、明确纠正 revision 与完整 provenance；
- per-session `generation`、取消后禁止旧结果写入记忆；
- DeepSeek SSE 流式适配器，显式关闭 thinking；
- 句级 LLM → TTS 管线和二进制 WebSocket 帧；
- 服务端先发音频、再发配对文本事件；前端在该音频实际开始播放时展示文本；
- 本地摄像头画中画、麦克风/摄像头/挂断控制、AudioWorklet 20 ms PCM16；
- 本地视频预览与 500 ms 一次的 JPEG 关键帧采样解耦；5 秒 latest-value 语义调度器已接入 Gateway；
- PC 主舞台和移动端响应式通话布局；
- 本地 Cubism/Pixi runtime、真实 Strawberry_Rabbit 模型、自适应 4096/1024 纹理、60 FPS ticker、连续头眼/呼吸/眨眼/口型参数混合；
- 从实际 WAV PCM 预计算 20 ms RMS 包络并按播放时间驱动 Live2D 嘴形。
- 连续情感证据、真实时间衰减和 generation-safe `avatar.intent` 已贯通后端与 Live2D；ASR partial 会立即触发 listening/barge-in，旧代意图不会污染新轮。

### 已有适配器或界面骨架，但尚未完成真实板端闭环

- sherpa-onnx streaming Zipformer ASR 与 Kokoro/Matcha/VITS TTS 适配器已经存在，仍需用 ELF2 上的真实模型目录、麦克风和声音做端到端验证；
- Gateway 已把 JPEG 接入单槽 latest-value 调度器，并通过板内 `/analyze` VLM HTTP 适配器发布 `VisualSnapshot`；仓库内尚不包含真正的 RK3588 VLM worker，也未接入 RKNN 快视觉；
- 新鲜 `VisualSnapshot` 已无条件进入每轮动态上下文并发布给前端；仍需用真实板内 VLM 服务验证准确度、超时和资源占用；
- Live2D 真实模型、连续 AvatarIntent 和 RMS 口型已接通，并通过桌面/竖屏/横屏 Chromium 拟真验证；音素级 viseme、语义重音、完整动作时间轴和目标手机 GPU 实测尚未完成；
- UI 已做桌面/移动端布局与构建检查，尚未完成覆盖主流手机浏览器的真机矩阵；
- V2 systemd、同源静态托管、Cloudflare Tunnel 单元与一键启动/回滚脚本已进入仓库，但已加显式激活保护；在比赛评审期间不得替换开发板与公网 V1。

任何目标时延、60 FPS 和内存预算在板端实测前都属于 **SLO/验收门槛**，不是已达成的性能声明。

## 目录

```text
new_code/
├── backend/                 # 会话编排、记忆/RAG、模型适配器、ASGI Gateway
├── web/                     # PC 优先、移动端完整的 Preact + TypeScript 通话界面
├── config/                  # 稳定角色提示词（不得放密钥）
├── docs/                    # 架构、协议、部署、UX、SLO 和路线图
├── artifacts/               # 基准结果；截图等本地产物默认不提交
└── scripts/                 # 检查脚本
```

## 本机检查

```powershell
cd E:\CODE\Visual_Companion_Robot\new_code\backend
python -m pip install -e ".[gateway,models,test]"
python -m pytest -q

cd ..\web
npm ci
npm run check
npm run build

cd ..
.\scripts\check.ps1
```

## 启动开发界面

```powershell
cd E:\CODE\Visual_Companion_Robot\new_code\web
npm run dev
```

浏览器媒体权限只在安全上下文中可用：本机开发可使用 `http://localhost:5174`，手机/公网必须使用 HTTPS。前端默认连接同源 `/v2/realtime`。

板端 Gateway 的依赖、模型目录、环境变量和启动方式见 [`docs/deployment-elf2.md`](docs/deployment-elf2.md)。

## 文档索引

- [`docs/architecture.md`](docs/architecture.md)：目标架构、当前纵向链路和模块边界
- [`docs/video-call-ux.md`](docs/video-call-ux.md)：视频通话式交互、媒体频率和端侧适配
- [`docs/protocol.md`](docs/protocol.md)：Realtime Protocol v2
- [`docs/latency-slo.md`](docs/latency-slo.md)：目标时延、测量口径和当前证据边界
- [`docs/deployment-elf2.md`](docs/deployment-elf2.md)：ELF2 配置与启动
- [`docs/implementation-roadmap.md`](docs/implementation-roadmap.md)：已完成、进行中和验收门槛
