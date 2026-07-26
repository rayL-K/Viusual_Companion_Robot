# Anima v0.0.1 实施路线

> 状态以 `new_code/` 源码和可复现测试为准。设计目标、自动化浏览器结果和 ELF2 真机指标分开记录。

## P0：可用的单机产品链路

### 已有基础

- FastAPI/ASGI Gateway、binary WebSocket、generation/cancellation；
- 浏览器 AudioWorklet PCM16、本地摄像头预览和 latest-only JPEG；
- sherpa-onnx streaming ASR 与 Kokoro/Matcha/VITS TTS Adapter；
- DeepSeek Flash SSE 与非思考对话配置；
- SQLite WAL、FTS/RAG、记忆 provenance、User/Anima 分区和 `Anima.md`；
- 真实 Cubism/Pixi Live2D、口型、视线、表情/动作调度和本地身体交互；
- PC/手机/平板的响应式结构与本机自动化验证。

### 当前最高优先级

1. **TurnTrace**：完整打点 ASR final -> context -> LLM first delta/clause -> TTS -> first reply frame -> playback/cancel，每次优化都用 p50/p95 证明。
2. **真流式语音输出**：去掉“LLM 一句 -> 等整段 WAV -> 再继续 LLM”的串行空洞，改为可取消的 TTS 流和 AudioWorklet 排队。
3. **打断与背压**：控制帧最高优先级，PCM 只允许 120–200 ms 积压，JPEG latest-only；新 `speech_started` 快速静音旧音频。
4. **ContextPlanner**：为 persona、近期对话、记忆/RAG、视觉和用户输入设定总 token 预算；稳定前缀保持可缓存。
5. **ELF2 真机闭环**：在不影响主机其他服务的前提下，按 candidate health 流程部署到 `anima.veyralux.org`。

## P1：感知准确性与连续上下文

- 保持摄像头本地预览 60 FPS 目标，语义推理默认每 5 秒一次，两者不共用渲染关键路径；
- 为视觉快照增加 server-observed time、`frame_id`、置信度和来源，一轮对话只冻结一份快照；
- 新鲜视觉语义无条件进入上下文，但不向用户照读检测器原始列表；
- 引入人/物/姿态结构化快路，语义 VLM 负责自然描述和环境关系；
- 用固定真人、动作、表情、室内/户外和负例图集计算准确率，不以单张演示替代。

## P1：关系记忆与多轮一致性

- 最近对话必须按 Conversation 连续携带，“为什么？”等省略问句可回溯上一轮；
- 增加事实抽取、情节摘要、时间上下文和 evidence 压缩；
- 检索 query 同时使用当前发言、最近对话意图和视觉语义，不只搜当前一句；
- 同一 Anima 多会话写入使用单 writer/actor，generation 仍属于各 Session；
- 被取消、低置信或未完整的回复不进入长期记忆。

## P1：ToC 身份与数据边界

1. Secure/HttpOnly/SameSite 登录态或等价短期 token；WebSocket query 不承担身份凭据。
2. Auth Resolver + 所有权校验，每个 User/Anima 物理 Store 与 RAG scope。
3. 每用户/每 IP 连接数、媒体速率和供应商成本预算；Origin 白名单。
4. 匿名数据升级、导出、删除、保留期、加密备份和抽样恢复。
5. 日志、metrics 和 trace 不含 prompt/回复、原始音视频、API key 或高基数主体 ID。

在这些门槛完成前，ELF2 部署定位为受控测试服务，不宣称已具备可信多租户生产能力。

## P2：供应商和容量解耦

- 完成 `ProviderRegistry`：ASR、Vision、LLM、TTS 及可选 RealtimeConversation 各有 capability/data-policy/health；
- 默认模式为模块化低延迟链路，原始音视频上云的实时通话仅在用户主动选择后启用；
- 设置供应商超时、并发上限、circuit breaker 和实际成本指标；
- 在 ELF2 上固定 ASR/TTS/VLM 模型、线程数、RSS 和温度基线；
- 未来迁移到低端 Linux Server 时，仅替换 Adapter 和容量配置，客户端协议不变。

## P2：发布与真实环境验收

- 已提供 `stage -> health -> activate -> rollback` 发布器、独立 candidate 端口、专用 systemd 用户与 Tunnel token；
- 候选版本不接管公网；失败不改当前 release；脚本不管理主机上其他服务；
- 完成 `anima.veyralux.org` 的 PC/手机真实 HTTPS/WSS、媒体权限、旋转、后台恢复和弱网矩阵；
- 进行 8 小时 soak、断网/重连/打断压力、内存增长、温度/降频和 OOM 验收；
- 对每次部署执行回滚演练和数据抽样恢复，不只测 `/v2/health`。

## 发布硬门槛

1. Backend test、Web check/build、Live2D browser smoke 全部通过；
2. Live2D 模型在桌面和 390 px 移动视口真实加载，无未预期 console/page error；
3. ELF2 真模型 ASR -> context -> LLM -> TTS -> 同步播放闭环通过；
4. 停止说话到首个有意义音频、打断、视觉新鲜度和预览 FPS 都有 p50/p95；
5. 本地预览与 5 秒语义更新互不拖慢；
6. `anima.veyralux.org` 有 TLS、鉴权、Origin/限流、成本预算和可验证回滚；
7. 密钥不进仓库/日志/命令行，发布制品无用户数据；
8. 公开制品中的 Live2D 模型具有覆盖 Web 托管和再分发的可审计授权。
