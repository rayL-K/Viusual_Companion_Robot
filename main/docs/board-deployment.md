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
| 场景视觉 | `BoardVisionService` + YOLOv5s RKNN | `main/models/yolo/yolov5s-640-640.rknn` | 必需；缺失时控制服务拒绝启动 |
| 语义视觉 | Qwen3-VL-2B W8A8 + FP16 Vision RKNN | `/opt/visual-companion-vlm/` | 必需；常驻服务异步分析场景关键帧 |
| 人脸检测 | OpenCV YuNet | `main/models/face/yunet.onnx` | 必需；情绪服务拒绝带病启动 |
| 本地身份 | OpenCV SFace | `main/models/face/sface.onnx` | 必需；只保存登记特征，不保存原图 |
| 人体姿态 | YOLOv8n-pose RKNN | `main/models/pose/yolov8n-pose.rknn` | 必需；输出 17 点骨架和保守姿态语义 |
| 本地 LLM | GGUF/llama.cpp 路线 | `main/models/qwen/*.gguf` | 仅 `backend.llm=local` 时 |
| 板端情绪 | FER+ ONNX 服务 | `main/models/emotion/emotion-ferplus-8.onnx` | 必需；由统一 `/vision` 接口调用 |
| 主动说话人 | Light-ASD ONNX | `main/models/active_speaker/light-asd-ava.onnx` | 必需；由 `/active-speaker` 接收同步 PCM 与人脸帧 |
| 离线 ASR | sherpa-onnx SenseVoice INT8 | `main/models/asr/` | 使用麦克风离线识别时 |
| 实时 TTS | sherpa-onnx Matcha Baker + Vocos | `main/models/tts/matcha-zh-baker/` | 必需；默认连续对话音色 |
| 参考音色 TTS | VoxCPM.cpp + VoxCPM1.5 Q4 | `/opt/visual-companion-voxcpm/` | 必需安装、按请求运行；不常驻 |

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

目标板当前出厂 Python 版本为 3.10：

```bash
python3.10 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r main/config/requirements-board.txt
python -m pip install --no-deps -e main

# 安装板端 VoxCPM.cpp 与固定 Q4 模型；不能直连模型站时设置 VOXCPM_MODEL_SOURCE
chmod +x tools/board/install_voxcpm_cpp.sh
tools/board/install_voxcpm_cpp.sh

# 安装登录后的短命令（只需执行一次）
chmod +x tools/board/start_all.sh
ln -sfn "$PWD/tools/board/start_all.sh" "$HOME/start-robot"
```

RKNNLite 必须使用与板端 `librknnrt 2.1.0` 匹配的官方 ARM64 wheel：
`rknn_toolkit_lite2-2.1.0-cp310-cp310-linux_aarch64.whl`。视觉链路不提供
云端、浏览器或 ONNX CPU 降级；模型或 NPU 不可用时部署验收必须失败。

## 构建和启动

```bash
# 前端构建
cd main/live2d_stage
npm ci
npm run check
npm run build
cd ../..

# 情绪服务（控制服务的强依赖）
python -m visual_companion_robot.perception.emotion_server &

# 控制服务（VoxCPM 按 /tts 请求启动，完成后释放）
python main/scripts/live2d_control_server.py &

# 静态前端
python -m http.server 8080 -d main/live2d_stage/dist &
```

浏览器打开 `http://127.0.0.1:8080/`。控制服务和情绪服务默认只监听本机，
无需向局域网开放端口。

## 板端验收清单

1. 记录系统镜像、Python、RKNNLite、rknpu2 和模型版本。
2. 验证摄像头、麦克风、浏览器 WebGL 与音频输出设备。
3. 分别测量视觉、Light-ASD、LLM、ASR、Matcha 与 VoxCPM 的冷启动、稳态延迟、峰值内存和温度。
4. 验证断网、模型缺失、服务退出时会明确失败，且不会切换到云端或客户端推理。
5. 运行不少于 30 分钟的连续交互，检查内存增长、设备释放和进程恢复。
6. 用含多人和真实音轨的视频验证 `/active-speaker`；低置信度或候选接近时必须返回 `unknown`。
7. 连续切换 Matcha/VoxCPM，确认 Vox 请求结束后 `voxcpm-server` 不残留，VLM、控制网关和 Cloudflare Tunnel 不被内存压力杀死。

日常启动和升级统一执行 `~/start-robot` 或 `~/start-robot restart`。脚本会从仓库刷新四个 systemd 单元，并移除早期版本可能遗留的常驻 VoxCPM 单元；Tunnel 不再强依赖控制服务，因此控制/VLM 重启期间仍保留正式连接器。

服务启动后执行 `tools/board/verify_deployment.sh`。它会把 systemd 状态、本地六组健康接口、正式公网回源、Vox 模型 SHA-256 与空闲进程释放作为同一验收门槛，任一失败都会返回非零状态。
