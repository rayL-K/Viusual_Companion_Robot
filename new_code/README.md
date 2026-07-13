# VeyraSoul V2

`new_code/` 是虚拟陪伴机器人 V2 的独立实现。旧系统保持冻结，只作为行为参照与模型资源迁移来源；V2 不在旧代码上继续叠加功能。

> **当前运行边界：** `veyralux.org` 是独立品牌门户；`robot.veyralux.org` 只承载正在评审使用的 V1；`anima.veyralux.org` 只保留给 V2，当前不得指向 V1。V2 只允许在开发电脑和自动化环境中开发验证，暂不上传、安装或切换到开发板。仓库内的 V2 systemd/Cloudflare 文件仅是未来部署草案，激活脚本默认拒绝切换。

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
9. **直接接触而非动作盘**：用户通过角色身体命中区域交互；表情和动作由自主导演结合语义与能力表选择，不向用户暴露模型动作列表。

## 当前实现状态（以代码为准）

### 已实现并有自动化测试覆盖

- SQLite WAL 记忆、FTS5 trigram 检索、向量候选融合、事实 revision；
- 确定性 Memory Curator：事实/偏好规范化去重、来源可靠度、弱冲突保护、明确纠正 revision 与完整 provenance；
- per-session `generation`、取消后禁止旧结果写入记忆；
- 匿名浏览器按稳定 session hint 派生独立 UserId；每个 User/Anima 使用独立哈希目录、`state.sqlite3` 与 `Anima.md`，旧全局 facts 不做不可信的自动归属；
- `settings.get/update/current` 已贯通 Anima.md、回复字数上限、显式回复延迟与 TTS `voiceId`；前端角色设置面板在桌面、手机和平板均可滚动操作；
- DeepSeek SSE 流式适配器，显式关闭 thinking；
- 句级 LLM → TTS 管线和二进制 WebSocket 帧；
- 服务端先发音频、再发配对文本事件；前端在该音频实际开始播放时展示文本；
- 本地摄像头画中画、麦克风/摄像头/挂断控制、AudioWorklet 20 ms PCM16；
- 本地视频预览与 500 ms 一次的 JPEG 关键帧采样解耦；5 秒 latest-value 语义调度器已接入 Gateway；
- PC 主舞台和移动端响应式通话布局；
- 本地 Cubism/Pixi runtime、真实 Strawberry_Rabbit 模型、自适应 4096/1024 纹理、60 FPS ticker、连续头眼/呼吸/眨眼/口型参数混合；
- 从实际 WAV PCM 预计算 20 ms RMS 包络并按播放时间驱动 Live2D 嘴形。
- 连续情感证据、真实时间衰减和 generation-safe `avatar.intent` 已贯通后端与 Live2D；ASR partial 会立即触发 listening/barge-in，旧代意图不会污染新轮；
- 浏览器原生 `AvatarActionScheduler` 已把 renderer-neutral 意图映射到真实 `.exp3/.motion3`，支持能力过滤、优先级、持续时间、冷却、抢占与代际门控；连续 SignalMixer/RMS 仍拥有最终参数混合顺序；
- 用户动作盘已移除；`@use-gesture/vanilla`、模型 HitArea、舞台视觉左右语义、tap/press/stroke 和本地 `InteractionDirector` 已进入实现与单元测试阶段，原始指针轨迹不进入协议或记忆；
- WebSocket 指数退避重连、AudioWorklet→ScriptProcessor 和 OffscreenCanvas→HTMLCanvas 兼容降级，以及 320×568、手机、平板和横屏 Chromium E2E。

### 已有适配器或界面骨架，但尚未完成真实板端闭环

