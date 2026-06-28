# Visual Companion Robot

基于 ELF2 (RK3588) 的多模态 AI 陪伴机器人。透过摄像头感知用户场景，结合 LLM 生成带情绪的个性化回复，驱动 Live2D 虚拟形象做出匹配的表情动作。Windows 10 为开发环境，ELF2 板卡为目标运行环境。

## 作品定位

本项目是一个**能看、能听、能说、能演**的桌面 AI 伴侣。它通过摄像头实时理解用户所在的场景和活动，将视觉上下文注入 LLM 对话，生成符合角色人设的回复，并自动映射为 Live2D 表情动作播放。

不再是"你说一句我回一句"的聊天机器人，而是会主动观察、会察言观色、会用动作表达情绪的虚拟伙伴。

## 闭环架构

```mermaid
flowchart TB
    subgraph ELF2["ELF2 (RK3588) 板端"]
        subgraph Input["输入层"]
            CAM["摄像头采集<br/>perception_loop.py"]
            MIC["麦克风采集<br/>sherpa-onnx ASR + VAD"]
            CHROME["Chromium 浏览器<br/>Live2D (WebGL)<br/>MediaPipe 人脸<br/>FER+ 情绪分类"]
        end

        subgraph Vision["视觉分析"]
            SA["SceneAnalyzer (双后端)"]
            SA_C["Cloud: Qwen3-VL API"]
            SA_L["Local: YOLO NPU<br/>+ Qwen0.5B 描述"]
            SA --- SA_C
            SA --- SA_L
        end

        subgraph LLM["对话决策"]
            RT["RobotRuntime + DialogueContext"]
            LLM_C["Cloud: DeepSeek API"]
            LLM_L["Local: Qwen2.5-1.5B<br/>(GGUF / CPU)"]
            RT --- LLM_C
            RT --- LLM_L
        end

        subgraph TTS["语音合成"]
            TTS_B["TTS (双后端)"]
            TTS_V["VoxCPM2 (2B)"]
            TTS_S["sherpa-onnx VITS TTS"]
            TTS_B --- TTS_V
            TTS_B --- TTS_S
        end

        L2D["Live2D 表情 + 嘴型同步"]
    end

    subgraph Cloud["云端服务"]
        DS["DeepSeek API<br/>(LLM 对话)"]
        OM["Open-Meteo API<br/>(天气查询)"]
    end

    CAM --> SA
    MIC --> RT
    CHROME --> SA
    SA --> RT
    RT --> TTS_B
    TTS_B --> L2D
    RT -.->|网络| DS
    RT -.->|网络| OM
```

## 模块清单

| 模块 | 状态 | 说明 |
|------|:----:|------|
| **视觉感知** | 🧪 | 云端 Qwen3-VL 与本地 YOLO/RKNN 双后端已实现；云端需密钥，NPU 路径待 ELF2 实机验证 |
| **LLM 对话** | 🧪 | DeepSeek 与本地 GGUF 双后端及统一 `LlmContext` 已实现；在线与板端模型需分别验收 |
| **Live2D 展示** | ✅ | Strawberry_Rabbit 模型，表情/动作/口型/鼠标跟随/待机/拖拽缩放 |
| **动作映射** | ✅ | 80+ 关键词 + 缓存，精准映射到 27 个 Live2D 动作 |
| **情绪识别** | 🧪 | FER+ ONNX、HTTP/CORS、真实摄像头预览与无脸回退已在 Win10 验证；真人表情和板端性能待验收 |
| **语音合成 (TTS)** | 🧪 | sherpa-onnx Aishell3 已接入网页并在 Win10 完成真实播放；VoxCPM2 与板端音质/延迟待验收 |
| **语音识别 (ASR)** | 🧪 | AudioWorklet → WebRTC VAD → SenseVoice INT8 离线闭环已在 Win10 验证；真人识别率待调校 |
| **语音打断 (VAD)** | 🧪 | WebRTC VAD 已用于句段过滤，播放期间会暂停采集防回声；真人打断策略待实现和调校 |
| **记忆模块** | ✅ | SQLite 对话轮次存储，DialogueContext 维护视觉+对话上下文 |
| **消息总线** | ✅ | RobotEvent + 事件类型常量，解耦模块通信 |
| **ELF2 部署** | ⚙️ | 配置就绪，待板端安装依赖 |

## 项目结构

