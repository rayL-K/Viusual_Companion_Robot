# 任务计划

## 当前阶段

Windows 10 开发闭环已完成系统修复和自动化回归；下一阶段以真实人物交互和
ELF2/RK3588 实机验收为主，不再新增没有运行接线的“可选后端”界面。

## 下一步任务

1. 用真人连续测试 FER+、SenseVoice、头部跟踪、语音打断和动作映射，记录阈值与误触发率。
2. 在 ELF2 上安装 Python 3.11、RKNNLite/rknpu2，并验证 YOLO RKNN 模型与 CPU ONNX 降级。
3. 分别验收本地 GGUF LLM、sherpa VITS 和 VoxCPM2 的延迟、内存、温度与断网行为。
4. 实现用户开口后可抢占当前 TTS 的语音打断策略。
5. 在供应商后台轮换曾进入 Git 历史的 SiliconFlow 密钥；Git 历史清理不能替代密钥吊销。

## 已完成

- 统一 `LlmContext` 调用协议，并修复控制服务真实 HTTP 路由。
- Live2D 舞台支持动作、表情、口型、待机、人物拖放缩放和结构化控制计划。
- 浏览器摄像头、MediaPipe 人脸检测、FER+ 服务与 blendshape 降级链路已接通。
- 麦克风 AudioWorklet、实时电平、WebRTC VAD、SenseVoice INT8 与 `/asr` 已形成完全离线闭环。
- 浏览器真实麦克风/摄像头、本地 VITS 播放、播放防回声暂停与设备释放已在 Win10 自动化验证。
- VoxCPM 公网、项目内推理和 Gradio 兼容模式具有独立的真实运行路径。
- sherpa-onnx Aishell3 已成为网页默认 TTS，并提供不依赖 LLM 的独立试听入口。
- 控制服务已增加并发路由测试和可复用的 Windows 长时间稳定性脚本。
- Windows 30 分钟稳定性回归已完成：1830 次请求、30 次真实 TTS、0 失败，未观察到持续内存增长。
- 控制服务与 FER+ 情绪服务已限制为本机浏览器 Origin，并提供可探测的健康状态。
- WebRTC VAD 状态机、FER+ 输出归一化和 YOLO RKNN 导出已有自动化测试。
- Windows `.bat` 入口兼容 PowerShell 7 与 Windows PowerShell 5.1。
- Python 3.11、Conda、项目依赖和 Windows/板端文档已统一。
- 当前开发分支及对应远端分支的历史密钥提交已重写清除。
