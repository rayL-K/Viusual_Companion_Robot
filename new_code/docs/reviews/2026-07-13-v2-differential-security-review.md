# VeyraSoul V2 差分安全审查（2026-07-13）

## 结论

- 审查范围：`36bd150..working tree` 下 `new_code/` 的用户隔离、设置、实时媒体、重连、Live2D 动作与文档变更。
- 代码库规模：中型；采用 focused review。高风险路径为 WebSocket 身份、每用户数据选路、设置写入和云端 LLM/TTS adapter；媒体/UI 采用一跳依赖与生命周期审查。
- 当前结论：**适合继续本机 V2 开发，不允许作为可信多用户服务发布。** V1/ELF2/公网评审链路未被本差分修改或部署。
- 本轮未发现硬编码 API key、Wi-Fi 密码或默认凭据；`DEEPSEEK_API_KEY`、ASR/TTS 模型目录缺失时启动失败，属于 fail-closed。

## 基线与 blast radius

- 相关基线提交：`da4ace4`（V2 基础）、`a6be655`（视频通话纵切片）、`f4260b5`（情感与记忆）、`36bd150`（本机 E2E）。
- `SessionRegistry` 生产调用面：Gateway 组合根与 realtime handler，共 2 个源码文件；身份变更不会绕过其他入口。
- `SpeechSynthesizer` 调用面：Port、TurnService、sherpa adapter 共 3 个源码文件；全部已迁移到 `SpeechSynthesisRequest`。
- `AvatarActionScheduler` 调用面：scheduler 与 `Live2DStageController` 共 2 个源码文件；服务端仍只发送 renderer-neutral intent。
- 浏览器匿名 session 生成/消费：identity helper 与 `RealtimeClient` 共 2 个源码文件。

## 未关闭发现

### [P1 / 发布阻断] 匿名 session hint 仍是可恢复持久数据的 bearer-like 提示

**证据**

- `web/src/core/realtime/sessionIdentity.ts:12-49` 将随机 hint 写入 `localStorage`；
- `web/src/core/realtime/RealtimeClient.ts:218-223` 将 hint 放入 WebSocket URL；
- `backend/src/veyrasoul/identity.py:34-40` 以 hint 哈希派生匿名 UserId。

**攻击场景**

同设备 XSS、恶意浏览器扩展、共享浏览器配置或泄漏的连接 URL 得到 hint 后，可重新连接同一匿名 User/Anima 分区并读取设置/继续同一会话。哈希目录防止路径穿越，但不提供主体认证。

**缓解与门禁**

- 默认 Gateway 已改为拒绝所有显式 `?user=`；只有服务端注入 `IdentityResolver` 才能创建正式用户；
- `session.ready.identityAssurance=anonymous_session_hint` 明确不是认证；
- V2 当前禁止部署。公网发布前必须使用 Secure/HttpOnly/SameSite 凭据或等价 token、服务端 Auth Resolver、会话轮换/吊销和 XSS 防护；不能把 localStorage/query 当账号凭据。

### [P1 / 发布阻断] 仍缺 WebSocket Origin、鉴权与主体级限流

**证据**

`backend/src/veyrasoul/gateway/app.py:204-360` 的 realtime 入口验证帧/事件大小和 identity 格式，但尚未验证可信 Origin、登录 token、每主体/每 IP 连接数或请求预算。

**攻击场景**

若直接把 V2 暴露公网，攻击者可建立大量匿名连接、持续上传 PCM/JPEG，并消耗 ASR/VLM/LLM/TTS 预算；浏览器跨站 WebSocket 也没有服务端 Origin 门禁。

**门禁**

Cloudflare 只能作为外层限流，不能替代应用对象授权。发布前必须增加 Origin allowlist、token 验证、每主体并发/字节/推理配额、连接关闭码与审计测试。

### [P2 / 可靠性] 多独立 SQLite 尚无 schema migration/备份恢复实现

每 User/Anima 物理分库已经阻断跨库漏查，但数据库数量增加后，`CREATE TABLE IF NOT EXISTS` 不能证明滚动升级、失败恢复和版本回滚。发布前需要 schema version、幂等 migration、备份前 WAL checkpoint、加密备份与抽样恢复演练。详见 `docs/user-data-isolation.md`。

## 本轮已修复的差分风险

1. **显式 user fail-open**：默认 resolver 不再接受 `?user=`；测试中的 `client_asserted` resolver 不进入默认组合根。
2. **内部错误泄漏**：视觉、设置读写和回复失败不再把异常正文/绝对路径发给客户端，日志只记录异常类型。
3. **设置丢失更新**：`settings.update` 强制 `expectedRevision`，旧编辑器收到 `settings_conflict`，不能 last-write-wins 静默覆盖。
4. **Anima.md/SQLite 部分提交**：先原子替换人设镜像，再提交 SQLite；镜像失败回滚事务，数据库失败尝试恢复旧镜像，并有故障测试。
5. **跨用户 RAG**：Store 在检索器创建前按 User/Anima 物理分区；旧共享 facts 因无法可信归属而不自动迁移。
6. **路径穿越**：外部 ID 严格校验，目录仅使用 SHA-256 派生 key，并在 `DataRoot` 下再次做 containment 检查。
7. **旧代复活**：实时文本、音频、AvatarIntent 与离散动作共享 generation/seq 门控；强制 WebSocket 重连后旧域重置。

## 测试覆盖

- Backend：身份格式、默认拒绝显式用户、注入 resolver 后的 User/Anima 分库、匿名 session 分库、旧 turns 幂等迁移、设置校验/持久化/字数/延迟/音色、revision 冲突、镜像故障回滚、视觉错误脱敏、代际取消。
- Web：重连退避与旧 socket 隔离、媒体能力降级和资源释放、设置协议解析、AvatarActionScheduler 的能力/no-op/优先级/冷却/代际/清理。
- Chromium E2E：6 个桌面/手机/平板横竖屏、fake camera/mic、真实 WebSocket、强制断开重连、继续对话、旧回复打断、设置载入、Live2D 与布局溢出。

## 覆盖限制

- 本轮没有执行 Semgrep 全规则扫描：该技能要求在扫描前另行确认精确规则集与输出计划；已执行离线 secret/insecure-default 人工扫描和 focused differential review。
- 尚未做 Firefox、WebKit/iOS Safari 真机、恶意 Origin、代理丢包/限带宽、8 小时 soak 或 ELF2 真模型压测。
- 未对外部依赖供应链做 SBOM/CVE 锁定审查。

## 发布判断

- 本机开发/自动化：**通过**。
- 合并到 V2 开发分支：**通过，需保留上述 P1 发布门禁**。
- 部署到 ELF2 或切换 `anima.veyralux.org` 为 V2：**不通过**。
