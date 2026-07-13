# Visual Companion Robot 维护手册

更新日期：2026-07-07

## 当前生产入口

- 公网 Web：`https://robot.veyralux.org`
- 微信小游戏 AppID：`wx8b9c56c00cb5c9ec`
- 当前小游戏开发版：`0.3.1`（已上传，尚未提交审核/发布）
- ELF2：`elf2-desktop.local`，项目目录 `/home/wenkang/embedded_competition`；当前手机热点地址由 DHCP 分配
- 板端服务：emotion、VLM、control、cloudflared 四项 systemd 服务

## 先读什么

1. `architecture_design.md`：不可破坏的运算边界和部署门禁。
2. `README.md`：项目入口与模块索引。
3. `main/docs/board-deployment.md`：板端依赖、模型和验收方式。

## 实际视觉链路

```text
Web getUserMedia / 小游戏 wx.createCamera + PCM 采集
  -> 低频 JPEG，或最后 2 秒 PCM + 最后 16 帧
  -> robot.veyralux.org/vision 或 /active-speaker
  -> Cloudflare Worker 注入设备令牌
  -> ELF2 BoardVisionService
  -> YOLOv5s + YOLOv8n-pose RKNN
  -> Qwen3-VL-2B W8A8 + FP16 RKNN（6 秒低频异步语义）
  -> YuNet + SFace + FER+ + Light-ASD
  -> 场景/物体/人数/姿态/身份/情绪/主动说话人
  -> /chat vision 上下文 + Live2D 表现
```

浏览器 MediaPipe、`emotion-onnx-client.js`、云端视觉和 YOLO ONNX CPU 降级均已删除。
不要恢复这些旧路径。

## 常用验证

```powershell
# Python
$env:PYTHONUTF8='1'
python -m unittest discover -s main/tests -p 'test_*.py'

# Web
Push-Location main/live2d_stage
npm test
npm run check
npm run build
Pop-Location

# 微信小游戏
Push-Location main/miniprogram
npm test
npm run check
Pop-Location

# Cloudflare
Push-Location tools/cloudflare/gateway
npm run check
Pop-Location
```

## 板端验收

```bash
systemctl is-active visual-companion-emotion visual-companion-vlm visual-companion-control visual-companion-cloudflared
curl -fsS http://127.0.0.1:8767/health
curl -fsS http://127.0.0.1:8765/vision-health
curl -fsS http://127.0.0.1:8765/emotion-health
journalctl -u visual-companion-control -n 100 --no-pager
```

上电后的统一启动/自检命令：

```powershell
ssh -t wenkang@elf2-desktop.local "~/start-robot"
```

当前板端通过 NetworkManager 配置首选/备用 Wi-Fi。手机热点建议使用 2.4 GHz；切到
5 GHz 信道 149 时，板端默认区域码可能无法扫描到热点。不要在脚本中写死 DHCP 地址，也不要在仓库中提交真实 Wi-Fi 名称或密码。

`vision-health` 必须明确返回 `elf2-local-yolo-pose-yunet-sface-ferplus`、`rknn-yolov5s`、
`yunet-sface-ferplus-local`、`ferplus-onnx` 和 `semantic_ready: true`。不能把“接口能返回 200”当作模型已推理，部署时还要用真人脸、多人、背景与无脸 JPEG 连续调用
`/vision`。

## 密钥与模型

- 密钥只在被 Git 忽略的 `main/config/board.env`、`main/config/local.env` 或 Cloudflare
  Secret 中保存。
- `main/models/` 不进 Git。
- YOLO 模型固定为 `main/models/yolo/yolov5s-640-640.rknn`。
- RKNNLite 固定使用与板端 runtime 匹配的 2.1.0 ARM64 wheel。
- Qwen3-VL 使用 `/opt/visual-companion-vlm` 内隔离的 RKLLM/RKNN 运行库，不覆盖系统
  `librknnrt.so 2.1.0`；模型 SHA-256 由 `tools/board/install_vlm.sh` 固定校验。
- Qengineering 的 2B 权重需先通过其仓库提供的 Sync 页面下载到 `main/models/vlm/`；安装脚本只接受文档中固定 SHA-256 的两个文件，不接受下载页 HTML 或不完整文件。
- DeepSeek Flash 是唯一有意使用的云模型。

## 发布顺序

1. 本地全量测试。
2. 同步 ELF2 代码与模型并重启 systemd。
3. 板内健康检查和真实帧推理。
4. 构建 Web 并部署 Cloudflare Worker/Assets。
5. 公网视觉、聊天、TTS 和响应式浏览器回归。
6. 微信开发者工具编译、预览、上传。
7. 微信后台合法域名、隐私说明、备案和审核。

## 已知需要真人最终确认的项目

- 微信真机首次摄像头/麦克风授权文案与系统弹窗。
- FER+ 在实际人物、侧脸和光线变化下的阈值。
- 扬声器回声环境中的语音打断灵敏度。
- Light-ASD 在实际距离、多人交谈、侧脸和遮挡条件下的门限。

自动化测试必须先覆盖其余确定性路径，不能用“等待真人测试”替代可自动验证的工作。
