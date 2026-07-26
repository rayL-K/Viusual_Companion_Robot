# Anima v0.0.1 未提交差异安全复核（2026-07-24）

> **审查对象：** 工作树相对 `HEAD=1dc6147` 的未提交 `new_code/` 差异。
>
> **方法：** Trail of Bits `differential-review`（FOCUSED）与 `insecure-defaults`。
>
> **结论：** **CONDITIONAL / 不应在修复下列 OPEN 高优先级事项前执行公网发布。**

## 执行摘要

| 严重度 | OPEN | 已验证缓解 / RESOLVED |
|---|---:|---:|
| 🔴 CRITICAL | 0 | 0 |
| 🟠 HIGH | 1 | 7 |
| 🟡 MEDIUM | 0 | 6 |
| 🟢 LOW | 2 | 2 |

**总体风险：HIGH（公开发布前仍被模型授权证据阻断；运行时 admission 高风险项已修复待全量复验）**

本次差异把匿名公网实时入口从“无认证 WebSocket”收敛为 Turnstile、短期签名 admission cookie、长期设备 cookie、精确 Origin 校验、连接/轮次/媒体配额及服务隔离；这些是实质性改善。

审阅期间，HTTP admission body 边界与 candidate admission 配置已被修正；它们需要在全量检查和 ELF2 上复验。仍然存在的公开发布阻断是：随公开仓库/公网服务一同再分发的 Strawberry_Rabbit 模型没有可核验证据证明获得公开再分发授权。

### 关键指标

- 变更：44 个已跟踪文件，约 **+2,951 / -1,664** 行；另外新增 admission、telemetry、systemd 单元与测试文件。
- 高风险面：认证/签名 cookie、Turnstile 外部验证、公开 WebSocket、DeepSeek 外呼、板端视觉回调、systemd 发布与多租户存储。
- 审查覆盖：所有变更的认证、网关、settings、ASR/TTS、外部 HTTP、部署单元/发布器、数据布局、Live2D 资产清单及对应测试；文案/UI 的非安全样式未逐行审阅。
- 已执行：`python -m pytest tests/test_admission.py tests/test_gateway.py tests/test_gateway_settings.py tests/test_gateway_main.py tests/test_sherpa_asr.py tests/test_sherpa_tts.py -q` → **47 passed**（包含本轮 chunked-body 修复后的运行）。
- 测试并不覆盖：真实 Cloudflare 回调、systemd 在 ELF2 上的实际加载顺序、Cloudflare Tunnel/DNS、真实板端资源压力、模型授权链。

## 变更与基线

| 范围 | 风险 | 变化 / 影响 |
|---|---|---|
| `gateway/admission.py`（新增） | HIGH | HMAC 签名 token、Turnstile Server-Side Verify、Origin、连接/速率/媒体限制 |
| `gateway/app.py` | HIGH | 新公开 HTTP admission 路由、WS admission、server-side device identity、idle/session 上限 |
| `gateway/settings.py`（新增） | HIGH | 生产配置 fail-closed、外部 URL 与 origin 校验 |
| `integrations/sherpa_asr.py` / `sherpa_tts.py` | HIGH | 将 async gate 前置，避免线程池被 native 锁等待占满 |
| `deploy/systemd/anima*.service`、`scripts/start-elf2.sh` | HIGH | root 控制面、候选健康门、私有密钥文件、只读 bind、Tunnel credential |
| `runtime.py`、`identity.py` | HIGH | device identity 到每用户/每 Anima 存储布局 |
| `web/.../admission.ts` | MEDIUM | 同源 Turnstile 显式渲染及 cookie 建立 |
| `web/public/live2d/Strawberry_Rabbit/` | HIGH（合规） | 随服务公开再分发模型二进制、纹理、表情与动作 |

基线中旧 `veyrasoul-v2*.service` 以 `wenkang` 运行，采用旧 Tunnel token 路径并且未有匿名 admission。本差异删除其部署文件、改为专用系统用户、固定 launcher 和远端配置 Tunnel；没有发现将先前安全校验删除后重新引入的历史回归。旧服务来源：`a6be655`（2026-07-11）。

## 发现与修复状态

### ✅ RESOLVED（原 HIGH）— Admission HTTP 路由的 chunked body 无界缓冲已修复，待全量/实机复验

**修复证据：** `new_code/backend/src/veyrasoul/gateway/app.py:L328-L341,L650-L666`。端点已改为 `_read_bounded_json()`；其通过 `request.stream()` 累加真实 chunk，在 JSON 解析前对每个 chunk 执行 4,096 bytes 硬上限，故无 `Content-Length` 或声明不可信的请求不会进入 Turnstile verifier。

