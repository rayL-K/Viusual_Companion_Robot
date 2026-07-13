# VeyraSoul V2 服务器采购与容量规划（2026-07-13）

> **结论先行：现在不建议直接购买双 GPU 服务器。** V2 尚未完成真实 ELF2、真实 SoulX 和真实公网并发基准；当前最划算的顺序是：继续使用 RK3588 承担默认板端模态，DeepSeek V4 Flash 作为云 LLM，先按小时租用一台显存不低于 24 GB 的 NVIDIA GPU 做 7～14 天验收。只有 SoulX 的自然度收益和热启动时延都通过门槛后，才购买单 GPU 工作站；只有持续并发、24×7 稳定性或显存隔离确实成为瓶颈后，才进入双 GPU 机架服务器。

本文不是报价单。所有价格、促销、库存和可购地域都以 **2026-07-13 访问厂商官网时**的页面为准；带“估算”的数字是容量规划假设，不是厂商承诺或本项目实测。

---

## 1. 证据标签与当前边界

| 标签 | 含义 |
| --- | --- |
| **实测** | 本仓库自动化或本机基准产生的结果；不外推为 RK3588、SoulX 或公网性能 |
| **模型资产事实** | 上游固定版本的代码、模型卡、文件清单或芯片厂商规格 |
| **厂商事实** | 整机、云服务或部件厂商官网在访问日展示的规格/活动 |
| **估算** | 基于功耗、显存、会话流量和工作进程预算的采购规划，必须用目标机器复测 |

### 1.1 当前已有“实测”证据

- **实测（开发电脑、确定性模型桩）**：`artifacts/e2e-local.json` 在 320×568、390×844、768×1024、1024×768、844×390 和 1440×900 六种视口完成真实 Chromium 纵切片；可见回复约 0.85～0.90 秒。它证明 WebSocket、播放时显字、Live2D 和 UI 生命周期，不代表真实 ASR/LLM/TTS 时延。
- **实测（开发电脑）**：`artifacts/memory-benchmark.json` 的 2,000 条数据、100 次检索 p95 为 6.968 ms。它只证明当前 SQLite/FTS/RAG 量级。
- **未实测**：ELF2 上的完整 V2、SoulX 热/冷启动、真实 VLM、公网 p50/p95、GPU 并发、30 天常驻、温度与功耗。因此下文不能把任何并发数写成“已经达到”。

### 1.2 采购不能修复的软件瓶颈

**模型资产事实**：固定的 SoulX-Podcast 版本仍把“streaming inference”列为 TODO，Flow 路径以 `streaming=False` 执行，HTTP API 在完整推理和写 WAV 后才返回文件。即使换成更强 GPU，它也不会自动变成首音频流式 TTS。证据见：

