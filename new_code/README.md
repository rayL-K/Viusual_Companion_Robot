# VeyraSoul V2

`new_code/` 是虚拟陪伴机器人 V2 的独立实现。旧系统保持冻结，只作为行为参照与迁移数据源；V2 不复制旧系统的单文件前端、同步串行控制服务器或“最近若干轮即记忆”的设计。

## 产品目标

让角色表现为持续存在、能感知、能记住、会形成情绪连续性的“虚拟生命体”，同时保证 RK3588 单板可运行和公网交互低时延。

核心原则：

1. **感知持续、回答取快照**：视觉和听觉持续更新；对话在用户话音结束时获取同一时刻的感知快照，不临时等待一轮完整视觉推理。
2. **最新值优先**：视频、姿态和语义是 latest-value 数据，不允许旧帧排队。
3. **可取消流水线**：ASR、LLM、TTS 和动作计划都带会话序号；用户打断后旧任务立即失效。
4. **文字与声音同步出现**：先准备首个可播放语音块，再同步展示对应文本，不采用“文字全部先出、TTS 很久后才跟上”。
5. **情绪是连续状态**：使用 valence/arousal/dominance/affinity/trust 连续状态驱动语气、表情和微动作，不随机刷表情。
6. **本地隐私优先**：视觉、ASR、TTS、记忆和 RAG 在 ELF2；DeepSeek Flash 仅处理裁剪后的语言上下文。
7. **VoxCPM 永不自动切换**：只有用户主动选择时才加载 VoxCPM。

## 目录

```text
new_code/
├── backend/                 # 板端会话编排、记忆、RAG、模型适配器
├── web/                     # PC 优先、移动端可用的 Preact + TypeScript 前端
├── docs/                    # 架构、SLO、协议和迁移决策
└── scripts/                 # Windows / ELF2 检查与启动脚本（逐步补齐）
```

## 当前可运行检查

```powershell
cd E:\CODE\Visual_Companion_Robot\new_code\backend
python -m pytest -q

cd ..\web
npm install
npm run check
npm run build
```

完整实施路线见 [`docs/implementation-roadmap.md`](docs/implementation-roadmap.md)。