**测试：** 新增集成测试传入无 `Content-Length` 的分块 >4KiB body，并断言 verifier 未被调用；本审阅随后重跑目标安全测试，47 passed。合并前仍须运行全量测试与 release check。

**残余：** 仍建议在 Cloudflare/反向代理设置相同或更小 request-body 上限，作为应用边界外的第二层。

---

### ✅ RESOLVED（原 HIGH）— Candidate admission 配置已改为 loopback 非公网模式，待发布门复验

**修复证据：** `new_code/deploy/systemd/anima-candidate.service:L14` 现强制 `ANIMA_ADMISSION_REQUIRED=false`，并清空 candidate 的 admission/HMAC/Turnstile 值；candidate 只监听 `127.0.0.1:8876`，不连接 Tunnel。active `anima.service` 保持 `ANIMA_ADMISSION_REQUIRED=true` 与完整公网 fail-closed 配置。

**残余验证：** `new_code/scripts/check.ps1:L84-L93` 已同步当前 candidate 拓扑；仍须在 Windows 运行该 release gate，并在 ELF2 完成 `systemd-analyze verify`、`stage → health → activate`。

---

### 🟠 HIGH — Strawberry_Rabbit 公开再分发授权没有证据

**位置：**

- `new_code/web/public/live2d/Strawberry_Rabbit/manifest.json:L1-L6`
- `new_code/web/public/live2d/Strawberry_Rabbit/Strawberry_Rabbit.moc3`（模型二进制）
- `new_code/web/public/live2d/Strawberry_Rabbit/textures_*/`（纹理）

**状态：** OPEN（合规发布阻断）

**爆炸半径：** `anima.veyralux.org` 的所有访问者都会下载模型；公开 Git 仓库同样构成再分发。

**测试覆盖：** NONE（没有许可来源、哈希、NOTICE 或 CI 合规门测试）。

**证据与场景：**

模型目录包含完整可运行 `.moc3`、纹理、表情和动作。目录中未发现 LICENSE、NOTICE、原始发布 URL、作者授权、可商用/公开再分发许可；其 `manifest.json` 自身明确标注 `"licenseStatus": "verification-required-before-public-redistribution"`。此状态不能作为授权凭证。

**影响：** 无法证明网页托管、GitHub 公开及比赛提交包中再分发资产具有授权；可能导致下架、版权投诉或比赛资格风险。

**修复要求：** 在公开前，二选一：
1. 在仓库加入模型作者/发行方的原始授权文本、来源不可变链接/版本、适用署名与使用限制、资产 SHA-256；CI 必须拒绝缺失 NOTICE 的可发布模型；
2. 用明确允许目标用途（公网展示、再分发、商业/比赛如适用）的模型替换，保留同等证据。

仅在页面隐藏水印或自写 `manifest.json` 不是授权。

## 🟡 MEDIUM 发现

### ✅ RESOLVED（原 MEDIUM）— Candidate release gate 已同步当前安全拓扑，待 PowerShell/ELF2 复验

**修复证据：** `new_code/scripts/check.ps1:L84-L93` 现在断言 candidate 的 `/opt/anima/candidate`、`/var/lib/anima-candidate`、`ANIMA_ADMISSION_REQUIRED=false`、清空 Turnstile 值、只读模型 bind 与生产 state 不可访问，已与 `anima-candidate.service:L14,L37-L40` 对齐。

**残余验证：** 合并前仍需在 Windows 执行 `scripts/check.ps1`，再在 ELF2 执行 `systemd-analyze verify` 与 `stage → health → activate`。

### ✅ RESOLVED（原 MEDIUM）— 非媒体控制事件已受每连接 token bucket 约束

**修复证据：**
- `new_code/backend/src/veyrasoul/gateway/admission.py:L42-L43,L97-L125`：每个 `ConnectionBudget` 独立维护 control token bucket，默认 10 events/s、burst 20。
- `new_code/backend/src/veyrasoul/gateway/settings.py:L155-L165`：配置范围被限制在 1–100 events/s 与 1–500 burst。
- `new_code/backend/src/veyrasoul/gateway/app.py:L517-L527`：在 JSON 解析、settings 写入和 turn 创建前调用 `accept_control()`；超限以 1008 关闭连接。

**测试：** `new_code/backend/tests/test_admission.py:L75-L78` 覆盖 refill/burst；`new_code/backend/tests/test_gateway.py:L792-L818` 覆盖突发控制事件被 1008 关闭。目标安全测试 47 passed。

**残余风险（LOW）：** 这是每连接而非按 device/global 的配额；同一设备最多 3 个连接，仍可能在允许预算内快速写入设置。若实机压测发现 SQLite tail latency 受影响，再为 `settings.update` 设置更低的独立 device/global bucket，并把同步 SQLite 文件写入移至受限 worker。

