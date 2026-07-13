# VeyraSoul V2 实施路线

状态基于当前 `new_code/` 源码，不把设计文档中的目标视为已实现。

## Phase 0：冻结与证据 — 已完成

- 旧代码源码 ZIP；
- 全 Git 历史 bundle；
- 未跟踪比赛材料 ZIP；
- SHA-256 manifest 与工作区状态。

## Phase 1：会话与数据内核 — 基本完成，待扩展

已完成：

- 事件契约、latest-value、generation/cancellation；
- SQLite WAL、事实 revision、FTS5 RAG、向量候选融合；
- Memory Curator、来源可靠度、弱冲突保护、revision 与 provenance；
- 连续 AffectState、真实时间衰减和 AvatarIntent/SignalMixer 闭环；
- 单元测试与 2,000 条记忆基准脚本。
- 匿名 session 派生 UserId、每 User/Anima 哈希目录和物理 SQLite 分库；
- `Anima.md`、回复上限/延迟/音色 revision 与前后端设置闭环；
- 旧共享库只按相同 session 安全迁移 turns，不自动归属全局 facts。

待完成：

- 本地 embedding 模型与文档 RAG 导入；
- 事实抽取器、自动情节摘要和长期 evidence 压缩；
- 跨进程/重启后的 session actor 恢复策略。
- Auth Resolver/token、匿名数据升级/导出/删除与加密备份恢复实现。

## Phase 2：实时纵向链路 — 进行中

已完成：

- FastAPI/ASGI Gateway 与 VSR2 binary WebSocket；
- 浏览器 AudioWorklet PCM16、视频关键帧采样和本地预览；
- sherpa-onnx streaming ASR 适配器；
- DeepSeek 非思考 SSE 输出；
- sherpa-onnx Kokoro/Matcha/VITS TTS 适配器；
- Matcha Baker + Vocos TTS 资产布局适配；
- ASR/TTS 启动期预热，首轮不再承担模型加载；
- 服务端音频先于配对文本、前端播放时显字；
- 新轮取消旧 generation 的单元测试。

待完成及验收门槛：

- 修复/确认 Gateway 的真实 ASR 模型启动配置并完成 ELF2 麦克风闭环；
- DeepSeek HTTP client 已复用；待验证连接缓存命中、超时和断流取消；
- TTS 分块或下一句预取，避免逐句串行空隙；
- VAD `speech_started` 级 barge-in，而非等待 final；
- 公网条件下测量停止说话到首音频 p50/p95。

## Phase 3：感知 — 语义骨架已接通，模型与快路径未完成

- 已完成：JPEG → 容量 1 latest-value 帧槽；
- 已完成：固定最短 5 秒语义调度、旧帧覆盖；
- 已完成：板内 `/analyze` HTTP 适配器、`VisualSnapshot` 发布、前端事件和每轮上下文注入；
- 待完成：仓库内实际 RK3588 Qwen/VLM worker、模型加载和板端准确度/延迟验证；
- RKNN 人物/物体/姿态快路径；
- YuNet/SFace 人脸身份与 FER+ 情绪证据；
- 场景变化触发（固定 5 秒节流已实现）；
- 多人说话人时间窗；
- `frame_id`、观察时间、完成时间一致性；
- 每轮无条件注入仍然新鲜的视觉快照。

验收要求：本地预览保持流畅时，机器视觉不能形成帧队列；语义准确度和新鲜度需使用真实人物/室内场景数据集测量。

## Phase 4：拟人表现与视频通话 UX — 连续情感与真实 Live2D 纵切片完成

已完成：

- PC 主舞台、摄像头画中画、通话计时、麦克风/摄像头/挂断控制；
- 移动端安全区和响应式布局；
- 本地预览与视觉上传频率解耦；
- 本地 Cubism/Pixi runtime 与真实 Strawberry_Rabbit 模型；
- 桌面 4096/移动 1024 纹理自适应、ResizeObserver fit、60 FPS ticker 与失败回退；
- 连续参数 SignalMixer、指针视线、呼吸、眨眼、头眼和微笑；
- 实际 WAV 20 ms RMS 包络按播放时间驱动口型；
- 用户/视觉弱情感证据、真实时间衰减、renderer-neutral AvatarIntent；
- listening/thinking/speaking/idle 与 generation/segmentIndex 同步；
- 前端按 sessionId + generation + seq 拒绝旧代/乱序意图；
- 浏览器原生 AvatarActionScheduler：真实 expression/motion、能力过滤、优先级/持续时间/冷却/抢占、代际门控与 RMS 最终混合顺序；
- 1440×900、320×568、390×844、768×1024、1024×768、844×390 Chromium 模型加载与无溢出验证。

待完成：

- viseme、语义重音与动作时间轴；
- 自动生成/校验 AvatarCapabilityManifest、全资产视觉回归和开发动作抽屉；
- 更成熟的端侧情绪分类器替换当前可解释弱证据词典；
- 真机摄像头、麦克风、方向切换、后台恢复和弱网矩阵；
- 视觉回归/E2E 自动化，不只依赖静态截图。

## Phase 5：板端与公网发布 — 部署骨架冻结，评审期间禁止执行

- 已完成：Gateway 同源托管 `web/dist`；
- 已完成：V2 Gateway/Cloudflare systemd 单元、环境模板、一键启动、健康等待与 V1 Tunnel 回滚；
- 已完成：启动脚本加入显式激活锁，默认保护正在评审使用的 V1；
- 当前约束：V2 仅做本机与自动化验证，不部署 ELF2、不切换评审主入口 `anima.veyralux.org`；`robot.veyralux.org` 继续作为 V1 兼容别名；
- 待完成：ELF2 上固定 ASR/TTS/VLM 模型与线程数；
- 待完成：Cloudflare HTTPS/WSS 真实入口、鉴权和限流；

## Phase 6：本机拟真验证 — 进行中

- 已完成：真实 ASGI Gateway、WebSocket binary media、确定性 LLM/VLM/TTS 桩和 Chrome E2E；
- 已完成：六种桌面/手机/平板横竖屏下真实 Live2D、fake camera/mic、音频播放后显字、视觉语义、设置面板、按钮裁切与整页溢出检查；
- 已完成：慢回复被新一轮打断后，旧 generation 文字与声音不会复活；
- 已完成：桌面浏览器强制关闭真实 WebSocket 后指数退避重建连接，并可继续对话；本次本机恢复约 0.8 秒，只是确定性基准，不代表公网 SLO；
- 已完成：E2E 不接触 ELF2、不使用正式 Tunnel，保证 V1 评审链路不变；
- 待完成：丢包/高延迟/限带宽注入、连续多次重连、长会话和内存增长。
- 断网、重连、打断、内存峰值、温度降频和 8 小时 soak；
- 灰度切换 `anima.veyralux.org`，保留 `robot.veyralux.org` 兼容别名与 V1 一键回滚。

## 发布前硬门槛

1. `python -m pytest -q`、`npm run check`、`npm run build` 全部通过；
2. 真实 ELF2 上 ASR → LLM → TTS → 浏览器播放闭环通过；
3. 停止说话到角色开口、打断、视觉新鲜度、Live2D FPS 有 p50/p95 数据；
4. 摄像头本地预览与 5 秒语义更新互不拖慢；
5. PC 和至少两种移动端浏览器完成权限、旋转、重连和安全区测试；
6. 密钥不进入仓库，公网入口有 TLS、鉴权、限流和回滚；
7. 长时间运行无持续内存增长、过热降频导致的不可接受退化或 OOM。
