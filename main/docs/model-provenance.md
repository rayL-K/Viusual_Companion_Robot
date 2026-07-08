# 视觉模型来源与本地部署决策

## 已进入生产链路

| 能力 | 模型 | 运行位置 | 来源与许可 |
| --- | --- | --- | --- |
| 场景目标 | YOLOv5s INT8 RKNN | ELF2 NPU | [Rockchip RKNN Model Zoo v2.1.0](https://github.com/airockchip/rknn_model_zoo/tree/v2.1.0/examples/yolov5) |
| 人脸与五点 | YuNet 2023-03 | ELF2 CPU / OpenCV DNN | [OpenCV Zoo YuNet](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet)，MIT |
| 本地身份特征 | SFace 2021-12 | ELF2 CPU / OpenCV DNN | [OpenCV Zoo SFace](https://github.com/opencv/opencv_zoo/tree/main/models/face_recognition_sface)，Apache-2.0 |
| 表情 | emotion-ferplus-8 | ELF2 CPU / ONNX Runtime | Microsoft ONNX Model Zoo FER+ |
| 人体姿态 | YOLOv8n-pose INT8 RKNN | ELF2 NPU | [Rockchip RKNN Model Zoo v2.1.0](https://github.com/airockchip/rknn_model_zoo/tree/v2.1.0/examples/yolov8_pose) |
| 画面语义 | Qwen3-VL-2B W8A8 + FP16 Vision RKNN | ELF2 NPU / RKLLM | [Qengineering RK3588 移植](https://github.com/Qengineering/Qwen3-VL-2B-NPU)，固定提交 `3aa2c11b8a1f3db15a6d4145e4f93840a9a02cb4`，BSD-3-Clause |
| 主动说话人 | Light-ASD AVA ONNX | ELF2 CPU / ONNX Runtime | [论文](https://arxiv.org/abs/2303.04439)、[官方实现](https://github.com/Junhua-Liao/Light-ASD)，MIT |

SFace 只生成归一化特征。命名身份存放于 ELF2 的
`main/data/face_profiles.sqlite3`，登记图片不落盘，也不经过 Cloudflare 或第三方模型。

### 主动说话人：Light-ASD

- 原论文与实现：[A Light Weight Model for Active Speaker Detection](https://arxiv.org/abs/2303.04439)、[Junhua-Liao/Light-ASD](https://github.com/Junhua-Liao/Light-ASD)（MIT）。
- 论文规模为约 1.0M 参数、0.6G FLOPs；AVA-ActiveSpeaker 验证集 mAP 94.1%。
- 已把官方权重导出为约 4.1 MB ONNX，并在本项目 ELF2 实测：1 秒片段 141.5 ms、2 秒 283.4 ms、4 秒 572.3 ms，进程峰值约 314.8 MiB。
- Web 与小游戏已接入最后 2 秒 16 kHz PCM + 最多 16 帧的生产协议；服务端做人脸短时跟踪，
  单候选门限为 0.55，多候选门限为 0.60 且领先第二名至少 0.08，否则返回 `unknown`。
- TalkNet 官方示例多人视频实测：32 帧完整窗口置信度 0.8935；生产 2 秒/16 帧窗口在公网
  置信度 0.8203，146 KiB 请求往返约 4.1 秒。单张 JPEG 仍不能据此声称“谁在说话”。

### 人体动作：YOLOv8n-pose（已进入生产链路）

采用 [Rockchip 官方 RKNN YOLOv8 Pose 示例](https://github.com/airockchip/rknn_model_zoo/tree/v2.1.0/examples/yolov8_pose)，其明确支持 RK3588。当前 ELF2 实测约 49–57 ms，输出 17 个 COCO 关键点，并用保守规则识别举手、倾斜、站立和坐姿。

### 画面语义：Qwen3-VL-2B

- 视觉编码器和 2B 解码器都在 ELF2 本地运行；不向 DeepSeek 或其他视觉 API 上传图片。
- 独立 systemd 服务常驻模型，避免每帧重新加载；`BoardVisionService` 在后台提交关键帧，YOLO/人脸/姿态的实时响应不等待 VLM。明显换景可在约 1 秒后发起新语义分析，静态画面继续限频。
- VLM 输出只作为 `semantic_caption` 补充环境、人物外观和整体状态；人数、身份、情绪和动作仍以专用模型结果为准，避免让生成式描述覆盖结构化事实。
- 12 张 COCO 2017 人物/动作/室内外基准中，旧 1B 模型把暗光猫误判为金毛犬并臆测自行车场景背景；Qwen3-VL-2B 修正这两类错误。32 token 单帧实测约 4.4–5.4 秒，替换旧模型后仍可与 SenseVoice、Matcha、FER+ 和实时检测在 8 GiB 内存中共存。
- 当前权重 SHA-256：LLM `fff51586d0afbc2516b5ab1a5cda2cefaf7fcbea4ee4a1d59cc37e9a08d26c5f`；Vision `99ed529107133af2570b521f45da510b6e539054e9952218be55d53c3f9c3bfc`。

## 未采用的捷径

- 不用画面中最大脸直接标记“主动说话人”；它只可作为 `focus_face`。
- 不用浏览器 MediaPipe、云视觉或 CPU YOLO 作为板端失败降级。
- 不自动给陌生人创建永久姓名；只有显式登记后的 SFace 特征才可返回姓名。
