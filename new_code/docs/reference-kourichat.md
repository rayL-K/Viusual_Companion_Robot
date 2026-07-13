# KouriChat 对话设计取舍

本文只提炼 `E:\CODE\kourichat` 中可验证的产品与架构思想，不复制其代码。该本地版本使用 **DeepAnima License 1.2（非商业）**，并要求归属；VeyraSoul V2 因此只做 clean-room 设计参考，所有实现均沿用 V2 自有接口、数据模型与测试。

## 值得吸收的设计

### 1. 用户、Anima 与记忆形成天然三元组

KouriChat 把记忆放在 `avatar_name / user_id` 命名空间下，并区分最近对话与核心摘要（`modules/memory/memory_service.py:14-20,83-104`）。方向是正确的：同一个用户面对不同角色时，不应共享未经授权的关系记忆。

V2 的实现要求更严格：

- `UserId` 是数据所有者，`AnimaId` 是用户拥有的角色实例，`SessionId` 只是连接生命周期；
- 目录名只能来自受约束的不可猜测 ID，不能直接使用昵称或用户输入；
- 每个 `UserId / AnimaId` 拥有独立 SQLite、FTS、向量索引、`Anima.md` 与媒体偏好；
- 检索 API 必须从服务端身份上下文取得 owner scope，调用方不得自由传入别人的路径或数据库。

### 2. 最近上下文与长期关系记忆分层

KouriChat 保存有界最近对话，并每十轮生成一次 50–100 字核心记忆（`memory_service.py:106-183`、`src/base/memory.md`）。这能维持跨重启连续感，但固定轮数触发和自由文本覆盖存在事实漂移风险。

V2 保留“分层”而替换实现：

1. **工作记忆**：当前轮及最近消息，按 token 预算裁剪；
2. **情景记忆**：可检索事件，包含时间、来源、会话与 generation；
3. **事实记忆**：Memory Curator 维护 revision、置信度与 provenance；
4. **关系状态**：affinity / trust / familiarity 等连续量，只由可审计证据更新；
5. **反思产物**：日记、信件或阶段总结是可选派生视图，不能反向覆盖事实源。

### 3. 把时间流逝作为对话上下文

KouriChat 会把距离上一次消息的时间差加入提示（`src/services/ai/llm_service.py:105-140`）。这对“持续存在的 Anima”很重要，但不能依赖只存在于进程内的消息字典。

V2 应由 `TemporalContextPort` 从持久事件时间线产生：

- 本轮间隔、当地时段、最近一次主动互动；
- 用户时区与安静时段；
- 仅在相关时加入压缩后的时间语义，不强迫每次回复提到时间；
- 使用单调时钟计算进程内耗时、UTC 时间保存跨重启事件。

### 4. 合并用户连续短句，而不是逐条抢答

KouriChat 使用按用户队列和重置定时器合并短时间内的多条消息（`src/handlers/message.py:503-585`）。这能减少“用户还没说完，角色已经回答”的机械感。

V2 采用可取消 `TurnCoalescer`，而不是线程定时器：

- 只合并尚未进入 LLM 的文本 partial/final；
- 语音 VAD final、明确发送按钮和问号后的短暂停顿可提前提交；
- 延迟是用户级设置，必须有最小值、最大值和关闭选项；
- 新输入到来时取消旧 generation，所有计时器有 deadline 与 cleanup；
- 不能为了合并而破坏当前低时延首响应目标。

### 5. 主动陪伴需要安静时段和未回复预算

KouriChat 的自动消息包含随机倒计时、安静时段和未回复计数（`src/handlers/autosend.py`）。产品方向可取，但随机选择用户、守护线程和自动重复调度不适合 V2。

V2 的 `ProactivePolicyPort` 必须满足：

