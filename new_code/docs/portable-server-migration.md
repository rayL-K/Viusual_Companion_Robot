# Anima v0.0.1：从 ELF2 到低配 Linux Server 的可执行迁移

本方案将 ELF2 看作当前的 **边缘实时服务器**，而不是客户端协议的一部分。迁移的目标不是复制一块板子的全部环境，而是把同一套 Gateway、角色资源、Provider 配置与经验证的数据快照，迁到一台可替换的 Ubuntu 主机；Web 与未来 App 仍是 thin client。

> 本文只陈述当前仓库实际实现的能力。DeepSeek 是唯一已接入的 LLM；TTS 当前必须是本地 `sherpa-onnx`；ASR 是可选的本地 `sherpa-onnx` streaming Zipformer；视觉是可选的、独立运行并且仅允许 loopback 回源的 `local-vlm`。云 ASR、云 TTS、云 VLM 都只是 `ports` 后的下一步适配目标，**尚不能靠改环境变量启用**。
>
> Python 包/导入路径 `veyrasoul` 是兼容性命名，迁移时必须原样保留；对外产品名称仍是 Anima v0.0.1，新主机配置优先使用 `ANIMA_*`。

## 1. 迁移后不变的产品边界

```text
任意浏览器 / 后续 iOS、Android App
  ├─ Live2D 本地渲染、鼠标/触控身体交互、摄像头预览、音频采集/播放
  └─ HTTPS/WSS，同源 /v2/realtime
                 │
                 ▼
          Cloudflare Tunnel（可换宿主）
                 │
                 ▼
  Anima Gateway（ELF2 或 Ubuntu x86_64/aarch64）
  ├─ 会话代际、取消、背压、准入、TurnTrace
  ├─ 每 User / Anima 独立 state、persona、RAG/记忆
  └─ Provider ports：ASR | Chat | TTS | Vision
                 │
       ┌─────────┼─────────┐
       ▼         ▼         ▼
  sherpa TTS  DeepSeek  local-vlm（可选）
  sherpa ASR（可选）
```

因此，浏览器/App 只需要稳定域名、HTTPS 与实时协议；不需要知道底层是 RK3588、x86_64 VPS 还是后续多节点服务。Live2D 模型始终由客户端加载和渲染，不把角色视频流推到服务器，迁移不会牺牲前端 60 FPS 的目标。

## 2. 当前能力与真实边界

| 模态 / 端口 | 现在可运行的实现 | 是否可迁移 | 迁移时的真实边界 |
|---|---|---:|---|
| 对话 `ChatProvider` | DeepSeek 非思考 SSE 流 | 是 | 需要新主机独立保存 API Key；配置只接受 `deepseek`。 |
| 语音合成 `StreamingTtsProvider` | 本地 sherpa-onnx（Matcha/Kokoro/VITS 支持的模型结构） | 是 | **必需**；当前没有云 TTS provider，模型和匹配 ABI 的 wheel 必须在目标主机重新验证。 |
| 语音识别 `StreamingAsrProvider` | 本地 sherpa-onnx streaming Zipformer | 可选 | 未配置时应显式 `ANIMA_ASR_PROVIDER=disabled`；不可把旧 SenseVoice 目录当 Zipformer 使用。 |
| 视觉 `VisionAnalyzer` | 独立 `local-vlm` HTTP 服务 | 可选 | Gateway 只允许回源到 `127.0.0.1` / `::1` / `localhost`，需在目标主机另行部署并验收该服务。 |
| 记忆 / RAG | SQLite WAL、FTS5、向量候选融合、来源与事实修订 | 是 | 迁的是一致性 SQLite 快照和 User/Anima 数据根，不迁密钥。 |
| Live2D | 浏览器端 Cubism/Pixi 资源 | 是 | release 的 `web/dist` 必须包含真实 `.model3.json` 与关联纹理/动作资源。 |

