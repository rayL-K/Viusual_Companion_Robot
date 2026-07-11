# ELF2（RK3588）部署说明

> 本文记录当前 V2 Gateway、systemd 单元和一键启动脚本。配置已经进入仓库，但尚未在 ELF2 上完成真实模型与公网切换验收。

## 1. 运行环境

- Ubuntu 22.04 aarch64（ELF2 当前系统）；
- Python 3.10–3.12；
- Node.js 仅用于构建前端，生产板可只部署 `web/dist`；
- sherpa-onnx 的 aarch64/Python wheel 及其模型资产；
- 可访问 DeepSeek API 的网络；
- HTTPS/WSS 反向代理用于手机和公网媒体权限。

## 2. 安装后端

```bash
cd ~/Visual_Companion_Robot/new_code/backend
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[gateway,models]'
```

开发/测试环境再安装：

```bash
python -m pip install -e '.[gateway,models,test]'
python -m pytest -q
```

## 3. 模型目录约定

### TTS（当前 Gateway 启动必需）

`VEYRASOUL_TTS_MODEL_DIR` 指向 sherpa-onnx Kokoro、Matcha 或 VITS 目录。适配器按资产布局自动判断类型。

```text
tts-model/
├── model.int8.onnx 或 model.onnx
├── tokens.txt
├── voices.bin              # 存在时按 Kokoro 加载
├── lexicon.txt             # 可选
├── dict/                   # 可选
├── espeak-ng-data/         # 可选
└── phone/date/number.fst   # 可选
```

中英混合能力取决于所选模型和语言资产，适配器本身不能让单语模型自动支持英文。VoxCPM 不会自动加载。

仓库旧模型目录中的 Matcha Baker 布局也可直接加载：`model-steps-3.onnx`、`vocos-22khz-univ.onnx`、`tokens.txt`、`lexicon.txt`。CLI 在开放端口前预加载 ASR/TTS，共享模型冷启动不会落到第一位用户身上。

### Streaming ASR

现有适配器期望：

```text
asr-model/
├── tokens.txt
├── encoder*.onnx
├── decoder*.onnx
├── joiner*.onnx
├── itn_zh_number.fst       # 可选
└── rule.fst                # 可选
```

若同前缀同时存在普通和 int8 ONNX，适配器优先选择文件名包含 `int8` 的版本。

`gateway/__main__.py` 已把该目录构造成 `AppServices.asr`，因此命令行启动时 ASR 目录是必需配置。模型会在建立 WebSocket 并创建 ASR session 时加载；仍需在 ELF2 上验证 wheel、模型文件和实时率。

### 板内语义 VLM 服务

Gateway 当前不直接加载 Qwen 模型，而是请求同机 HTTP 服务：

```text
GET  /health
POST /analyze
body: {"image": "<base64-jpeg>"}
response: {"ok": true, "semantic_caption": "自然语言画面描述"}
```

默认地址为 `http://127.0.0.1:8767`。latest-value 调度器保证同一会话只保留最新 JPEG，并默认每 5 秒最多启动一次分析；共享 `LocalVlmClient` 再用单实例锁串行访问板端 worker。仓库当前只有客户端适配器，不包含 `/analyze` 服务实现，因此仍需部署现有板端 VLM worker 才能形成真实视觉闭环。

## 4. 环境变量

| 变量 | 必需 | 默认值 | 当前用途 |
| --- | :---: | --- | --- |
| `DEEPSEEK_API_KEY` | 是 | 无 | DeepSeek Authorization；禁止提交仓库 |
| `DEEPSEEK_MODEL` | 否 | `deepseek-v4-flash` | API model 名称，需与账户实际可用模型一致 |
| `DEEPSEEK_MAX_TOKENS` | 否 | `256` | 单轮最大输出 token；代码限制在 32–2048 |
| `VEYRASOUL_ASR_MODEL_DIR` | 是 | 无 | streaming Zipformer 模型目录 |
| `VEYRASOUL_ASR_THREADS` | 否 | `4` | ASR CPU 线程 |
| `VEYRASOUL_ASR_DECODING_METHOD` | 否 | `greedy_search` | sherpa 解码方式 |
| `VEYRASOUL_ASR_RULE1_SILENCE` | 否 | `1.6` | endpoint rule 1 trailing silence |
| `VEYRASOUL_ASR_RULE2_SILENCE` | 否 | `0.55` | endpoint rule 2 trailing silence |
| `VEYRASOUL_ASR_RULE3_LENGTH` | 否 | `20.0` | endpoint rule 3 最短句长 |
| `VEYRASOUL_ASR_QUEUE_FRAMES` | 否 | `50` | ASR PCM 有界队列帧数 |
| `VEYRASOUL_TTS_MODEL_DIR` | 是 | 无 | Kokoro/Matcha/VITS 模型目录 |
| `VEYRASOUL_TTS_SID` | 否 | `0` | speaker id |
| `VEYRASOUL_TTS_SPEED` | 否 | `1.0` | 0.5–2.0 内使用 |
| `VEYRASOUL_TTS_THREADS` | 否 | `4` | TTS CPU 线程 |
| `VEYRASOUL_PERSONA_PATH` | 否 | `new_code/config/persona.md` | 稳定角色提示词 |
| `VEYRASOUL_MEMORY_PATH` | 否 | `new_code/data/memory/veyrasoul.db` | SQLite 文件；父目录需可写 |
| `VEYRASOUL_VLM_URL` | 否 | `http://127.0.0.1:8767` | 板内 VLM HTTP 服务 |
| `VEYRASOUL_VLM_TIMEOUT` | 否 | `20` | 单次 VLM HTTP 超时秒数 |
| `VEYRASOUL_VISION_REFRESH_SECONDS` | 否 | `5.0` | 语义推理最短启动间隔 |
| `VEYRASOUL_WEB_DIST` | 否 | `new_code/web/dist` | Gateway 同源静态前端目录；空值表示不挂载 |
| `VEYRASOUL_HOST` | 否 | `127.0.0.1` | Gateway 监听地址 |
| `VEYRASOUL_PORT` | 否 | `8875` | Gateway 端口 |
| `VEYRASOUL_LOG_LEVEL` | 否 | `info` | uvicorn 日志级别 |