- 用户显式开启，默认关闭；
- 每用户时区、安静时段、每日预算、连续未回复上限；
- 只使用该用户与该 Anima 的隔离数据；
- 触发原因可解释、可撤销，调度任务可幂等恢复；
- 不在摄像头/麦克风未授权时后台采集；
- 主动消息仍经过同一代际、记忆提交与 AvatarIntent 管线。

### 6. 对话可派生“生活痕迹”

KouriChat 能由近期对话和人设生成日记、状态、信件等内容（`modules/memory/content_generator.py`）。这能增强 Anima 的持续存在感，但不应成为实时通话主链路的延迟负担。

V2 将其定义为 `ReflectionArtifactPort`：空闲时异步生成、来源可追踪、用户可查看和删除；失败不影响聊天，产物不得被当成用户事实写回 Memory Curator。

## 明确拒绝继承的部分

| KouriChat 现状 | V2 决策 |
|---|---|
| `MessageHandler` 同时处理队列、搜索、记忆、LLM、命令和发送，文件超过 50 KB | 拆为 TurnCoordinator、ContextAssembler、MemoryPort、LlmPort、DeliveryPort |
| OpenAI 客户端、人设、记忆和上下文在服务对象内直接耦合 | 所有模态通过 Port 注入，本地/云端 adapter 不进入领域层 |
| 用户名/角色名直接参与文件路径 | 仅使用验证后的不透明 ID，并做根目录 containment 检查 |
| JSON 文件读改写保存记忆 | SQLite WAL、事务、schema migration、在线备份与恢复校验 |
| `threading.Timer` 和多个全局 mutable dict | 单一异步生命周期、generation 取消、deadline、幂等调度 |
| 每十轮让 LLM 重写整段核心记忆 | 候选事实 → 证据校验 → revision；弱证据不得覆盖强事实 |
| 捕获所有异常后退回“无记忆回答” | 边界返回可观察错误；是否降级由策略层决定，不能静默丢失上下文 |
| `$`、`[happy]` 等控制标记混入自然语言 | 文本、情感、动作、语音参数使用结构化协议字段 |
| 主动消息默认随机调度 | 用户授权、安静时段、预算、幂等任务和审计记录缺一不可 |

## 对 V2 的落地映射

```text
UserIdentityPort
  -> UserDataRoot / AnimaRepository
  -> ConversationEventStore
  -> ContextAssembler
       -> TemporalContextPort
       -> MemoryRetrievalPort
       -> RelationshipStatePort
       -> PerceptionSnapshotPort
  -> TurnCoordinator
       -> TurnCoalescer
       -> LlmPort
       -> SpeechSynthesizerPort
       -> AvatarPerformancePort
  -> ProactivePolicyPort / ReflectionArtifactPort（非实时旁路）
```

所有 Port 都必须有稳定数据合同，并允许 `local`、`cloud` 或测试 adapter；切换实现不得改变领域事件，也不得绕过用户数据出境策略。

## 验收条件

1. 两个用户使用相同 `AnimaId` 文本时，记忆、RAG、设置和导出结果仍完全隔离；
2. 同一用户的两个 Anima 不互相读取事实、关系状态或 `Anima.md`；
3. 连续短句可在配置窗口内合并，发送按钮与语音 final 可立即提交；
4. 主动陪伴默认关闭，安静时段、每日预算和连续未回复上限均有测试；
5. 日记/信件生成失败不会阻塞或污染实时对话；
6. 更换本地/云端 LLM、ASR、TTS、视觉和 Avatar adapter 时，协议及用户隔离测试不变；
7. 许可证扫描确认 V2 未复制 KouriChat 受限代码。

## 当前状态

本文是设计取舍，不代表上述模块已经全部实现。当前 V2 已具备 generation 取消、SQLite/FTS RAG、事实 provenance、视觉上下文与 AvatarIntent，也已落地匿名 User/Anima 独立数据根及 `Anima.md` 设置；可信账号认证、多 Anima CRUD、主动陪伴策略、TurnCoalescer、TemporalContextPort 和反思产物仍需按路线图逐项实现和验证。
