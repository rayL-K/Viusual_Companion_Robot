# Anima 推理节点选型（2026-07）

> 价格和库存会变化。本页记录的是 2026-07-27 可由厂商官方页面核实的规格或报价；采购前必须重新询价。任何消费级单卡都不能替代生产高可用设计。

## 结论

Anima 的首个服务器验证节点应优先租用 **RTX 4090 24GB**，完成真实模型、并发和延迟压测后再采购。完整常驻的 7B/8B Q4 LLM、Qwen3-TTS、Whisper、轻量 VLM、CUDA 上下文和 KV cache 对 16GB 很紧张；16GB 只能作为单用户开发下限，通常需要模型卸载或串行热切换，容易重新引入首包等待。

建议分层：

- 控制面、账号、数据库、对象存储：普通云服务器或托管数据库，不占 GPU。
- GPU Worker：无状态任务执行，至少 24GB VRAM；会话、记忆和用户数据不以本地磁盘为唯一副本。
- ELF2：开发期继续作为边缘感知和兼容性节点；回收后不成为系统单点。
- 云端 API：作为容量溢出和节点故障时的显式降级，必须受用户数据出境/隐私同意控制。

## 先租后买

AutoDL 官方页面在调研时展示：

| GPU | 显存 | 按量价格 | 连续 30 天粗算 |
|---|---:|---:|---:|
| RTX 3090 | 24GB | ¥1.32/小时 | ¥950.4 |
| RTX 4090 | 24GB | ¥1.88/小时 | ¥1,353.6 |
| RTX 5090 | 32GB | ¥2.78/小时 | ¥2,001.6 |

连续月成本仅按 `价格 × 24 × 30` 计算，未包含数据盘、流量、快照和税费。按量实例关机后通常不保留 GPU，因此不应直接作为唯一的 ToC 在线节点。

验证顺序：

1. 租 4090 24GB 运行一至两周。
2. 记录并发 1/2/4 下的 VRAM 峰值、ASR 完成时间、LLM 首 token、TTS 首音频和端到端 P50/P95。
3. 用真实中文、中英混说、摄像头视觉、长对话记忆和 Live2D 同时运行的负载测试，而不是分别跑模型 benchmark。
4. 若单会话峰值稳定低于 20GB，再评估采购 3090 24GB 工作站；否则选择 32GB 以上节点或拆分模型。

## 自建建议

### 开发下限：RTX 5060 Ti 16GB

- NVIDIA 官方起售价：¥3,199。
- 16GB GDDR7，TGP 180W，官方建议 600W 电源。
- 建议整机：6 核以上 CPU、64GB RAM、2TB NVMe、650W 金牌电源。
- 适合单人开发、串行推理和 adapter 合约验证，不作为多用户生产承诺。

### 生产原型性价比：RTX 3090 24GB

- 24GB VRAM，TGP 350W；建议 850–1000W 高质量电源。
- 新卡正规低价渠道有限，实际通常是二手采购；必须有验机和保修，运行显存压力、CUDA 稳定性和长时满载测试，拒绝来源不明的魔改显存卡。
- 可将功耗限制在约 280–320W，换取更可控的温度和能耗。

### 不推荐的中间档：RTX 5070 Ti 16GB

- NVIDIA 官方起售价：¥6,299，16GB GDDR7，TGP 300W。
- 算力更强但显存仍是 16GB；对于同时常驻多模态模型，通常不如将预算投入 24GB 节点。

### 高预算：RTX 5090 D 32GB

- NVIDIA 官方建议零售价：¥16,499。
- 32GB 对多模型常驻更友好，但 GPU TGP 高达 575W，整机、散热、电费和供电成本不符合首个低成本节点定位。

## 采购门槛

上线前至少满足：

- 64GB RAM；启用 CPU offload 时建议 128GB。
- 2TB NVMe，模型与用户数据分卷；数据库和对象数据有异机备份。
- 有线网络、UPS、温度监测和掉电恢复。
- GPU worker 无状态化；任何单台 GeForce 故障不会造成账号或记忆数据永久丢失。
- 至少存在第二 GPU 节点或云端 Provider 熔断路径。
- 以压测数据确定并发上限，过载时排队或拒绝，而不是让所有会话同时超时。

## 官方来源

- [NVIDIA RTX 5060 系列规格与建议电源](https://www.nvidia.cn/geforce/graphics-cards/50-series/rtx-5060-family/)
- [NVIDIA RTX 5070 系列规格](https://www.nvidia.cn/geforce/graphics-cards/50-series/rtx-5070-family/)
- [NVIDIA RTX 3090 规格](https://www.nvidia.cn/geforce/graphics-cards/30-series/rtx-3090-3090ti/)
- [NVIDIA RTX 50 系列发布与建议零售价](https://www.nvidia.cn/geforce/news/rtx-50-series-graphics-cards-gpu-laptop-announcements/)
- [AutoDL 当前 GPU 价格](https://www.autodl.com/)
- [AutoDL 计费说明](https://api.autodl.com/docs/price/)
- [腾讯云 HAI](https://cloud.tencent.com/product/hai)
- [阿里云 GPU 实例创建与计费模式](https://help.aliyun.com/zh/egs/user-guide/create-a-gpu-instance/)
