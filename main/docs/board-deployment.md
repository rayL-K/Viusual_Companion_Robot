# Firefly RK3588 板端部署指南

## 需拷贝的目录

```text
Visual_Companion_Robot/
├── main/
│   ├── src/                      # 业务模块（全部）
│   ├── scripts/                  # 控制服务 + 测试脚本
│   ├── live2d_stage/             # Vite 前端（先 npm run build）
│   ├── config/                   # 配置文件 + local.env
│   ├── assets/                   # Live2D 模型 + TTS 参考音频
│   └── requirements.txt          # Python 依赖
├── tools/sync_firefly.bat        # Windows→板端同步脚本（参考）
└── README.md
```

## 需下载的大模型文件

### 1. VoxCPM2（TTS 语音合成）— 必需
```bash
# 从 HuggingFace 镜像下载
git clone https://hf-mirror.com/OpenBMB/VoxCPM2 main/models/voxcpm/VoxCPM2
# 约 4GB，下载后放在 main/models/voxcpm/VoxCPM2/
```

### 2. Moondream 2（视觉场景理解）— 必需
```bash
# 方案A: 从 hf-mirror 下载模型文件
mkdir -p main/models/moondream2
# 下载 model.safetensors (3.6GB) + config.json + tokenizer.json 等
# 从 https://hf-mirror.com/vikhyatk/moondream2 下载全部文件

# 方案B: 用 snapshot_download（需网络）
python -c "
from huggingface_hub import snapshot_download
snapshot_download('vikhyatk/moondream2',
    local_dir='main/models/moondream2',
    endpoint='https://hf-mirror.com')
"
```

### 3. Qwen2.5-1.5B-Instruct（LLM 对话）— 必需
```bash
# 方案A: llama.cpp GGUF 格式（推荐，ARM 优化最好）
# 下载地址: https://hf-mirror.com/Qwen/Qwen2.5-1.5B-Instruct-GGUF
# 选择 q4_k_m.gguf (~1GB)
mkdir -p main/models/llm
# 放入 main/models/llm/qwen2.5-1.5b-q4_k_m.gguf

# 方案B: PyTorch 原始格式
# git clone https://hf-mirror.com/Qwen/Qwen2.5-1.5B-Instruct
```

### 4. sherpa-onnx ASR 模型（语音识别）— 必需
```bash
# 首次运行自动下载，或手动下载放入 main/models/asr/
mkdir -p main/models/asr/sense-voice
# 需下载: model.onnx (~80MB) + tokens.txt
# 从 https://github.com/k2-fsa/sherpa-onnx/releases 下载
```

## 模型文件总览

| 模块 | 模型 | 大小 | 路径 |
|------|------|------|------|
| TTS | VoxCPM2 | ~4GB | `main/models/voxcpm/VoxCPM2/` |
| 视觉 | Moondream 2 | ~3.6GB | `main/models/moondream2/` |
| LLM | Qwen2.5-1.5B GGUF | ~1GB | `main/models/llm/` |
| ASR | SenseVoice ONNX | ~80MB | `main/models/asr/sense-voice/` |
| **总计** | | **~8.7GB** | |

## 板端启动步骤

```bash
# 1. 安装依赖
pip install -r main/config/requirements-board.txt

# 2. 配置密钥
cp main/config/local.env.board main/config/local.env
# 编辑 local.env，填入 SILICONFLOW_KEY（开发期备用）

# 3. 构建前端
cd main/live2d_stage
npm install && npm run build

# 4. 启动控制服务
python main/scripts/live2d_control_server.py &

# 5. 启动前端（静态文件服务）
python -m http.server 8080 -d main/live2d_stage/dist &

# 6. 打开浏览器
# http://localhost:8080
```

## 板端推理性能预估 (RK3588)

| 模块 | 推理时间 | 说明 |
|------|:------:|------|
| Moondream 2 (视觉) | 3-8s | CPU bf16，NPU 加速后可降到 1-2s |
| Qwen2.5-1.5B (LLM) | 10-20 tok/s | llama.cpp ARM NEON 优化 |
| VoxCPM2 (TTS) | 2-5s/句 | CPU 推理 |
| SenseVoice (ASR) | <0.5s | sherpa-onnx ARM |
