# 任务计划

## 当前阶段

先把项目结构、模块边界、Live2D 模型资源、本地测试脚本和真实展示闭环整理稳定。

## 下一步任务

1. 完成运行时消息定义，用统一事件连接感知、对话、语音和 Live2D 模块。
2. 增加真实音频口型链路：从 WAV 或 TTS 输出生成音量包络，驱动嘴巴开合。
3. 完善 VoxCPM2 自托管 TTS 适配层，保留 `voxcpm_hf_space_test` 公网 API 测试后端和 `voxcpm_local` 本地推理后端，参考音频只作为可试听、可编辑文本的音色输入。
4. 完善 LLM 到 Live2D 的结构化控制协议：补 JSON Schema 文件、延时动作计划、表情白名单、参数范围裁剪和平滑过渡测试。
5. 完成真实 Live2D 渲染窗口，继续打磨模型缩放、舞台构图、表情切换、动作播放和口型值接收。
6. 按顺序替换模拟模块：摄像头、ASR、TTS、本地对话模型和视觉模型。
7. 在 Firefly 上跑通同步、启动和基础显示调试流程。

## 已完成

- 配置加载器已能读取并校验 `config/app.yaml`。
- Live2D 资源加载层已能把 `manifest.json` 转换成可被程序使用的角色对象。
- 嘴型同步已有可视化测试报告，固定文本覆盖普通话主要声母/韵母和英语常见元辅音。
- 嘴型参数已迁移到 `config/mouth_shapes.json`，每个音可以独立调整嘴型和临时合成声音参数。
- 嘴型可视化报告支持恢复初始值、保存浏览器本地调整值和下载调整后的完整配置。
- 已完成 VoxCPM、LLM_Live2D、astrbot_plugin_vtuber 三个外部项目的可借鉴性评估，结论见 `external_reference_assessment.md`。
- 已新增真实 Live2D 展示台 `live2d_stage/`，可加载 Strawberry_Rabbit 模型、请求本地 LLM 控制服务并接入 VoxCPM 音频接口。
- 已将 TTS 路线收敛为 VoxCPM2，保留公网 API 与本地推理两种模式。
- 已复制少量 VoxCPM2 保存音色样本和对应转写文本到 `assets/tts/voxcpm_samples/`，并改为在语音面板中作为参考音频选择，不再作为占位语音模型。
- 已新增 `voxcpm_hf_space_test` 后端，用于临时调用 OpenBMB Hugging Face Space 测试真实 TTS 链路。
- Live2D 展示台已支持从 `/voices` 读取语音模型列表和参考音频列表，并在“更换语音模型”面板中切换 VoxCPM 公网 API / 本地推理后端、试听参考音频、编辑参考文本。
- 已新增 SQLite 记忆模块骨架，对话轮次默认保存到 `main/data/memory.sqlite3`。
- 已新增 DeepSeek 临时 API 控制生成脚本，API key 只从环境变量读取，不写入仓库。
- 已根据模型原始使用说明定位水印热键，Web 展示台通过 `Param261 = 1` 模拟“消除水印”状态。