### ✅ RESOLVED（原 MEDIUM）— 设备身份 cookie 默认寿命缩短为 30 天滑动窗口

**修复证据：** `new_code/backend/src/veyrasoul/gateway/admission.py:L33-L34,L194-L200` 设备 token 默认 30 天；`new_code/backend/src/veyrasoul/gateway/settings.py:L116-L121` 环境默认和上限一致；`new_code/backend/src/veyrasoul/gateway/app.py:L343-L360` 在通过短期 admission challenge 时复用有效 device token 并以该 TTL 重新写入 Secure/HttpOnly/SameSite=Strict cookie，因此为滑动窗口。轮换 `ANIMA_ADMISSION_SECRET` 会使所有既有 device token 验签失败，提供全局撤销路径。

**测试覆盖：** 签名、到期和 server-side identity 的 admission/gateway 测试存在；本轮未见针对 30 天边界、重新签发滑动窗口及 secret 轮换失效的显式测试。

**残余风险（LOW）：** 没有单设备 revoke、登出、设备列表或账号恢复；共享浏览器配置文件仍共享同一匿名空间。ToC 账号体系上线前，应将 UI 明确表述为“设备级匿名空间”，提供清除本机数据与管理员全局 secret 轮换操作；账号上线时使用可单独撤销的 server-side device/session version。

## 已验证的缓解 / RESOLVED

| 项 | 证据 | 状态与测试 |
|---|---|---|
| 公网 WS 无 Origin/cookie 限制 | `admission.py:L223-L236` 校验 exact Origin + 两枚 HMAC cookie；`app.py:L365-L385` 在 accept 前执行 | ✅ RESOLVED；`test_admission.py:L37-L55`、`test_gateway.py:L722-L778` |
| 客户端可用 query 覆盖公网 user/anima/session | `app.py:L388-L422` 从签名 device token 派生 identity，拒绝 `user` 和非 default anima | ✅ RESOLVED；`test_gateway.py:L764-L777` |
| unlimited WS / turn / 媒体/控制事件上传 | `admission.py:L97-L125,L269-L308`、`app.py:L503-L527,L857-L885`；Uvicorn `ws_max_size=1_600_000` | ✅ RESOLVED；控制事件 limiter 见上；`test_admission.py:L58-L117`、`test_gateway.py:L292-L318,L792-L818` |
| 可控 VLM URL 把摄像头帧外传 | `settings.py:L310-L322` 仅允许无凭据 loopback HTTP(S) | ✅ RESOLVED；`test_gateway_settings.py` 覆盖 loopback 约束 |
| Native ASR/TTS 锁等待占满 asyncio 默认 executor | `sherpa_asr.py:L65-L87`、`sherpa_tts.py:L42-L74` 先取得 async gate，再进入线程；取消时保持 gate 至 native worker 退出 | ✅ RESOLVED；`test_sherpa_asr.py`、`test_sherpa_tts.py` 覆盖并发/取消路径 |
| 原始 trace/session/user id 可被日志关联 | `telemetry/turn_trace.py` 的 HMAC sink，`__main__.py:L129-L145` 注入独立 key | ✅ RESOLVED；`test_turn_trace.py` |
| 多租户路径拼接/越界 | `identity.py:L85-L89` 的哈希 storage key，`personalization/layout.py:L23-L40` 的 root containment | ✅ RESOLVED；`test_gateway.py:L630-L719` 及现有 personalization tests |
| 旧服务以可写家目录用户运行 | 新 active unit `anima.service:L9-L39` 使用 `anima-gateway`、只读 bind、`ProtectHome=true`、分离可写目录 | ✅ RESOLVED（静态审阅；待 ELF2 运行验证） |
| Tunnel token 暴露给服务用户/命令行 | `anima-cloudflared.service:L10-L29` 使用 systemd `LoadCredential` 和专用 `anima-tunnel` 用户 | ✅ RESOLVED（静态审阅；待 ELF2 运行验证） |

## Insecure-defaults 审计结果

- 生产 `RuntimeSettings` 默认 `ANIMA_ADMISSION_REQUIRED=true`，且 `AdmissionPolicy` 对 admission secret、allowed origin、Turnstile site/secret 缺失**失败关闭**：`settings.py:L99-L161`、`admission.py:L45-L76`。
- `ANIMA_LLM_BASE_URL` 仅允许 HTTPS，loopback HTTP 仅限开发端点；VLM URL 仅 loopback 且拒绝 credentials/query/fragment：`settings.py:L298-L322`。
- 未在生产源码/模板中发现实际 DeepSeek key、明文密码、`verify=False`、wildcard CORS 或 debug 默认。
- candidate unit 的固定 dummy 值不是生产密钥泄漏；该单元现已改为 loopback candidate 的 `ANIMA_ADMISSION_REQUIRED=false`，并清空 admission/Turnstile 值，仍待 ELF2 发布门复验。
- `/etc/anima/anima.env` 的 admission/HMAC secret 有长度和权限检查：`start-elf2.sh:L163-L220`。Turnstile secret/site key 目前由运行时 fail-closed，而不是发布器预检；建议在发布器中明确预检以产生可操作错误。

