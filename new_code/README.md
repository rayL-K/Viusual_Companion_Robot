# Anima v0.0.1

`new_code/` 是 Anima 的独立产品代码：面向浏览器与后续 App 的低时延多模态虚拟陪伴系统。产品以 **Anima v0.0.1** 对外发布；生产主路径是可替换的 Linux Server 与 API Provider，不绑定特定开发板。

## 当前架构

```text
Web / App
  ├─ 本地 60 FPS Live2D 舞台、触控/鼠标身体交互、音视频采集与播放
  └─ HTTPS + WSS
          │
          ▼
Anima Gateway（Ubuntu x86_64 / aarch64）
  ├─ 会话代际、打断、背压、TurnTrace
  ├─ Anima.md / 用户设置 / 独立数据目录
  ├─ 上下文预算、短期对话、长期记忆与 RAG
  └─ ASR / LLM / Vision / TTS provider ports
          │
          ├─ 当前：DeepSeek LLM API
          └─ 当前：sherpa 或 OpenAI-compatible 音频、loopback local-vlm（按配置启用）
```

核心边界：

1. **API-first、硬件无关**：网页和 App 只依赖稳定的 HTTPS/WSS 协议与鉴权；服务器、GPU worker 和 Provider 可以独立替换。
2. **Live2D 在客户端渲染**：服务器发送语义化表情、动作、情绪与音频事件，不传输角色视频流，节省带宽并保持 60 FPS。
3. **媒体与推理解耦**：摄像头预览保持高帧；视觉语义采用 latest-only 低频采样，默认每 5 秒刷新，不让积压帧拖慢交互。
4. **Provider 可替换但不虚报实现**：ASR、LLM、视觉、TTS 通过接口隔离。登录后的 Catalog 只列出本进程真实绑定的别名、模型和音色，不返回密钥或上游 URL；当前环境配置每种能力至多绑定一个实际 Provider（ASR/Vision 可禁用），尚不是多上游同时在线的路由池。
5. **用户数据隔离**：每个 User/Anima 拥有独立 `state.sqlite3`、`Anima.md` 与可备份目录；ToC 模式使用 OIDC/JWKS、PKCE、服务端会话与 owner-scope 授权，匿名实时入口在生产配置中关闭。
6. **不伪造等待感**：回复正文只在对应音频真正开始播放时出现；不使用固定“快速答案”，新输入会取消旧代回复。

> `/v2/realtime` 与 `/v2/health` 是当前内部传输协议路径，不代表产品代号；对外产品版本始终是 Anima v0.0.1。
>
> Python 包路径 `veyrasoul` 与少量 `VEYRASOUL_*` 环境变量是兼容性标识符，暂时保留以避免破坏导入和旧部署配置；它们不是产品名称。新部署优先使用 `ANIMA_*`。

## 已实现

- FastAPI 实时 Gateway、二进制 WebSocket 音视频帧、可取消 turn generation；
- DeepSeek SSE 非思考流式适配器、OpenAI-compatible ASR/TTS 适配器，以及可替换的 ASR/LLM/Vision/TTS 端口；
- 每 Anima Provider 选择的持久化与服务端校验；实时连接建立时冻结 snapshot，修改路由或音色后从下一条 WebSocket 连接生效；
- 可协商的 24 kHz mono PCM 流式 TTS：服务端约 140 ms 跨分段媒体时钟，浏览器 120 ms 目标/200 ms 硬上限有界播放队列，不支持时保留 WAV 回退；
- 回复流水线只预取下一分段的 TTS 首个有效音频块；单许可、单槽位阻止继续抢跑，取消或失败会关闭当前与待播上游流；
- 云 ASR 在付费请求前使用独立于 LLM turn 的并发/分钟配额；16 kHz PCM 按实时速率限流，取消或文字输入会递增识别 epoch 并废弃迟到结果；
- 有硬上限的上下文构造：稳定前缀、Anima.md、近期对话、视觉、记忆、连续情绪；
- SQLite WAL、FTS5、向量候选融合、事实修订与来源信息；
- 每个 User/Anima 的数据目录、设置 revision、Anima.md 镜像和备份边界；
- 浏览器麦克风/摄像头、AudioWorklet PCM、latest-only JPEG、拥塞迟滞和重连；
- 真实 Cubism/Pixi Live2D 模型加载，桌面 4096 / 移动端 1024 纹理自适应；
- 60 FPS ticker、呼吸/眨眼/头眼/注视/RMS 口型、表情与动作调度；
- 模型身体 HitArea、鼠标与触控 tap/press/stroke 交互；
- PC、手机、平板与低高度横屏响应式布局；
- 品牌门户 `veyralux.org` 与产品入口 `anima.veyralux.org` 分离。

