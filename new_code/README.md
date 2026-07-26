# Anima v0.0.1

`new_code/` 是 Anima 的独立产品代码：面向浏览器与后续 App 的低时延多模态虚拟陪伴系统。产品以 **Anima v0.0.1** 对外发布；ELF2 目前作为开发和测试服务器，后续可将同一套服务迁移到低端 Linux 服务器，而客户端无需随硬件迁移重写。

## 当前架构

```text
Web / App
  ├─ 本地 60 FPS Live2D 舞台、触控/鼠标身体交互、音视频采集与播放
  └─ HTTPS + WSS
          │
          ▼
Anima Gateway（当前 ELF2，后续任意 Linux Server）
  ├─ 会话代际、打断、背压、TurnTrace
  ├─ Anima.md / 用户设置 / 独立数据目录
  ├─ 上下文预算、短期对话、长期记忆与 RAG
  └─ ASR / LLM / Vision / TTS provider ports
          │
          ├─ 当前：DeepSeek LLM API
          └─ 当前：本地 sherpa ASR/TTS、loopback local-vlm（按配置启用）
```

核心边界：

1. **客户端不依赖 ELF2**：网页和 App 只依赖稳定的实时协议与鉴权；迁移服务器只需替换部署与 Provider 配置。
2. **Live2D 在客户端渲染**：服务器发送语义化表情、动作、情绪与音频事件，不传输角色视频流，节省带宽并保持 60 FPS。
3. **媒体与推理解耦**：摄像头预览保持高帧；视觉语义采用 latest-only 低频采样，默认每 5 秒刷新，不让积压帧拖慢交互。
4. **Provider 可替换但不虚报实现**：ASR、LLM、视觉、TTS 通过接口隔离；当前只有 DeepSeek 是已接入的云 Provider，云 ASR、云 TTS、云 VLM 仍需新增 Adapter、配置校验与验收后才能启用。
5. **用户数据隔离**：每个 User/Anima 拥有独立 `state.sqlite3`、`Anima.md` 与可备份目录；正式多用户入口仍需接入服务端鉴权。
6. **不伪造等待感**：回复正文只在对应音频真正开始播放时出现；不使用固定“快速答案”，新输入会取消旧代回复。

> `/v2/realtime` 与 `/v2/health` 是当前内部传输协议路径，不代表产品代号；对外产品版本始终是 Anima v0.0.1。
>
> Python 包路径 `veyrasoul` 与少量 `VEYRASOUL_*` 环境变量是兼容性标识符，暂时保留以避免破坏导入和旧部署配置；它们不是产品名称。新部署优先使用 `ANIMA_*`。

## 已实现

- FastAPI 实时 Gateway、二进制 WebSocket 音视频帧、可取消 turn generation；
- DeepSeek SSE 非思考流式适配器，以及可替换的 ASR/LLM/Vision/TTS 端口；
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
- ELF2 上已有 RK3588 本地视觉服务与模型资产；Anima Gateway 正按旁路部署、健康检查、回滚后切换入口的顺序接入。
- 当前板端 ASR 资产是离线 SenseVoice，新的 streaming Zipformer 适配器不能直接复用；正式链路需要安装兼容流式模型。云端实时 ASR 目前没有 Adapter，不能只靠配置启用。
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
└── scripts/       # 本机检查、E2E 与板端启动
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

## 迁移原则

ELF2 不是客户端协议的一部分。迁移到低端服务器时只移动 Gateway、Provider 配置和用户数据卷：

- DeepSeek + 本地 sherpa TTS、ASR/VLM 显式禁用的最小路线：建议从 4 vCPU / 8 GB RAM / 80 GB NVMe 起步；
- DeepSeek + 本地 sherpa ASR/TTS：建议 8 vCPU / 16 GB RAM；
- 本地大模型或多路并发视觉：单独评估 GPU/NPU，不与基础 ToC 网关混部。

最终选型以 TurnTrace 的 p50/p95、并发数、音频首包和每用户成本为依据，而不是先购买高配机器。

## 文档

- [架构](docs/architecture.md)
- [实时协议](docs/protocol.md)
- [延迟 SLO](docs/latency-slo.md)
- [ELF2 部署](docs/deployment-elf2.md)
- [迁移到低配 Linux Server](docs/portable-server-migration.md)
- [Live2D 身体交互](docs/live2d-interaction.md)
- [视频通话式 UX](docs/video-call-ux.md)
- [用户数据隔离](docs/user-data-isolation.md)
- [实现路线](docs/implementation-roadmap.md)
- [安全审查索引与最新复核](docs/reviews/README.md)
