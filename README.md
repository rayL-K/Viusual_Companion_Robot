# Visual Companion Robot

基于 Firefly/RK3588 的多模态 AI 陪伴机器人。透过摄像头感知用户场景，结合 LLM 生成带情绪的个性化回复，驱动 Live2D 虚拟形象做出匹配的表情动作。Windows 笔记本为主要开发环境，Firefly 板卡为目标运行环境。

## 作品定位

本项目是一个**能看、能听、能说、能演**的桌面 AI 伴侣。它通过摄像头实时理解用户所在的场景和活动，将视觉上下文注入 LLM 对话，生成符合角色人设的回复，并自动映射为 Live2D 表情动作播放。

不再是"你说一句我回一句"的聊天机器人，而是会主动观察、会察言观色、会用动作表达情绪的虚拟伙伴。

## 闭环架构

```
┌─────────────────────────────────────────────────┐
│                   RobotRuntime                    │
│                                                   │
│  摄像头 ──→ SceneAnalyzer ──→ DialogueContext     │
│              (Qwen3-VL)         (视觉上下文)       │
│                                    │              │
│  用户输入 ─────────────────→  LLM (DeepSeek-V3)   │
│                                    │              │
│                              ┌─────┴─────┐        │
│                              │ 回复文本    │        │
│                              │ 情绪标签    │        │
│                              │ 动作映射    │        │
│                              └─────┬─────┘        │
│                                    │              │
│   Live2D ←── TTS ←── 展示文本 ←───┘              │
│   (动作播放)  (语音)  (去括号)                    │
└─────────────────────────────────────────────────┘
```

三层 prompt 驱动角色人格：System Prompt（人设+视觉+时间）→ 对话历史 → 用户输入。

## 模块清单

| 模块 | 状态 | 说明 |
|------|:----:|------|
| **视觉感知** | ✅ | Qwen3-VL-8B 通过硅基流动 API，国内直连 3-6s/帧，中文场景描述+活动识别+情绪推断+人数统计 |
| **LLM 对话** | ✅ | DeepSeek-V3，含视觉上下文注入、角色人格 system prompt、多轮记忆 |
| **Live2D 展示** | ✅ | Strawberry_Rabbit 模型，表情/动作/口型/鼠标跟随/待机/拖拽缩放 |
| **动作映射** | ✅ | 80+ 关键词 + 子 LLM 兜底 + 缓存，精准映射到 27 个 Live2D 动作 |
| **语音合成 (TTS)** | ✅ | VoxCPM2 本地推理 / 公网 API / Gradio 桥接，TTSInterface 抽象层 |
| **语音识别 (ASR)** | ⚙️ | ASRInterface 抽象层 + sherpa-onnx 后端已定义，待接入麦克风 |
| **语音打断 (VAD)** | ⚙️ | Silero VAD 3 状态机已实现，待接入音频流 |
| **记忆模块** | ✅ | SQLite 对话轮次存储，DialogueContext 维护视觉+对话上下文 |
| **消息总线** | ✅ | RobotEvent + 事件类型常量，解耦模块通信 |
| **Firefly 部署** | ⚙️ | 同步脚本就绪，待板端适配 RKNN |

## 项目结构

```text
main/
├── app.py                          # 板端入口（待接入 RobotRuntime）
├── config/                         # 应用配置、TTS、嘴型配置
├── requirements.txt                # Python 依赖
├── src/visual_companion_robot/
│   ├── perception/                 # 感知层
│   │   ├── vision.py               #   PerceptionFrame 数据结构
│   │   ├── scene_analyzer.py       #   Qwen3-VL 场景分析器
│   │   ├── perception_loop.py      #   摄像头→视觉→总线 主循环
│   │   ├── asr_interface.py        #   ASR 抽象基类 + 工厂
│   │   ├── sherpa_onnx_asr.py      #   sherpa-onnx 后端
│   │   └── vad.py                  #   Silero VAD 语音打断
│   ├── brain/                      # 对话决策层
│   │   ├── dialogue.py             #   DialogueContext + DialogueTurn
│   │   └── memory.py               #   SQLite 记忆存储
│   ├── speech/                     # 语音输出层
│   │   └── tts_interface.py        #   TTS 抽象基类 + 工厂
│   ├── voice/                      # 语音引擎
│   │   └── voxcpm_local.py         #   VoxCPM2 本地推理
│   ├── runtime/                    # 运行时
│   │   ├── robot.py                #   RobotRuntime 闭环主循环
│   │   ├── bus.py                  #   消息总线
│   │   └── config.py               #   配置加载
│   └── ui/live2d/                  # Live2D 控制
│       ├── controller.py           #   动作/表情控制
│       └── mouth_sync.py           #   口型同步
├── live2d_stage/                   # Vite Live2D 网页控制台
├── scripts/                        # 控制服务、测试脚本
├── visual-perception/              # 独立视觉管线（MediaPipe 备用）
└── models/moondream2/              # Moondream 2 本地模型（备用）
```

## 快速开始

```powershell
# 1. 环境
conda activate companion

# 2. 密钥
set SILICONFLOW_KEY=sk-your-key-here

# 3. 测试闭环
python -c "
import sys; sys.path.insert(0,'main/src')
from visual_companion_robot.runtime.robot import RobotRuntime, RobotConfig
rt = RobotRuntime(RobotConfig(
    vision_api_key='sk-xxx',
    llm_api_key='sk-xxx',
    llm_model='deepseek-ai/DeepSeek-V3',
    llm_base_url='https://api.siliconflow.cn/v1',
    debug=True,
))
resp = rt.run_once('你好！')
print(resp.display_text)
print(resp.emotion, resp.actions)
"
```

## 当前依赖

| 服务 | 使用 |
|------|------|
| 硅基流动 API | Qwen3-VL-8B（视觉）+ DeepSeek-V3（对话） |
| VoxCPM2 | TTS 语音合成（本地模型） |
| Strawberry_Rabbit | Live2D 角色模型 |

## 后续路线

1. 接入麦克风 → VAD → ASR 语音输入闭环
2. TTS 播放集成 → 口型同步
3. Live2D 前端接收 RobotResponse 动作/情绪
4. Firefly RK3588 板端部署适配
5. 人脸身份注册与识别