## 外部调用与信任边界

| 边界 | 现有控制 | 残余限制 |
|---|---|---|
| 浏览器 → Cloudflare → gateway | HTTPS/WSS、Turnstile、exact Origin、Secure HttpOnly cookies、连接/turn/媒体/控制事件上限、4 KiB admission body 上限 | 真实 Cloudflare 配置与全量负载仍需上线验证 |
| gateway → Turnstile Siteverify | 固定 HTTPS URL、5s timeout、验证 success/action/hostname、token 不写日志 | 需要真实 widget/secret 与 origin 上线验证 |
| gateway → DeepSeek | HTTPS base URL 校验、复用 client、API key 不 repr | Provider 可见对话上下文；需隐私告知/用户授权策略 |
| gateway → 本地 VLM | 配置强制 credential-free loopback，单 inference lock | VLM 本身和本机端口不在本次源码审计范围 |
| gateway → per-device storage | HMAC 派生 user key、数据根 containment、candidate 与 active data 分离 | device token 无撤销；SQLite 负载仍需压力测试 |
| root deployer → active/candidate | root-owned launcher/control files、release manifest、固定 release path、health digest；candidate 已固定为 loopback 非 admission 模式 | 尚未在 ELF2 实测 |

## 测试与爆炸半径

| 函数/面 | 直接调用者或入口 | 优先级 |
|---|---:|---|
| `AdmissionGate.validate_handshake` | 1 个公开 WS handler | P0（认证入口） |
| `verify_admission` | 1 个公开 HTTP route + Web UI bootstrap | P0（认证前 body 读取） |
| `AdmissionGate.try_turn` | `TurnController._start_locked`，所有文本/ASR final turn | P0（全局容量） |
| `SherpaStreamingAsr.decode` | 每一 ASR session 的 batch loop | P1（共享 native recognizer） |
| `SherpaTtsSynthesizer.synthesize` | 每个 reply segment | P1（共享 native engine） |
| `start-elf2.sh health/deploy` | 所有板端发布操作 | P0（发布/回滚） |
| `DataLayout.state_database` | 每个 user/anima runtime | P0（数据隔离） |

## 发布前建议

### 立即阻断项

- [ ] 为 Strawberry_Rabbit 补齐可验证公开再分发授权链，或替换为明确授权模型；没有证据不得公开部署/公开推送资产。

### 发布前必做

- [ ] 重跑含新 `_read_bounded_json` 测试的全量后端测试；确认 chunked/no-Length body 不会调用 verifier。
- [ ] 运行已同步 candidate unit 断言的 `scripts/check.ps1`，并在 ELF2 完成 `systemd-analyze verify`、`stage → health → activate`。
- [ ] 在真实 Cloudflare widget、Tunnel、DNS 环境验证：成功 challenge、错误 Origin、过期 cookie、缺密钥 fail-closed、WSS 连通。
- [ ] 为控制事件设置 per-device/global limiter，及 settings 写入压力测试。
- [ ] 以真实 ELF2 服务用户检查 `systemd-analyze security anima.service anima-cloudflared.service`、文件 owner/mode、模型只读 bind、数据目录隔离。
- [ ] 运行完整 backend/web 测试、Web Live2D smoke、公开依赖/SBOM 与模型资产清单审计。
- [ ] 定义 device cookie 清除、撤销和未来账号迁移方案。

## 方法、范围与置信度

**策略：** FOCUSED。认证、存储、外呼、并发原生模型和部署均为 HIGH 风险，已逐文件审阅其一跳调用者、配置及测试；UI 文案和纯样式仅表面扫描。

**基线：** Git `HEAD=1dc6147`；未提交工作树。对删除的旧 `veyrasoul-v2` 单元使用 `git show HEAD:` 与 `git blame HEAD` 复核。

**技术：** 差异审阅、fail-open 配置搜索、签名/token 流追踪、Origin/cookie/WS 状态机审阅、外部 URL 验证、部署权限与路径边界审阅、测试执行、资产许可证存在性检查。

**限制：** 没有在本次审阅中操作 ELF2、读取真实 `/etc/anima` secrets、创建 Turnstile widget、执行公网攻击、验证模型源作者授权或扫描第三方依赖 CVE；因此这些结论不能替代上线前实机/法务/供应链检查。

**置信度：** 对 OPEN HIGH（模型授权）：HIGH；对静态缓解：MEDIUM-HIGH；对真实运行/外部平台：MEDIUM。