```text
main/
├── config/
│   ├── app.yaml                    # 双后端配置（backend/model_paths/npu）
│   └── requirements-board.txt      # RK3588 板端依赖清单
├── src/visual_companion_robot/
│   ├── integrations/               # 模型运行时 + 外部服务集成
│   │   ├── model_runtime.py        #   RknnEngine / RkllmEngine / OnnxEngine
│   │   ├── model_assets.py         #   模型安全下载与解压
│   │   ├── llm_client.py           #   LlmClient 抽象 + DeepSeek/Local 双实现
│   │   └── web_context.py          #   Open-Meteo 天气查询
│   ├── perception/                 # 感知层
│   │   ├── vision.py               #   PerceptionFrame 数据结构
│   │   ├── detector.py             #   YOLO NPU 检测器
│   │   ├── scene_analyzer.py        #   双后端场景分析器
│   │   ├── emotion.py              #   FER+ ONNX 情绪识别
│   │   ├── emotion_server.py       #   情绪推理 HTTP 服务
│   │   ├── perception_loop.py      #   摄像头→视觉→总线 主循环
│   │   ├── asr_interface.py        #   ASR 抽象基类 + 工厂
│   │   ├── sherpa_onnx_asr.py      #   SenseVoice INT8 后端
│   │   ├── offline_asr_service.py  #   PCM16 / VAD / ASR 编排
│   │   └── vad.py                  #   WebRTC VAD 语音打断
│   ├── brain/                      # 对话决策层
│   │   ├── dialogue.py             #   DialogueContext + DialogueTurn
│   │   └── memory.py               #   SQLite 记忆存储
│   ├── speech/                     # 语音输出层
│   │   └── tts_interface.py        #   TTS 抽象基类 + 工厂
│   ├── voice/                      # 语音引擎
│   │   ├── voxcpm_local.py         #   VoxCPM2 本地推理
│   │   └── sherpa_tts.py          #   sherpa-onnx TTS 轻量后端
│   ├── runtime/                    # 运行时
│   │   ├── robot.py                #   RobotRuntime 闭环主循环
│   │   ├── bus.py                  #   消息总线
│   │   └── config.py               #   双后端配置加载
│   └── ui/live2d/                  # Live2D 控制
│       ├── controller.py           #   动作/表情控制
│       └── mouth_sync.py           #   口型同步
├── live2d_stage/                   # Vite Live2D 网页控制台
│   └── src/
│       ├── stage.js                #   主舞台 + 真实运行后端状态面板
│       ├── offline-asr-client.js   #   PCM 句段切分与本机 ASR 客户端
│       ├── emotion-onnx-client.js  #   情绪分类（调用后端 FER+）
│       └── perception-client.js    #   MediaPipe 人脸追踪
└── tools/
    ├── download_emotion_ferplus.py # FER+ 模型下载
    ├── export_yolo_rknn.py         # YOLO ONNX → RKNN 导出
    └── integration_test.py         # 端到端集成测试
```

## 快速开始

### 开发环境 (Windows 10)

```powershell
# 1. 创建/更新环境（PowerShell 7 非必需）
tools\launchers\setup_conda.bat

# 2. 自动化回归
tools\launchers\test_live2d.bat

# 3. 启动 Live2D 菜单
tools\launchers\live2d_stage.bat
```

外部服务密钥只放在当前终端环境变量，或被 Git 忽略的
`main/config/local.env` 中；不得写入受版本控制的文件：

```powershell
$env:DEEPSEEK_API_KEY = "..."
$env:SILICONFLOW_KEY = "..."
```

### 部署环境 (ELF2 RK3588)

```bash
# 1. 安装板端依赖
pip install -r main/config/requirements-board.txt

# 2. 下载模型
python tools/download_emotion_ferplus.py

# 3. 配置本地后端
#    main/config/app.yaml 中 backend 设为 local

# 4. 启动情绪服务
python -m visual_companion_robot.perception.emotion_server &

# 5. 启动主程序
python main/app.py
```

## 技术栈

| 层 | 技术 |
|------|------|
| **后端语言** | Python 3.11 |
| **NPU 推理** | rknn-toolkit2 (YOLO) |
| **CPU 推理** | llama-cpp-python (Qwen2.5), onnxruntime (FER+) |
| **语音** | sherpa-onnx (ASR/TTS), webrtcvad (VAD) |
| **前端** | Vite 8 + PixiJS 6 + Live2D Cubism |
| **浏览器 AI** | MediaPipe Tasks-Vision (人脸) |
| **云端** | DeepSeek API, 硅基流动 API, Open-Meteo API |
| **硬件** | ELF2 (RK3588, 6 TOPS NPU) |

## 后续路线

1. 在真人交互中调校 SenseVoice 句段阈值、人脸情绪、语音打断与动作映射
2. 在 ELF2/RK3588 上验收 YOLO/RKNN、SenseVoice、轻量 TTS 与本地 LLM 的延迟和内存占用
3. 补齐 VoxCPM2 模型与授权音色资源后，验收音质、缓存和断网降级
4. 实现可抢占当前 TTS 的真人语音打断策略
