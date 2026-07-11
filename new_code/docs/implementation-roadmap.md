# V2 实施路线

## Phase 0：冻结与证据（已完成）

- 旧代码源码 ZIP；
- 全 Git 历史 bundle；
- 未跟踪比赛材料 ZIP；
- SHA-256 manifest 与工作区状态。

## Phase 1：内核（当前）

- 事件契约、latest-value、generation/cancellation；
- SQLite WAL 记忆、事实修订、FTS5 RAG、向量融合接口；
- AffectState 与 AvatarIntent；
- 单元测试与性能基准。

## Phase 2：实时纵向链路

- ASGI Gateway 与二进制 WebSocket；
- AudioWorklet PCM、online ASR partial/final；
- DeepSeek Flash 非思考流式输出；
- 首短句 TTS pipeline；
- 同步文字/音频/动作事件。

## Phase 3：感知

- 迁移 RKNN、YuNet/SFace/FER+ 适配器；
- 快/慢路径调度、场景变化触发；
- 多人说话人时间窗；
- 感知时间线和上下文快照。

## Phase 4：拟人表现与 UI

- Live2D 参数所有权混合器；
- 呼吸、眼跳、注视、倾听/思考/被打断状态；
- PC 舞台主视图与移动端 bottom sheet；
- 真实摄像头、麦克风和弱网测试。

## Phase 5：板端与发布

- systemd 单元、内存/CPU/NPU 预算；
- Cloudflare Worker V2 路由；
- soak、断网、重连、打断和 OOM 测试；
- 灰度切换 `robot.veyralux.org`，保留 V1 一键回滚。
