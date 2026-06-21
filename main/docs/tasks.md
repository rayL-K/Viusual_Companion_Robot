# 任务计划

## 当前阶段

Windows 10 开发闭环已完成系统修复和自动化回归；下一阶段以真实人物交互和
ELF2/RK3588 实机验收为主，不再新增没有运行接线的“可选后端”界面。

## 下一步任务

1. 将 sherpa-onnx ASR 与 WebRTC VAD 接入麦克风输入闭环，替代对浏览器 Web Speech 的依赖。
2. 用真人连续测试 FER+、头部跟踪、语音打断和动作映射，记录阈值与误触发率。
3. 在 ELF2 上安装 Python 3.11、RKNNLite/rknpu2，并验证 YOLO RKNN 模型与 CPU ONNX 降级。
4. 分别验收本地 GGUF LLM、sherpa VITS 和 VoxCPM2 的延迟、内存、温度与断网行为。
5. 为控制服务增加长期运行和并发请求测试，覆盖服务退出、模型缺失与请求取消。
6. 轮换曾进入 Git 历史的 SiliconFlow 密钥；需要公开仓库时再单独执行历史清理。

## 已完成

- 统一 `LlmContext` 调用协议，并修复控制服务真实 HTTP 路由。
- Live2D 舞台支持动作、表情、口型、待机、人物拖放缩放和结构化控制计划。
- 浏览器摄像头、MediaPipe 人脸检测、FER+ 服务与 blendshape 降级链路已接通。
- 麦克风设备检测和实时电平已验证；Web Speech 不可用时会显示明确状态。
- VoxCPM 公网、项目内推理和 Gradio 兼容模式具有独立的真实运行路径。
- sherpa-onnx Aishell3 已完成真实中文 WAV 合成验证。
- WebRTC VAD 状态机、FER+ 输出归一化和 YOLO RKNN 导出已有自动化测试。
- Windows `.bat` 入口兼容 PowerShell 7 与 Windows PowerShell 5.1。
- Python 3.11、Conda、项目依赖和 Windows/板端文档已统一。