`orchestration/ports.py` 已将四类模态隔离出来。新增云端 provider 应新增 adapter、配置校验、超时/取消/隐私测试与真实基准；不得伪装成已支持的 provider 名称。

当前公开发布仍受模型授权证据阻断，且部署安全项需要真机复验；迁移或切流前先阅读[最新差异安全复核](./reviews/differential-security-review-2026-07-24.md)。

## 3. 推荐的低配单机落点

### 3.1 先跑通的 SaaS 单机

选择 **Ubuntu 22.04 LTS 或 24.04 LTS，x86_64 或 aarch64，4 vCPU / 8 GiB RAM / 80 GiB NVMe**：

- DeepSeek 承担文本推理；
- 本机 sherpa TTS 承担中英混合播报；
- ASR 与视觉可以先显式禁用，或仅在模型已实际部署、压测通过后开启；
- `anima.veyralux.org` 的同一个 Cloudflare Tunnel 只回源本机 `127.0.0.1:8875`；
- Live2D、摄像头预览及麦克风采集留在用户端。

若同时运行本地 sherpa ASR，建议提高到 **8 vCPU / 16 GiB RAM / 100 GiB NVMe**。若还要在同机运行真实 VLM，应把模型大小、并发、CPU/GPU/NPU、RSS、温度和视觉 5 秒 latest-only 频率一起实测；没有一套可对所有 VLM 成立的“低配”规格。不要把基础网关与未经隔离的重型 VLM 默认混部。

### 3.2 数据 / 模型 / 密钥三分离

| 类别 | 目标路径或服务 | 备份策略 | 绝不放入 |
|---|---|---|---|
| release（代码与前端） | root-owned、版本化 `/srv/anima/releases/<id>` | Git commit + 已构建 artifact 哈希 | 用户数据、模型、密钥 |
| 模型 | root-owned `/srv/anima/models` | 模型清单、来源、hash；必要时单独对象存储 | release / Git |
| 用户状态 | `/var/lib/anima`（生产） | SQLite 一致性备份、加密离机副本、恢复演练 | release / 镜像 |
| 密钥 / 可变 provider 配置 | `/etc/anima/*.env`、systemd credential | 密钥管理器或加密备份，独立轮转 | Git、日志、tar、客户端 |

生产服务应以专用无登录用户运行；发布、模型、数据、密钥各自有最小可写权限。未来改成容器或编排环境时保持这四个独立卷/secret，不把它们重新混入镜像。

## 4. 迁移前清单（在 ELF2 上完成）

1. **冻结可变状态**：停止 Anima 的写入流量或进入维护窗口；不要停止、删除或改写旧项目服务。
2. **记录来源版本**：记录 Git commit、release SHA-256、当前 Provider 组合、模型目录与模型 hash；记录时不输出 `.env` 内容或 token。
3. **生成一致性数据库备份**：对每个 SQLite 数据库先 checkpoint，再使用 SQLite `.backup` 生成新文件；不要直接拷贝 WAL 正在写入的 `*.db`。
4. **校验备份**：在副本上执行 `PRAGMA quick_check;`，并计算 `sha256sum`。保留原始数据为只读，直到新主机长时验收通过。
5. **导出 release 输入**：只导出 `backend/src`、`backend/pyproject.toml`、`web/dist`、`config/persona.md`；构建产物必须包括 Live2D 模型和纹理。预检脚本是管理工具，可从受信仓库副本单独拷贝，不能混入线上 release。
6. **模型单独打包**：按实际 Provider 只带 sherpa TTS；若开启 ASR 再带流式 Zipformer；若开启视觉则记录 local-vlm 的独立部署方案。不要把模型、数据或 `/etc/anima` 混在 source tar 内。
7. **准备新的密钥集**：新主机单独创建 admission、telemetry HMAC、DeepSeek、Turnstile/Tunnel 凭据。若需要维持登录/设备 token，会话密钥的迁移与轮转要有明确窗口；不要从备份中顺手复制根目录配置。