- [SoulX-Podcast 固定 commit](https://github.com/Soul-AILab/SoulX-Podcast/tree/5ac9c0e1cfe596396200c7d38e3fd53b7b3fbf4b)
- [README 的 streaming TODO](https://github.com/Soul-AILab/SoulX-Podcast/blob/5ac9c0e1cfe596396200c7d38e3fd53b7b3fbf4b/readme.md#L183-L190)
- [当前 API 完成后返回文件](https://github.com/Soul-AILab/SoulX-Podcast/blob/5ac9c0e1cfe596396200c7d38e3fd53b7b3fbf4b/api/service.py#L209-L235)

因此 SoulX 只能先作为用户显式选择的“高质量 GPU 音色 sidecar”，不能替换默认低时延 TTS。服务器采购验收必须同时看**首音频延迟、取消释放、自然度和峰值显存**，不能只看 GPU 型号。

---

## 2. 负载拆分：RK3588 仍然做什么

无论购买哪一档，ELF2/RK3588 都不应退化成摆设。建议保留两种运行模式：

### 2.1 比赛/单设备演示模式

RK3588 仍是完整可运行边缘节点，负责：

1. Realtime Gateway 与 generation/cancel 会话状态；
2. 浏览器 PCM/JPEG 接收、latest-value 感知时间线；
3. sherpa-onnx streaming ASR；
4. RKNN 人/物/姿态/人脸等视觉快路径，以及能在板端稳定运行的语义视觉；
5. 默认低时延本地 TTS；
6. 单用户/单 Anima 的记忆、RAG、离线降级与本机健康检查；
7. 断网时维持本地可用，而不是依赖新服务器才能说话。

### 2.2 公网多用户模式

新增 CPU/GPU 主机负责认证、公网入口、用户数据库/备份、可观测性以及可选高质量模型；RK3588 作为注册的 `EdgeNode` 负责实体设备对应的本地媒体和板端推理。通过现有 Port/API 切换，不让所有公网用户强制串行经过一块板的单实例 VLM 锁。

这样既保留“基于 RK3588 的端侧多模态系统”，又避免未来多用户架构被单板吞吐量锁死。V1 在评审期继续独立运行；任何新服务器都不得替换当前 V1。

---

## 3. 三档采购建议

| 档位 | 一次性/首年成本 | GPU/显存 | 初始活跃全模态会话规划 | 当前建议 |
| --- | ---: | --- | ---: | --- |
| A：CPU 控制面 | 云活动机 99 元/首年；本地节点约 1～1.8 万元 | 无 | 整链路先按 1（RK3588 是瓶颈） | **现在采用** |
| B：单 GPU sidecar | 约 5.5～7 万元；专业 ECC 约 10～18 万元 | 5090D V2 24 GB；或 32/48 GB 专业卡 | 1～2 | SoulX 租云验收通过后再买 |
| C：双 GPU 服务器 | 双 L40S 约 18～32 万元询价；双 96 GB 约 35～65 万元询价 | 2×48 GB 或 2×96 GB，显存不自动合并 | 4 起验、逐级压到 8 | 当前不买 |

“会话规划”是保守压测起点，不是最大连接数或已实现吞吐。实际扩容只看目标 SLO 的 p95、错误率和 8 小时稳定性。

### 3.1 A 档：云 LLM + RK3588 模态，性价比 CPU 节点

**适合**：目前的 1～3 名开发/演示用户；视觉、ASR、默认 TTS 仍在 ELF2；LLM 调 DeepSeek；CPU 节点只做入口、认证、数据库、备份、监控和协议转发。

#### 推荐配置

| 部件 | 最低开发配置 | 建议长期配置 | 说明 |
| --- | ---: | ---: | --- |
| CPU | 4 vCPU | 12～16 核 / 24～32 线程 | 不在 CPU 上跑大 VLM/TTS；优先单核性能和稳定性 |
| RAM | 8 GB | 64 GB；正式数据优先 ECC | 8 GB 只适合入口；64 GB 给缓存、备份、监控留余量 |
| 系统盘 | 80 GB SSD | 2×1 TB NVMe 镜像 | OS、容器、日志 |
| 数据盘 | 100 GB | 2×2 TB NVMe 镜像 | 用户/Anima 数据、审计与快照 |
| 网络 | 3 Mbps 仅开发 | 100 Mbps 对称起步 | 60 FPS 预览在浏览器本地，不上行 60 FPS；但 PCM、2 Hz JPEG 和 TTS 仍需带宽 |
| GPU | 无 | 无 | SoulX/VLM 不进入此节点 |

**估算**：当前 16 kHz mono PCM16 本身约 256 kbit/s；再加 2 Hz、384 px JPEG、TTS 音频和协议开销，按每个活跃通话 **0.8～1.8 Mbps 双向总预算**规划。腾讯 3 Mbps 活动机只适合 1 个活跃演示会话，不是多用户生产规格。

#### 采购形式与成本

1. **首选过渡方案：腾讯云轻量应用服务器。** 官方活动页在访问日显示 4 核 4 GB、3 Mbps，新用户首年 99 元，并注明活动至 2026-12-30；资格、限购、续费价和库存以结算页为准。它适合反向代理、状态页和开发验证，不适合承载多个实时媒体会话。来源：[腾讯云轻量特惠](https://cloud.tencent.com/act/pro/lhsale)、[2026 年中活动](https://cloud.tencent.com/act/pro/warmup-202606)。
2. **本地自建 CPU 节点（估算 10,000～18,000 元）**：Ryzen 9 9950X 16C/32T、64 GB、2×2 TB NVMe、2.5/10GbE、UPS。AMD 官方规格为 16C/32T、最高 5.7 GHz、170 W；来源：[AMD Ryzen 桌面处理器规格](https://www.amd.com/en/products/processors/desktops/ryzen.html)。这不是 ECC 服务器替代品，但对早期团队的性价比最高。
3. **需要 ECC/BMC/上门服务时再询价塔式服务器**：Dell PowerEdge T160、H3C/HPE 或联想 ThinkSystem。官网定制页的预选服务会显著扭曲价格，必须让销售输出“裸硬件 BOM + 三年保修 + 到手含税价”，不要按页面默认高价直接下单。来源：[Dell PowerEdge T160 中国定制页](https://www.dell.com/zh-cn/shop/dell-poweredge%E6%9C%8D%E5%8A%A1%E5%99%A8/poweredge-t160-%E5%A1%94%E5%BC%8F%E6%9C%8D%E5%8A%A1%E5%99%A8-%E9%AB%98%E7%BA%A7%E5%AE%9A%E5%88%B6%E6%9C%8D%E5%8A%A1/spd/poweredge-t160/aspet160)、[H3C 服务器产品](https://www.h3c.com/cn/Products_And_Solution/Server/)。

#### 容量与功耗（估算）

- CPU 节点本身：约 50～100 个长连接、8～20 个轻量文本/控制活跃会话的规划起点；**整个多模态链路仍受单块 RK3588 限制，先按 1 个活跃全模态会话验收**。
- 典型整机平均 80～180 W、压力峰值 250 W；24×7 月电量约 58～130 kWh。
- 若用 0.6～1.0 元/kWh 作为本地预算假设，月电费约 35～130 元，不含制冷、UPS 损耗和公网费用。

**A 档是当前推荐。** DeepSeek 官方当前 V4 Flash 非思考模式价格为缓存命中输入 0.02 元/百万 tokens、未命中输入 1 元/百万 tokens、输出 2 元/百万 tokens。按每轮 2,000 输入 + 150 输出、全部未命中做保守估算，10,000 轮约 23 元；目前没有经济理由为了普通对话先购买本地大 LLM 服务器。来源：[DeepSeek 模型与价格](https://api-docs.deepseek.com/zh-cn/quick_start/pricing)。

> **兼容性期限**：同一官方页声明 `deepseek-chat` / `deepseek-reasoner` 将于北京时间 **2026-07-24 23:59** 弃用；采购与压测应直接使用 `deepseek-v4-flash` / `deepseek-v4-pro`，不要继续围绕旧模型名建设。

---

### 3.2 B 档：单 NVIDIA GPU，高质量 TTS/VLM sidecar

**适合**：SoulX 主观效果明确优于默认 TTS，并且团队愿意接受它“完整 WAV 后返回”的时延；还需要一个 7B 级量化 VLM 做高质量语义，但不打算自托管大 LLM。

#### 推荐配置

| 部件 | 性价比方案 | 商务稳定方案 |
| --- | --- | --- |
| GPU | RTX 5090D V2 24 GB；若同卡并存不达标，直接升到专业卡 | RTX 5000 Ada 32 GB / RTX 6000 Ada 48 GB / RTX PRO 6000 Blackwell 96 GB |
| CPU | 16～24 高性能核心 | Xeon W / Threadripper PRO 16～32 核 |
| RAM | 128 GB | 128～256 GB ECC |
| 存储 | 2 TB 系统 + 4 TB 模型/缓存 | 2×1.92 TB 系统镜像 + 2×3.84 TB 数据镜像 |
| 网络 | 2.5/10GbE，公网 100 Mbps 起 | 10/25GbE，独立管理口 |
| 电源 | 1,200 W 品牌整机 | 冗余/工作站认证电源，按 GPU BOM 配置 |

**模型资产事实**：SoulX Base 的三个 Qwen3 BF16 分片合计约 4.125 GB，`flow.pt` 约 451 MB，`hift.pt` 约 83 MB；Hugging Face 仓库包含 tokenizer/ONNX/cache 等文件后约 9.89 GB。模型卡与文件清单见 [SoulX-Podcast-1.7B](https://huggingface.co/Soul-AILab/SoulX-Podcast-1.7B)。模型资产能放进显存不等于运行时够用，PyTorch、KV cache、激活、Flow、vocoder 和并发 worker 都要额外占用。

**估算显存预算**：

- SoulX 单 worker 热运行先预留 **12～16 GB**；
- 7B VLM 4-bit worker 预留 **6～10 GB**；
- CUDA context、碎片和取消重建安全余量至少保留 **15%～20%**；
- 24 GB 卡只建议“1 个 SoulX worker”与“小 VLM 分时复用”，不要在未测前承诺二者满并发；32/48 GB 卡才适合稳定并存。

#### 当前可买整机参考

- **固定价性价比参考**：联想官方商城在访问日展示拯救者刃 9000K、Ultra 9 285K、64 GB、2 TB、RTX 5090D V2 24 GB，标价 49,999 元，并展示 12 期免息/以旧换新。来源：[联想商城当前搜索页](https://s.lenovo.com.cn/search/?cat=310-311&innerKey=&key=%E6%8B%AF%E6%95%91%E8%80%85+%E5%88%839000&recommendType=0)。这是消费级 Windows 整机，页面没有声明 ECC，适合研发 sidecar，不应当作无人值守机房服务器。
- **专业工作站参考**：Dell Precision 7960 官方支持 Ubuntu、128/256 GB ECC 和多块 RTX 5000 Ada 32 GB；中国官网配置价格随显卡/服务变化，必须询价。来源：[Dell Precision 7960 中国](https://www.dell.com/zh-cn/shop/precision-7960-%E5%A1%94%E5%BC%8F/precision-7960-%E5%A1%94%E5%BC%8F/spd/precision-t7960-workstation)、[支持 GPU 清单](https://www.dell.com/support/manuals/zh-cn/precision-t7960-workstation/precision-t7960-setup-and-specifications/gpu-%E7%8B%AC%E7%AB%8B?guid=guid-a879aefc-b317-4dfa-b836-665dccbe4c32)。
- **可扩展专业参考**：Lenovo ThinkStation P8 官方规格支持 Threadripper PRO、最多三块 RTX PRO、1400 W 电源和 10GbE；中国区价格需要企业销售询价。来源：[ThinkStation P8 官方规格](https://www.lenovo.com/us/en/p/workstations/thinkstation-p-series/thinkstation-p8-workstation/len102s0017)。
- **另一家询价对照**：HP Z8 Fury G5 官方宣称单 CPU 最多 60 核、最多四块高端 GPU、8 个 PCIe 插槽和 4 个前置 NVMe 位；中国页要求联系销售。来源：[HP Z8 Fury 中国](https://www.hp.com/cn-zh/workstations/z8-fury-specs.html)。

NVIDIA 中国官方页显示，RTX 5090D V2 的标准显存为 24 GB GDDR7、显卡总功耗 575 W、建议系统功率 1000 W、不支持 NVLink，官方起售价为 16,499 元。具体非公版显卡和整机仍以 BOM 为准；若 24 GB 在实测中不足，应直接比较 32/48/96 GB 专业卡，不把旧款或境外 32 GB RTX 5090 当作中国大陆稳定货源。来源：[NVIDIA 中国 RTX 5090D V2](https://www.nvidia.cn/geforce/graphics-cards/50-series/rtx-5090-d-v2/)。

#### 容量、功耗与成本（估算）

- **初始进程槽**：1 个 SoulX worker；1 个 7B 4-bit VLM worker按需加载或分时；2～4 个连接可以排队，但首轮只承诺 **1～2 个活跃高质量模态会话**，以 p95 而不是显存可装数量决定扩容。
- 消费级整机到手约 50,000 元；若厂商兼容清单允许再补足 128 GB，并加入备份盘、UPS 和 Linux 验收，总预算约 **55,000～70,000 元**；若不允许扩内存则改选专业工作站。专业 ECC/48 GB 工作站先按 **100,000～180,000 元询价预算**，不把官网基础配置当最终报价。
- 平均 350～650 W、压力峰值约 900 W；24×7 月电量约 252～468 kWh。按 0.6～1.0 元/kWh 的预算假设，月电费约 151～468 元，不含空调。
- 消费级卡没有 ECC/企业 SLA；必须配置自动重启、显存泄漏探针、温度/功耗告警和备用默认 TTS。

---

### 3.3 C 档：可扩展双 GPU，24×7 多用户边车

**适合**：至少 4 个活跃全模态会话、TTS 与 VLM 需要显存/故障域隔离、业务需 24×7、已有机柜/机房和运维能力。宿舍或普通卧室不适合部署这一档。

#### 推荐 BOM

| 部件 | 起步双 GPU | 扩展方案 |
| --- | --- | --- |
| GPU | 2×NVIDIA L40S 48 GB ECC、每卡独立进程池 | 扩到 4×L40S；或 2×RTX PRO 6000 Blackwell Server 96 GB |
| CPU | 1～2×EPYC 9335/9355 级，合计 32～64 核起 | 扩展前预留足够 PCIe lanes；不为纯推理盲目堆 192 核 |
| RAM | 256 GB ECC | 512 GB ECC |
| 系统盘 | 2×1.92 TB enterprise NVMe RAID1 | BOSS/M.2 镜像 |
| 数据/模型 | 4×3.84 TB enterprise NVMe RAID10 | 对象存储/独立备份节点 |
| 网络 | 2×25GbE + 独立 BMC | 100GbE 只在多节点/集中存储确有需求时上 |
| 电源 | 2+0/1+1 冗余，200～240 V 机房电路 | 按扩卡后的整机功耗重新验收 |

**厂商事实**：L40S 为 48 GB GDDR6 ECC、最大 350 W、PCIe Gen4 x16；不支持 MIG，也不支持 NVLink。来源：[NVIDIA L40S](https://www.nvidia.com/en-us/data-center/l40s/)。因此双卡应按两个独立故障域调度，而不是假设有 96 GB 统一显存。

**推荐整机平台**：Lenovo ThinkSystem SR675 V3。官方产品指南支持 5th Gen EPYC 9005、4/8 个双宽 PCIe GPU 位，并明确列出 L40S 48 GB 和 RTX PRO 6000 Blackwell Server 96 GB；其 2-2-1 方案允许从两块 GPU 起步再扩展。来源：[SR675 V3 产品指南](https://lenovopress.lenovo.com/lp1611-thinksystem-sr675-v3-server)、[Lenovo Hybrid AI 2-2-1 指南](https://lenovopress.lenovo.com/lp2313-lenovo-hybrid-ai-221-platform-guide)。

**竞价对照**：

- Dell PowerEdge R760xa：2U、双 Xeon、最多 32 DIMM、2400/2800 W 冗余电源和 iDRAC；具体 L40S BOM、供电线和中国区交付必须由销售书面确认。来源：[Dell PowerEdge R760xa](https://www.dell.com/en-us/shop/ipovw/poweredge-r760xa)。
- H3C/HPE：中国本地服务覆盖较好，但官网公开页没有足够证据确认本项目目标卡的精确 BOM；只在销售提供“GPU 型号、卡数、供电、散热、驱动、Ubuntu 版本、三年上门”书面兼容清单后比较。来源：[H3C 智慧计算](https://www.h3c.com/cn/Products_And_Solution/Server/)。

**高显存替代**：RTX PRO 6000 Blackwell Workstation/Server Edition 均为 96 GB GDDR7 ECC，最大功耗可达 600 W；适合未来更大 VLM/本地 LLM，但对当前 SoulX + 7B VLM 明显过配。来源：[RTX PRO 6000 Workstation](https://www.nvidia.com/en-us/products/workstations/professional-desktop-gpus/rtx-pro-6000/)、[RTX PRO 6000 Server](https://www.nvidia.com/en-us/data-center/rtx-pro-6000-blackwell-server-edition/)。

#### 进程隔离与容量（估算）

- GPU 0：SoulX 高质量 TTS，先放 2 个 worker；GPU 1：VLM，先放 2 个 7B 4-bit worker；默认低时延 TTS 仍可回 RK3588。
- 起始验收目标：**4 个活跃全模态会话**，逐级压到 8；只有语音结束到开口 p95 ≤3.5 秒、TTS 热启动 p95 ≤1 秒、取消 ≤250 ms、GPU 显存峰值 <85% 且 8 小时无泄漏时，才能上调 worker。
- 2×L40S 整机平均约 800～1,300 W、压力峰值约 1,600～2,000 W；月电量约 576～936 kWh。按 0.6～1.0 元/kWh 的预算假设，月电费约 346～936 元，制冷和机柜电费另计。
- 双 L40S、256 GB、企业 NVMe、三年服务的中国区整机先按 **180,000～320,000 元询价预算**；双 RTX PRO 6000 96 GB 先按 **350,000～650,000 元询价预算**。这是宽区间采购估算，不是公开成交价。

---

## 4. 云 GPU：先租后买

三家国内云厂商都提供 GPU 实例，但型号、地域、配额和实时价格变化大；本次没有找到能同时证明“中国大陆当前可购 + 指定 L40S + 固定活动价”的官方公开页面，因此不编造小时价。

| 厂商 | 官方事实 | 本项目用法 | 采购动作 |
| --- | --- | --- | --- |
| 腾讯云 GPU / HAI | 支持 GPU CVM、驱动/CUDA 镜像和按量/竞价等计费；价格由计算、存储、网络组成 | 7～14 天 SoulX/VLM 兼容与时延试验 | 控制台筛选显存 ≥24 GB，导出含税询价；确认大陆地域、出网费、关机是否继续计费 |
| 阿里云 GPU ECS/EGS | 支持按量、包年包月、抢占式、节省计划；可购规格随地域变化 | 可中断离线音色评测用抢占式；实时服务不用可随时回收的实例 | 先查目标地域库存和驱动/CUDA，再做一周账单 |
| 华为云 GACS | 支持按需、包周期和竞价，多类 GPU/昇腾实例 | 作为国产云服务/售后报价对照 | 不默认假设 CUDA 模型能在昇腾无改动运行；SoulX 必须选 NVIDIA/CUDA 兼容规格 |

官方入口：[腾讯云 GPU](https://cloud.tencent.com/product/gpu)、[腾讯云计费说明](https://cloud.tencent.com/document/product/560/8025)、[阿里云 GPU 购买](https://help.aliyun.com/zh/egs/user-guide/create-a-gpu-instance/)、[华为云 GPU](https://www.huaweicloud.com/product/gpu.html)。华为云另有每日限额的新用户免费试用，适合安装验证而非生产容量承诺；来源：[华为云免费试用说明](https://www.huaweicloud.com/special/pro-ecs-freetrial.html)。

### 4.1 租用验收脚本应记录

1. 冷启动、热启动、首音频、完整 WAV、RTF、峰值显存、主机 RSS；
2. 10/30/60/120 字中英混合与副语言标签；
3. 1、2、4 并发 p50/p95，以及排队长度；
4. 新 generation 取消后进程停止时间、显存回落时间和临时文件清理；
5. 30 分钟与 8 小时 soak 的显存、温度、错误率；
6. 同一参考音色的盲听自然度、稳定度、相似度；
7. VLM 与 SoulX 同卡时的相互干扰。

不通过时，结论应是“保留默认 sherpa TTS，SoulX 仅离线生成或不采用”，而不是再加钱买更大服务器。

---

## 5. 程序、数据、模型、配置和密钥如何落盘

任何新主机都应延续 V2 的分离原则：

```text
/opt/veyrasoul/              # 程序与不可变镜像，只读发布
/srv/veyrasoul/data/         # User/Anima 数据库、记忆、审计
/srv/veyrasoul/models/       # 可重下的模型资产，不进入用户备份
/etc/veyrasoul/              # 非敏感配置与版本化 schema
/run/credentials/veyrasoul/  # 启动时注入密钥，不写镜像/仓库
/var/cache/veyrasoul/        # TTS/VLM 临时缓存，可清理
```

最低采购要求：

- 数据盘镜像/RAID 不是备份；每天做加密增量备份到不同故障域，按月做离线恢复演练；
- 用户数据备份不包含模型仓库和可重建缓存；
- GPU sidecar 只拿到本轮最小输入，不直接挂载完整用户数据库；
- OS/容器、用户数据、模型和缓存要有独立容量配额；
- BMC、SSH、数据库和模型 API 不暴露到公网；公网只到鉴权 Gateway；
- 采购合同写明硬盘保留/销毁、三年保修、风扇/电源冗余、Ubuntu/CUDA 驱动支持。

---

## 6. 最终推荐路径与决策门

### 现在（推荐）

1. **A 档**：现有 ELF2 + DeepSeek V4 Flash；如需要稳定公网控制面，使用腾讯 99 元活动机做单用户开发入口，但不要受 3 Mbps 套餐误导为生产容量。
2. 用腾讯/阿里/华为任一按量 GPU 租 7～14 天，完成 SoulX 与候选 VLM 的同机基准；内部试验预算上限先设 1,000～3,000 元（不是厂商报价），并启用自动关机/费用告警。
3. 用实际日志算每月 GPU 活跃小时，不以“未来也许会用”采购。

### 何时购买 B 档

同时满足：

- SoulX 盲听显著优于默认 TTS；
- 单卡热启动 TTS p95 ≤1 秒，语音结束到开口 p95 ≤3.5 秒；
- 24 GB 卡可在 <85% 峰值显存下运行目标 TTS/VLM 调度；
- 最近三个月预计 GPU 活跃小时使租云成本接近本地三年 TCO；
- 团队能承担驱动、监控、备份和停机恢复。

满足后，性价比首选约 5 万元的 5090D V2 整机作为隔离 sidecar；若必须 ECC/Ubuntu 认证/三年上门，再向 Lenovo P8、Dell Precision 7960、HP Z8 Fury 三家发同一 BOM 询价。

### 何时购买 C 档

同时满足：

- 4 个以上活跃会话已在单 GPU 上造成可复现的 p95/SLO 违约；
- TTS 与 VLM 必须不同 GPU 隔离，而不是简单排队即可解决；
- 已有机房、200～240 V 供电、制冷、机柜和 24×7 运维；
- 至少收齐 Lenovo/Dell/H3C 三份同规格含税 BOM 与三年服务报价；
- 做过一周云 GPU 同等负载基准。

若这些条件没有同时满足，双 GPU 服务器是昂贵的闲置资产，不是低时延保证。

---

## 7. 三年 TCO 计算模板

不要只比显卡价格。统一使用：

```text
本地三年 TCO = 含税整机 + 内存/盘/UPS + 36 × (电费 + 制冷/机柜 + 公网 + 维护) - 残值
云三年 TCO   = GPU 按量小时 × 月活跃小时 × 36 + 系统盘/快照 + 出网 + CPU 常驻节点
回本月数     = 本地一次性投入 / (云每月费用 - 本地每月运行费用)
```

所有报价必须固定：GPU 精确型号与显存、CPU、DIMM 数量、NVMe 耐久度、网卡、冗余电源、Linux/驱动、保修、税和交期。只有写到同一张 BOM 上，厂商价格才可比较。

---

## 8. 官方来源与访问记录

以下页面均在 **2026-07-13（Asia/Shanghai）**访问；活动和价格最易变化，购买前必须再次打开原页并保留下单截图/报价单。

| 类型 | 官方来源 | 本文使用事实 |
| --- | --- | --- |
| LLM | [DeepSeek 模型与价格](https://api-docs.deepseek.com/zh-cn/quick_start/pricing) | V4 Flash/Pro 价格、并发和旧模型名弃用日期 |
| TTS | [SoulX-Podcast GitHub](https://github.com/Soul-AILab/SoulX-Podcast/tree/5ac9c0e1cfe596396200c7d38e3fd53b7b3fbf4b) | CUDA 推理链、非流式现状、许可证 |
| TTS 模型 | [SoulX-Podcast-1.7B HF](https://huggingface.co/Soul-AILab/SoulX-Podcast-1.7B) | 模型卡与文件资产 |
| GPU | [NVIDIA 中国 RTX 5090D V2](https://www.nvidia.cn/geforce/graphics-cards/50-series/rtx-5090-d-v2/) | 24 GB、575 W、建议系统功率 1000 W、官方起售价 |
| GPU | [NVIDIA L40S](https://www.nvidia.com/en-us/data-center/l40s/) | 48 GB ECC、350 W、无 MIG/NVLink |
| GPU | [RTX PRO 6000 Workstation](https://www.nvidia.com/en-us/products/workstations/professional-desktop-gpus/rtx-pro-6000/) | 96 GB ECC、600 W |
| CPU | [AMD Ryzen 桌面 CPU](https://www.amd.com/en/products/processors/desktops/ryzen.html) | 9950X 16C/32T、170 W |
| CPU | [AMD EPYC 9005](https://www.amd.com/en/products/processors/server/epyc/9005-series.html) | 核数、TDP、PCIe/内存平台范围 |
| 中国整机/活动 | [联想刃 9000K 搜索页](https://s.lenovo.com.cn/search/?cat=310-311&innerKey=&key=%E6%8B%AF%E6%95%91%E8%80%85+%E5%88%839000&recommendType=0) | 5090D V2 24 GB 整机、访问日标价/活动 |
| 工作站 | [Dell Precision 7960 中国](https://www.dell.com/zh-cn/shop/precision-7960-%E5%A1%94%E5%BC%8F/precision-7960-%E5%A1%94%E5%BC%8F/spd/precision-t7960-workstation) | Ubuntu、ECC、可选 GPU/价格需询价 |
| 工作站 | [Lenovo ThinkStation P8](https://www.lenovo.com/us/en/p/workstations/thinkstation-p-series/thinkstation-p8-workstation/len102s0017) | 最多三 GPU、1400 W、10GbE |
| 工作站 | [HP Z8 Fury 中国](https://www.hp.com/cn-zh/workstations/z8-fury-specs.html) | 多 GPU/PCIe/NVMe 扩展 |
| GPU 服务器 | [Lenovo SR675 V3](https://lenovopress.lenovo.com/lp1611-thinksystem-sr675-v3-server) | L40S/RTX PRO 6000 支持与 4/8 GPU 扩展 |
| GPU 服务器 | [Dell R760xa](https://www.dell.com/en-us/shop/ipovw/poweredge-r760xa) | 2U、内存、PCIe、电源和管理 |
| 云 CPU 活动 | [腾讯云轻量特惠](https://cloud.tencent.com/act/pro/lhsale) | 4C4G3M 99 元/年、新用户条件、活动期限 |
| 云 GPU | [腾讯云 GPU](https://cloud.tencent.com/product/gpu) | GPU CVM/HAI、驱动镜像和计费入口 |
| 云 GPU | [阿里云购买 GPU 实例](https://help.aliyun.com/zh/egs/user-guide/create-a-gpu-instance/) | 地域库存、按量/抢占式购买方式 |
| 云 GPU | [华为云 GPU](https://www.huaweicloud.com/product/gpu.html) | 按需/包周期/竞价和产品入口 |
