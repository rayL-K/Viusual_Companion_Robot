# ELF2 应用目录

这里包含 Visual Companion Robot 的板端业务代码、响应式 Web、模型配置和自动化测试。项目总览、部署命令、接口与当前实测数据以仓库根目录 [`README.md`](../README.md) 为唯一入口。

## 生产边界

- ELF2 本地：YOLO/Pose、Qwen3-VL、YuNet/SFace、FER+、Light-ASD、SenseVoice、Matcha/Vocos、VoxCPM.cpp 与 SQLite 记忆。
- 云端：DeepSeek Flash 只接收净化后的结构化上下文，不接收原始图像、音频或身份特征。
- 客户端：`live2d_stage/` 负责摄像头/麦克风采集、Live2D 渲染和音频播放；生产 API 使用 `https://anima.veyralux.org` 同源路径。
- `miniprogram/` 保留现有开发版，当前冻结，不作为 Web 主线的发布门禁。

## 常用入口

```text
scripts/live2d_control_server.py             统一控制网关
src/visual_companion_robot/perception/       板端感知
src/visual_companion_robot/voice/            Matcha 与 VoxCPM 适配
src/visual_companion_robot/brain/memory.py   SQLite 短期/长期记忆
live2d_stage/                                PC/移动端 Web
config/tts_models.json                       生产音色与参考音色
docs/board-deployment.md                     板端部署细节
docs/voxcpm_tts_route.md                     ELF2 VoxCPM 实测路线
```

Windows 10 可直接使用 `tools\launchers\test_live2d.bat` 回归，不要求安装 PowerShell 7。ELF2 上电后一键启动命令为：

```bash
~/start-robot
```