推荐的 SQLite 备份形态（每个实际数据库分别执行；路径按主机实际部署替换）：

```bash
# 在维护窗口，以服务用户可读且无人写入的副本为输入。
sqlite3 /var/lib/anima/memory/anima.db 'PRAGMA wal_checkpoint(TRUNCATE);'
sqlite3 /var/lib/anima/memory/anima.db ".backup '/srv/anima-export/anima-$(date -u +%Y%m%dT%H%M%SZ).db'"
sqlite3 /srv/anima-export/anima-*.db 'PRAGMA quick_check;'
sha256sum /srv/anima-export/anima-*.db > /srv/anima-export/SHA256SUMS
```

如果目标机没有 `sqlite3` CLI，可由受控 Python/SQLite 维护工具做等价备份；不能用不一致的文件复制替代。

## 5. 新主机预检与落盘

在目标 Ubuntu 上解压**不含密钥的数据**与 release 输入后，从受信仓库副本单独安装只读预检工具并运行：

```bash
# /path/to/new_code 是已审阅的仓库副本，不是 production release 目录。
sudo install -m 755 /path/to/new_code/deploy/portable/portable-preflight.sh /usr/local/bin/anima-portable-preflight

# 推荐的最小实际组合：DeepSeek + 本地 sherpa TTS，ASR/VLM 先禁用。
anima-portable-preflight \
  --source /srv/anima/release-input \
  --tts-model /srv/anima/models/tts/kokoro-zh-en \
  --profile speech

# 只有在模型已完成 ABI 验证时再打开：
anima-portable-preflight \
  --source /srv/anima/release-input \
  --tts-model /srv/anima/models/tts/kokoro-zh-en \
  --asr-model /srv/anima/models/asr/zipformer-zh-en-int8 \
  --profile asr
```

预检是只读的：它检查 Ubuntu 版本、`x86_64/aarch64`、CPU/RAM/磁盘、构建产物中的真实 Live2D、当前 sherpa 模型所需资产，以及可选 local-vlm URL 必须是 loopback。它不会读取 `.env`，不会泄露任何密钥，也不会声称云端 ASR/TTS/VLM 已可用。

然后在新主机逐项完成：

1. 建立专用服务用户、root-owned runtime 和 models 目录；根据目标 ABI 新建 venv 并安装 `backend` 的 `[gateway,models]` 依赖。**不要复制 ELF2 的 aarch64 venv 到 x86_64。**
2. 复制并校验构建好的 release 输入；将数据恢复到 `/var/lib/anima`，修复为服务用户私有权限。用临时 candidate 数据根做恢复抽样，避免候选版本修改生产数据库。
3. 在 `/etc/anima` 创建新的最小权限环境文件，生产配置中显式选择：

   ```dotenv
   ANIMA_LLM_PROVIDER=deepseek
   ANIMA_TTS_PROVIDER=sherpa
   ANIMA_TTS_MODEL_DIR=/srv/anima/models/tts/kokoro-zh-en
   ANIMA_ASR_PROVIDER=disabled
   ANIMA_VISION_PROVIDER=disabled
   ```

   再从独立的 secret store 写入 LLM key、admission secret、telemetry HMAC key、Turnstile key/secret；它们不应出现在该文档、命令历史、release、日志或 Git。
4. 绑定 Gateway 到 `127.0.0.1:8875`，先通过 candidate 端口、`/v2/health`、真实文本/TTS、Live2D 资源、RAG 读取与恢复的用户数据抽样，再切生产入口。
5. 若开启 ASR，验证 audio partial/final、打断与 16 kHz PCM 背压；若开启视觉，验证摄像头预览仍保持浏览器端流畅且语义 scheduler 只在 latest-only 采样后回填上下文。

## 6. Cloudflare Tunnel 无停机迁移

当前 hostname 与 Tunnel 是独立的：hostname 路由指向**命名 Tunnel**，Tunnel 可以同时有新旧 connector。切换时无需修改 Web/App Base URL，也不必为新机器另造产品域名。

