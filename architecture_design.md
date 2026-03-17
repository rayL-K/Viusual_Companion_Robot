# 虚拟陪伴机器人系统架构设计 (基于 RK3588 异构计算)

## 1. 核心定位与系统条件
- **开发目标**：具备极低延迟、高帧率视觉追踪、情绪动作联动，且以本地高性能 TTS 为核心交互驱动的多模态陪伴机器人。
- **硬件平台**：EC-I3588J (RK3588芯片，内置CPU大核A76x4、小核A55x4， GPU Mali-G610，NPU 6 TOPS)。
- **运行环境**：底层为 Linux（使用 `taskset` 绑定 CPU 核心），UI 为基于 OpenGL ES 硬件加速的 PyQt5/PySide6。
- **设计原则**：**软硬协同（Hardware-Software Co-design）**。通过精准的算力切分，实现 5 个独立进程的无阻塞多进程流水线（Producer-Consumer模式），榨干硬件性能。
- **其他相关约束/全局设定**：
  - 项目或关联模块涉及使用大体积 CSV，编码极大可能为 GBK。
  - 需要配合 MySQL 建立 `input`（输入）和 `output`（输出）表作为持久化支持（或者辅助存储），系统内部交互短期/长期记忆主要基于 SQLite（`data/memory.db`）。

## 2. 核心算力池分配 (硬件资源映射)
为确保各模块互不干扰，严禁使用默认的全局系统调度，必须强绑定硬件资源：

1. **TTS 核心阵地 (CPU 大核 A76 x2)**
   - **资源锁定**：将系统最宝贵的算力锁定给本地化 TTS 引擎。
   - **核心职责**：确保语音合成的实时率（RTF）远小于 1，实现流式秒回。同步提取音频 RMS（均方根）能量值，精准驱动 Live2D 唇形同步（Lip-sync，计算 `ParamMouthOpenY`）。
2. **ASR 听觉阵地 (CPU 大核 A76 x1)**
   - **资源锁定**：绑定 1 个大核运行 Sherpa-onnx 语音识别模块。
   - **核心职责**：配合 VAD（如 Silero-VAD）端点检测，实现环境音中的毫秒级精准过滤与拾音。
3. **UI 与表现层 (GPU Mali-G610)**
   - **资源锁定**：由 GPU 处理，基于 PyQt/PySide 的 OpenGL ES 硬件加速。
   - **核心职责**：接管 Live2D 的骨骼、物理与表情渲染运算，释放 CPU 负担，呈现最终音频、表情、头部追踪效果。
4. **视觉感知追踪 (NPU 6 TOPS + VPU)**
   - **资源锁定**：NPU 算力（`rknn_model_zoo` - RetinaFace 等模型）+ VPU 视频硬解（GStreamer）。
   - **核心职责**：人脸检测与视线解算全部卸载至 NPU/VPU。通过卡尔曼滤波实现平滑目标追踪，保持 60FPS+ 极低功耗运转。
5. **认知与调度大脑 (CPU 小核 A55)**
   - **资源锁定**：剩余 A55 小核心处理器群。
   - **核心职责**：负责轻量级的 LangChain 逻辑调度、长短期记忆数据库（SQLite/MySQL）读写查询，以及协调各核心进程间的 `multiprocessing.Queue` 数据流传递。要求模型输出强约束的 JSON 格式动作指令。

## 3. 五进程异步流水线 (5-Process Pipeline)
系统由 5 个相互独立的进程构成，通过 `multiprocessing.Queue` 进行非阻塞通信：

- **Process 1: Vision_Engine (感知层 - NPU)**
  - 链路：拉取 GStreamer 帧 -> RKNN 人脸检测 -> 卡尔曼滤波 (Kalman Filter) 坐标平滑 -> 坐标压入 `Vision_Queue(maxsize=1)`。
- **Process 2: ASR_Engine (听觉层 - A76)**
  - 链路：麦克风阵列拾音 -> VAD 过滤底噪 -> 截取有效人声 -> Sherpa-onnx 转写 -> 文本压入 `Text_Queue`。
- **Process 3: Cognitive_Brain (认知层 - A55)**
  - 链路：读取 `Text_Queue` -> 提取本地记忆 (SQLite 用户画像/历史对话) -> 组装 System Prompt -> 调用 LLM（强制输出 JSON，例如：`{"text": "辛苦啦，喝杯水吧", "emotion": "smile", "action": "nod"}`） -> JSON 压入 `Action_Queue`。
- **Process 4: TTS_Engine (表达层 - A76 核心主战场)**
  - 链路：读取 `Action_Queue` -> 解析 JSON 获取文本与情绪动作 -> 运行本地声码器产出音频流 (Audio Buffer) -> 同步提取 Lip_Feature -> 把 `(Audio_Buffer, Lip_Feature, emotion, action)` 元组打包压入 `UI_Queue`。
- **Process 5: UI_Live2D_Main (主进程 - GPU)**
  - 链路：运行 GUI (PyQt) 事件循环 -> 非阻塞读取 `Vision_Queue` 更新头部追踪 (LookAt) -> 监听 `UI_Queue` 播放音频并同步驱动 Live2D 模型表情/嘴型。

## 4. 标准代码目录结构
```text
ec_i3588_companion/
├── main.py                     # 程序入口，初始化 5 个进程与 Queue，设定 CPU 绑核逻辑
├── config.yaml                 # 统筹配置 (硬件设配号, 角色 Prompt, 记忆库路径)
├── core/
│   ├── vision_npu.py           # 视觉感知 (GStreamer + RKNN + 卡尔曼滤波)
│   ├── audio_asr.py            # 语音识别 (Sherpa-onnx + Silero-VAD)
│   ├── brain_llm.py            # 认知大脑 (LangChain + Prompt 工程 + 记忆读取)
│   └── tts_engine.py           # 语音合成 (本地模型 + 唇形特征提取)
├── ui/
│   ├── main_window.py          # GUI 框架与状态悬浮窗 (参考 AIRI 灵动岛机制)
│   └── live2d_controller.py    # 动作映射与 OpenGL 硬件加速渲染
├── data/
│   └── memory.db               # 本地 SQLite 数据库 (长短时记忆)
└── requirements.txt
```

## 5. 当前开发阶段与进展
- **Phase 1**：✅ 彻底打通 5 大独立进程的总线框架 (`main.py`)，完成基于 `spawn` 调用的进程池编排。实现进程间通讯 Queue 链路，并加入 `taskset` 资源锁定预留代码和无僵尸进程的 Graceful Shutdown 安全退出机制。
- **Phase 2（待完成）**：逐一向 `core/` 下的引擎驱动文件填补并验证真实业务 SDK 调用（例如集成 `GStreamer` 和 `Sherpa-onnx`）。