- sherpa-onnx streaming Zipformer ASR 与 Kokoro/Matcha/VITS TTS 适配器已经存在，仍需用 ELF2 上的真实模型目录、麦克风和声音做端到端验证；
- Gateway 已把 JPEG 接入单槽 latest-value 调度器，并通过板内 `/analyze` VLM HTTP 适配器发布 `VisualSnapshot`；仓库内尚不包含真正的 RK3588 VLM worker，也未接入 RKNN 快视觉；
- 新鲜 `VisualSnapshot` 已无条件进入每轮动态上下文并发布给前端；仍需用真实板内 VLM 服务验证准确度、超时和资源占用；
- Live2D 真实模型、连续 AvatarIntent 和 RMS 口型已接通，并通过桌面/竖屏/横屏 Chromium 拟真验证；音素级 viseme、语义重音、完整动作时间轴和目标手机 GPU 实测尚未完成；
- 身体交互目前只有本机实现、单元测试和运行时命中区域核验，尚未完成目标手机触控、误触率、无障碍和帧耗验收；Strawberry Rabbit 模型公网再分发授权也尚未闭环；
- UI 已做桌面/移动端布局与构建检查，尚未完成覆盖主流手机浏览器的真机矩阵；
- 当前匿名隔离依赖不可猜测的稳定 session hint，仅提供数据分区而不是账号认证；默认 Gateway 会拒绝显式 `?user=`，只有注入服务端 IdentityResolver 后才能建立正式用户身份；
- V2 systemd、同源静态托管、Cloudflare Tunnel 单元与一键启动/回滚脚本已进入仓库，但已加显式激活保护；在比赛评审期间不得替换开发板与公网 V1。

任何目标时延、60 FPS 和内存预算在板端实测前都属于 **SLO/验收门槛**，不是已达成的性能声明。

## 目录

```text
new_code/
├── backend/                 # 会话编排、记忆/RAG、模型适配器、ASGI Gateway
├── web/                     # PC 优先、移动端完整的 Preact + TypeScript 通话界面
├── brand-site/              # veyralux.org 独立品牌门户与 Static Assets 部署
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

cd ..\brand-site
npm ci
npm run typecheck
npm test
npm run build

cd ..
.\scripts\check.ps1

# 使用确定性本机模型桩启动真实 Gateway + Chrome，验证桌面/移动视频通话纵切片
.\scripts\check.ps1 -WithE2E
```

浏览器 E2E 会使用 fake camera/microphone、本地短音频和确定性 LLM/VLM 桩，不需要密钥，也不会访问或部署 ELF2。它验证真实 WebSocket、强制断开后的自动重连与续聊、二进制音频配对、播放时显字、旧代打断、视觉事件、角色设置、Live2D 加载、媒体权限、按钮裁切和页面溢出；结果写入 `artifacts/e2e-local.json`。它不能替代真实模型自然度、弱公网和板端性能测试。

## 启动开发界面

```powershell
cd E:\CODE\Visual_Companion_Robot\new_code\web
npm run dev
```

浏览器媒体权限只在安全上下文中可用：本机开发可使用 `http://localhost:5174`，手机/公网必须使用 HTTPS。前端默认连接同源 `/v2/realtime`。

板端 Gateway 的依赖、模型目录、环境变量和启动方式见 [`docs/deployment-elf2.md`](docs/deployment-elf2.md)。

## 文档索引

- [`docs/architecture.md`](docs/architecture.md)：目标架构、当前纵向链路和模块边界
- [`docs/brand-site-creative-direction.md`](docs/brand-site-creative-direction.md)：品牌门户内容、动效、域名与事实边界
- [`docs/live2d-interaction.md`](docs/live2d-interaction.md)：无动作盘身体交互、语义契约、生命周期和授权边界
- [`docs/video-call-ux.md`](docs/video-call-ux.md)：视频通话式交互、媒体频率和端侧适配
- [`docs/protocol.md`](docs/protocol.md)：Realtime Protocol v2
- [`docs/latency-slo.md`](docs/latency-slo.md)：目标时延、测量口径和当前证据边界
- [`docs/deployment-elf2.md`](docs/deployment-elf2.md)：ELF2 配置与启动
- [`docs/implementation-roadmap.md`](docs/implementation-roadmap.md)：已完成、进行中和验收门槛
- [`docs/user-data-isolation.md`](docs/user-data-isolation.md)：用户/Anima 数据、备份、迁移与安全边界
- [`docs/reference-evaluations.md`](docs/reference-evaluations.md)：SoulX-Podcast 与 Neuro 的事实核查和取舍
- [`docs/reference-kourichat.md`](docs/reference-kourichat.md)：KouriChat clean-room 对话/记忆设计取舍
- [`docs/server-buying-guide.md`](docs/server-buying-guide.md)：服务器容量、三档采购方案、云 GPU 试租与三年 TCO 决策门
- [`docs/reviews/2026-07-13-v2-differential-security-review.md`](docs/reviews/2026-07-13-v2-differential-security-review.md)：本轮身份/数据/实时链路差分安全审查