## 当前验收边界

- 本机自动化已经验证真实 Live2D 资源请求、画布渲染、桌面与移动布局；仍需在目标手机浏览器验证 GPU 帧耗、媒体权限和触控误触率。
- 通用服务器使用 systemd、同源 Gateway 与 Cloudflare Tunnel/受信反向代理；Gateway 仅监听 loopback，ASR/TTS/VLM worker 不直接暴露公网。
- OpenAI-compatible ASR 当前在端点检测后按完整语句上传，不是真正的增量转写；追求更低首字时延时仍需接入并验收供应商原生的 streaming ASR 协议。本地 sherpa 路径则必须安装兼容的 streaming Zipformer 资产，不能拿离线 SenseVoice 目录直接替代。
- PCM 上传预算默认等于 16 kHz mono PCM16 的实时速率（32,000 B/s，最多预借 1 秒），单帧最大 200 ms；云 ASR 请求另有服务端并发与分钟配额。提高这些上限会直接扩大公网成本与滥用面，必须在压测和预算告警后调整。
- OpenAI-compatible TTS 的 PCM 流式路径默认关闭；只能在已验证上游确实支持流式 PCM 时显式设置 `ANIMA_TTS_STREAMING_ENABLED=true`，“OpenAI-compatible”本身不等于具备该扩展。
- Live2D 运行库许可与角色模型的公开再分发授权是两件事；公开部署前需保留模型授权证据。
- 目标时延与 60 FPS 都是实测 SLO，不以配置项或桌面模拟结果代替真机数据。

## 目录

```text
new_code/
├── backend/       # 会话、记忆/RAG、Provider 适配器、ASGI Gateway
├── web/           # Preact + TypeScript 实时交互与 Live2D 客户端
├── brand-site/    # veyralux.org 品牌门户
├── config/        # 默认 Anima.md（不得写入密钥）
├── deploy/        # systemd / Cloudflare 部署单元
├── docs/          # 架构、协议、SLO、部署与评审记录
├── artifacts/     # 可复现基准结果
└── scripts/       # 本机检查、E2E 与发布门禁
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
```

本机开发：

```powershell
cd E:\CODE\Visual_Companion_Robot\new_code\web
npm run dev
```

浏览器媒体权限要求安全上下文：电脑本机可使用 `http://localhost:5174`，手机和公网入口必须使用 HTTPS。前端默认连接同源 `/v2/realtime`。

## 服务器部署原则

服务器只承载 Gateway、Provider Adapter 与受控用户数据卷；模型 worker 可按资源独立部署：

- DeepSeek + OpenAI-compatible ASR/TTS、视觉暂时显式禁用的 API-first 路线：开发可从 4 vCPU / 8 GB RAM / 80 GB NVMe 起步，生产按真实并发、数据库与观测负载扩容；
- 加入本地 sherpa ASR/TTS：建议至少 8 vCPU / 16 GB RAM，并按目标 CPU 实测实时系数；
- 本地大模型或多路并发视觉：单独评估 GPU/NPU，不与基础 ToC 网关混部。

最终选型以 TurnTrace 的 p50/p95、并发数、音频首包和每用户成本为依据，而不是先购买高配机器。

## 文档

- [架构](docs/architecture.md)
- [实时协议](docs/protocol.md)
- [延迟 SLO](docs/latency-slo.md)
- [通用 Linux Server 部署与迁移](docs/portable-server-migration.md)
- [服务器采购与容量规划](docs/server-buying-guide.md)
- [Live2D 身体交互](docs/live2d-interaction.md)
- [视频通话式 UX](docs/video-call-ux.md)
- [用户数据隔离](docs/user-data-isolation.md)
- [实现路线](docs/implementation-roadmap.md)