## 5. 当前启动方式

```bash
cd ~/Visual_Companion_Robot/new_code/backend
source .venv/bin/activate

export DEEPSEEK_API_KEY='从安全的环境文件或密钥服务读取'
export VEYRASOUL_ASR_MODEL_DIR="$HOME/models/asr/zipformer-zh-en-int8"
export VEYRASOUL_TTS_MODEL_DIR="$HOME/models/tts/kokoro-zh-en"
export VEYRASOUL_MEMORY_PATH="$HOME/.local/share/veyrasoul/veyrasoul.db"
export VEYRASOUL_VLM_URL="http://127.0.0.1:8767"
export VEYRASOUL_VISION_REFRESH_SECONDS=5
export VEYRASOUL_HOST=127.0.0.1
export VEYRASOUL_PORT=8875

python -m veyrasoul.gateway
```

若只做同一局域网临时调试，可设 `VEYRASOUL_HOST=0.0.0.0`，但前端手机媒体权限仍需要 HTTPS，且不能把未鉴权端口直接暴露公网。

检查：

```bash
curl -fsS http://127.0.0.1:8875/v2/health
```

当前 CLI 强制配置 ASR，所以正常启动后的 `streaming_asr` 应为 `true`。health 只说明 ASGI 服务可响应、协议版本和 factory 已配置，不代表 ASR/TTS/VLM 已完成推理自检；当前 health 也不查询 VLM。

## 6. 前端构建与同源路由

```bash
cd ~/Visual_Companion_Robot/new_code/web
npm ci
npm run check
npm run build
```

生产静态文件位于 `web/dist/`。Gateway 会把 `VEYRASOUL_WEB_DIST` 以 `/` 挂载在 API/WS 路由之后，因此 Cloudflare Tunnel 可以直接回源 `127.0.0.1:8875`。若在 Gateway 前增加独立反向代理，它必须：

- 以 HTTPS 提供静态文件；
- 将 `/v2/realtime` 升级并转发为 WebSocket 到 `127.0.0.1:8875`；
- 将 `/v2/health` 转发到 Gateway；
- 保持同源，当前前端没有独立的 Gateway URL 配置；
- 设置合理的连接超时、上传大小、速率限制和鉴权。

当前项目使用 WebSocket 传 PCM/JPEG，不是 WebRTC。它便于控制和调试，但公网抖动、拥塞控制和回声体验仍需用真实网络验证。

## 7. systemd、一键启动与公网切换

仓库已提供：

- `deploy/systemd/veyrasoul-v2.service`：Gateway、ASR/TTS 预热、同源前端；
- `deploy/systemd/veyrasoul-v2-cloudflared.service`：把正式 Tunnel 回源切换到 `127.0.0.1:8875`；
- `deploy/veyrasoul.env.example`：不含真实密钥的环境模板；
- `scripts/start-elf2.sh`：安装单元、启动、健康检查、状态、停止和回滚。

首次准备环境文件：

```bash
sudo install -d -m 700 /etc/veyrasoul
sudo install -m 600 deploy/veyrasoul.env.example /etc/veyrasoul/veyrasoul.env
sudoedit /etc/veyrasoul/veyrasoul.env
chmod +x scripts/start-elf2.sh
```

此后在 `new_code/` 下的一键启动命令是：

```bash
./scripts/start-elf2.sh
```

脚本会在 V2 Gateway 健康后才启动正式 Tunnel，并停止使用同一 token 的 V1 Tunnel。需要回滚时执行：

```bash
./scripts/start-elf2.sh rollback
```

这些单元仍属于“已实现、待 ELF2 验证”，不能在实机和 `robot.veyralux.org` 验收前视为生产就绪。

## 8. 板端验收

部署不能只验证 `/health`。必须逐项取得证据：

1. ASR 模型加载、partial、endpoint final 和连续语音；
2. DeepSeek 首 token/首句，thinking 确认关闭；
3. Kokoro/VITS 中英混合、冷/热 TTS 时延和自然度；
4. 浏览器首音频播放且文字同步；
5. 新发言打断旧 generation，旧回复不写入记忆；
6. 摄像头本地预览实际 FPS，2 Hz JPEG 不拖慢预览；
7. 已接入的 5 秒语义调度在真实 VLM worker 上验证准确性、新鲜度和队列有界；
8. 8 小时 RSS、温度、CPU/NPU 频率和重连测试；
9. `robot.veyralux.org` 在 PC/移动端使用 HTTPS/WSS、媒体权限和鉴权通过。
