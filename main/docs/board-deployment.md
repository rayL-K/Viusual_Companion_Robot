# Firefly RK3588 板端部署指南

本文只描述当前代码真实支持的部署路径。所有 NPU、CPU 延迟和内存数据必须在
目标 ELF2 板卡上实测，不使用开发机或理论值代替。

## 同步内容

```text
Visual_Companion_Robot/
├── main/
│   ├── src/                      # Python 业务模块
│   ├── scripts/                  # 控制服务和检查脚本
│   ├── live2d_stage/             # Vite 前端
│   ├── config/                   # 板端依赖与运行配置
│   └── assets/                   # Live2D 与授权参考音频
├── tools/                        # 同步、启动与模型工具
└── README.md
```

`main/models/` 不进入 Git，应在目标设备或部署介质中单独准备。

## 按启用模块准备模型

| 模块 | 当前代码路径 | 模型位置 | 是否必需 |
| --- | --- | --- | --- |
| 本地视觉 | `YoloDetector` + `RknnEngine` | `main/models/yolo/*.rknn` | 仅 `backend.vision=local` 时 |
| 本地 LLM | GGUF/llama.cpp 路线 | `main/models/qwen/*.gguf` | 仅 `backend.llm=local` 时 |
| 浏览器情绪 | FER+ ONNX 服务 | `main/models/emotion/emotion-ferplus-8.onnx` | 需要 FER+ 增强时 |
| 离线 ASR | sherpa-onnx SenseVoice INT8 | `main/models/asr/` | 使用麦克风离线识别时 |
| 轻量 TTS | sherpa-onnx VITS | `main/models/tts/sherpa-onnx/` | 使用轻量本地 TTS 时 |
| VoxCPM2 | 项目内 Python 推理 | `main/models/voxcpm/VoxCPM2/` | 可选；必须先评估板端资源 |

仓库当前没有 Moondream 运行链路，不需要下载 Moondream 权重。

FER+ 模型可在联网开发机上准备：

```bash
python tools/download_emotion_ferplus.py
```

YOLO ONNX 转 RKNN 时必须使用真实代表性校准图片：

```bash
python tools/export_yolo_rknn.py \
  --onnx main/models/yolo/yolo.onnx \
  --output main/models/yolo/yolo.rknn \
  --dataset main/models/yolo/quant_dataset.txt
```

## 板端环境

目标 Python 版本为 3.11：

```bash
python3.11 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r main/config/requirements-board.txt
python -m pip install --no-deps -e main
```

RKNNLite、rknpu2 和 llama-cpp-python 需要按板卡系统镜像与厂商 SDK 单独安装，
不能直接使用 Windows 开发机的二进制包。

## 构建和启动

```bash
# 前端构建
cd main/live2d_stage
npm ci
npm run check
npm run build
cd ../..

# 情绪服务（可选）
python -m visual_companion_robot.perception.emotion_server &

# 控制服务
python main/scripts/live2d_control_server.py &

# 静态前端
python -m http.server 8080 -d main/live2d_stage/dist &
```

浏览器打开 `http://127.0.0.1:8080/`。控制服务和情绪服务默认只监听本机，
无需向局域网开放端口。

## 板端验收清单

1. 记录系统镜像、Python、RKNNLite、rknpu2 和模型版本。
2. 验证摄像头、麦克风、浏览器 WebGL 与音频输出设备。
3. 分别测量视觉、LLM、ASR、TTS 的冷启动、稳态延迟、峰值内存和温度。
4. 验证断网、模型缺失、服务退出时的错误提示和降级行为。
5. 运行不少于 30 分钟的连续交互，检查内存增长、设备释放和进程恢复。