1. 在 Cloudflare Zero Trust/Dashboard 中确认 `anima.veyralux.org -> http://127.0.0.1:8875` 的 published application route 仍属于目标的远程管理 Tunnel；不要在 connector 进程上增加 `--url` 去覆盖远程 ingress。
2. 新主机仅在本机 candidate/active 健康检查通过后，使用该 Tunnel **当时仍有效的 token** 启动 `cloudflared`，以便新旧 connector 可并存验证。生产 token 用 root-owned systemd credential 或 0600 token file；不放在 release、CLI 参数、日志、浏览器或 Git。切换验证前不要先轮转 token。
3. 观察新 connector 已连通、HTTPS/WSS、准入页、文本/TTS 及 Live2D 资源均成功；在切换观察窗口内保留旧 connector 作为回退；同一命名 Tunnel 不需要改客户端 DNS。
4. 验收稳定后，停止旧主机 connector；随后把 token 轮转到新值并仅更新新主机的 credential/service，再确认 connector 恢复。不要在未验证新 connector 前先删旧 connector，也不要将“轮转 token”误认为不需要更新新主机服务。

Cloudflare 对远程管理 Tunnel 的 connector 运行支持 `cloudflared tunnel run --token-file <PATH>`；更换 token 的服务安装方式是先卸载旧服务，再使用新 token 安装。以 Cloudflare 当前官方文档为准： [Tunnel run parameters](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/configure-tunnels/tunnel-run-parameters/) 、[published application routes](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/configure-tunnels/remote-tunnel-permissions/)。

## 7. 单机到多节点的演进顺序

### Stage A：单机 gateway（现在优先）

- 一个 Gateway + 一个 Cloudflare Tunnel；
- DeepSeek LLM、sherpa TTS，ASR/VLM 仅在经验证后开启；
- SQLite/WAL 仅被该实例写入；
- 每轮 TurnTrace 记录 provider 时延与队列指标，作为扩容依据。

### Stage B：功能分离而不是盲目水平扩容

- 保持 Gateway 的 WebSocket 会话粘性；
- 将 `local-vlm` 独立为只在私网/loopback 可达的 worker，不能把摄像头 JPEG 直接转发至任意公网 URL；
- 将模型 worker、Gateway、备份任务拆开资源配额；
- 把用户状态的备份、恢复和 schema 迁移做成显式作业。

### Stage C：多节点 / ToC 扩展

- Gateway 无状态部分可水平扩展，但先引入真正的身份认证、会话路由和共享 rate limit；
- SQLite per-user 备份可以继续保留，但跨节点写入前需选定单 writer/分片策略，不能把同一 WAL 文件挂在多主机共享目录上；
- RAG embedding、对象存储、队列、观测与密钥管理独立服务化；
- 只有在 provider adapter 已实现并有取消、隐私、成本、压测证据后，才切换云端 ASR/TTS/VLM。

## 8. 验收门与回退

新主机不因“HTTP 200”即切流。至少同时满足：

- 同源 HTTPS/WSS、Turnstile/准入、速率限制、reconnect；
- 真实 Live2D 模型与纹理 200、桌面/移动布局、鼠标/触控身体交互；
- 文本 DeepSeek 的首段、TTS 首音频、取消旧代回复；
- 恢复后同一 User/Anima 的 persona、设置、RAG/记忆来源均可读，且其他用户不可串数据；
- 需要时的 ASR partial/final、视觉 5 秒语义更新与前端预览不阻塞；
- 至少一段持续运行、断网重连、CPU/RSS/磁盘和 provider 错误注入记录。

任一门失败：停止新 connector 或将 hostname 流量留在旧 connector，保留新机日志和只读数据副本，先修复再切换。release 的回退不应覆盖新产生的用户数据；数据回退必须按已验证的备份/恢复流程单独执行。
