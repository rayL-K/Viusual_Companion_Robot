# VeyraSoul V2 Live2D 交互差分安全审查

## 元数据

- **审查日期**：2026-07-13
- **审查基线**：`HEAD 19621a2`（`codex/veyrasoul-v2`）
- **最终工作树快照**：2026-07-13 21:16 CST
- **审查方法**：Trail of Bits `differential-review`，中型代码库 focused review
- **代码库规模**：98 个已跟踪源码文件；Web `src` 35 个，Backend 56 个；本差分另新增 9 个交互源码/测试文件
- **重点范围**：浏览器手势信任边界、DOM dataset 暴露、资源清理、依赖与许可证、Live2D 模型资产、测试覆盖、调用爆炸半径与 Git 历史

## 1. 执行摘要

本差分把原有“指针仅驱动注视”扩展为完整的本地身体交互链路：`@use-gesture/vanilla` 统一 Pointer Events，Live2D `hitTest` 把屏幕坐标转换为固定身体语义，`InteractionDirector` 生成短时反射，`SignalMixer` 在原有 60 FPS 更新点叠加反射。当前事件只在浏览器本地流转，不进入 WebSocket、对话、长期记忆或分析日志。

最终快照中没有发现可由远程输入直接利用的高危代码漏洞，也没有发现原始指针轨迹越过渲染层。审查期间识别出的重复 contact、重复 `start()` 残留计时器、MIT notice 未进入构建制品三项问题均已修复并补充回归门禁。

仍有 **1 个发布阻断项**：仓库和 Vite 制品继续携带约 51 MB 的 Strawberry Rabbit 模型/美术资产，但没有可审计的模型再分发许可证；manifest 已明确标记 `verification-required-before-public-redistribution`。因此结论为：

- **本机 V2 开发与合并**：通过；
- **交互代码安全边界**：通过，保持事件为本地、不可信 UI 信号；
- **包含当前模型资产的公网 V2/CDN/公开代码包发布**：不通过，直到模型授权闭环或资产从公开制品移除。

## 2. 本次变更

### 2.1 生产链路

1. `AvatarStage.tsx` 使角色舞台可聚焦，并为 Enter/Space 提供等价主交互；
2. `AvatarInteractionController.ts` 识别 hover、contact、tap、press、stroke、release，限制主指针/鼠标左键，并管理 press timer、手势实例和本地反馈；
3. `Live2DHitTestPort.ts` 使用 Pixi mapper 或 canvas/renderer 比例回退进行坐标转换；
4. `StrawberryRabbitHitAreas.ts` 把模型 HitArea 名称收敛到固定枚举，并对重叠区域实施确定性优先级；
5. `InteractionDirector.ts` 根据当前 affect/phase 产生有截止时间的局部反射；
6. `Live2DStageController.ts` 只把语义事件交给本地 director，同时把最后一次 `area/gesture/sequence` 写入调试 dataset；
7. `SignalMixer.ts` 在连续参数层合并反射，不改变真实音频 RMS 的口型所有权。

### 2.2 资产与依赖

- 新增并精确锁定 `@use-gesture/vanilla@10.3.1`，传递依赖为同版本 `@use-gesture/core`；
- 桌面/移动 model3 增加相同的 11 个 HitArea；
- `manifest.json` 删除了旧的本机绝对来源路径，新增语义映射、命中优先级和授权状态；
- `public/THIRD_PARTY_NOTICES.md` 随 Vite 构建发布，`check.ps1` 与 E2E 均验证其存在和内容。

## 3. 信任边界与数据流

```text
不可信浏览器输入
Pointer/Touch/Pen/Keyboard
        |
        v
AvatarInteractionController --原始 clientX/Y--> 本地 CSS 反馈/注视
        |
        | 固定枚举、限频、无原始路径
        v
AnimaInteractionEvent --> InteractionDirector --> SignalMixer --> Cubism 参数
        |
        +--> data-interaction-area/gesture/sequence（仅同源 DOM 调试态）

无 WebSocket / LLM / Memory / Analytics 出边
```

边界结论：

- PointerEvent 必须视为**不可信 UI 输入**，不能被用作身份、授权、付费、关系记忆或安全审计证据；
- `StrawberryRabbitHitAreas` 只接受固定映射中的模型名称，未知字符串被丢弃，不能进入 dataset 或 CSS 值；
- `AnimaInteractionEvent` 类型不含 `clientX/clientY/path/movement/velocity`，控制器单元测试也对序列化结果做了否定断言；
- DOM dataset 暴露的是固定枚举与局部序号。任意同源脚本本来就能监听 Pointer Events，因此该 dataset 没有新增跨源能力；舞台销毁时三个字段会删除；
- 当前 `rg` 调用图中，交互事件只被 `Live2DStageController` 消费，没有 backend、RealtimeClient 或协议层调用者。

## 4. 未关闭发现

### V2-INT-001 — [P1 / 发布阻断（许可合规）] Strawberry Rabbit 模型没有可验证的公开再分发授权

**置信度：高。** 这是供应链/发布合规阻断，不是远程代码执行漏洞。

**位置与证据**

- `web/public/live2d/Strawberry_Rabbit/manifest.json:5`：`licenseStatus` 为 `verification-required-before-public-redistribution`；
- `web/public/THIRD_PARTY_NOTICES.md:75-79`：明确说明 Cubism/Pixi 软件许可证不自动授予 `.moc3`、纹理、动作和表情的再分发权；
- 模型目录包含 45 个已跟踪文件，共 51,051,754 bytes，其中包括 17.5 MB `.moc3` 和多张 4096/1024 纹理；目录内没有模型作者许可证、购买协议、授权书或可验证来源说明；
- `npm run build` 会把整个目录原样复制到 `dist/live2d/Strawberry_Rabbit`，当前没有根据 `licenseStatus` 阻止构建/发布的 gate。

**历史**

资产由提交 `a6be655`（`feat(v2): 打通多模态视频通话纵切片`）引入；本差分没有新引入模型二进制，但修改了 model3/manifest 并继续让它进入 Web 制品。旧 manifest 曾公开本机绝对路径 `E:/jieya/Strawberry_Rabbit-DLC`，本差分已删除该路径，降低了本机信息暴露，但不能替代授权证据。

**具体发布场景**

若直接把当前 `dist` 部署到 `anima.veyralux.org`、上传公开 GitHub 仓库或比赛代码包，任何访问者都可以下载完整 `.moc3`、纹理、动作和表情。若原资源许可不覆盖公开 Web 托管、修改或二进制再分发，项目会面临下架、投诉或比赛材料失效；写一份第三方 notice 不能取得原作者权利。

**修复要求**

满足以下任一项后才允许公开发布：

1. 保存能覆盖比赛展示、公开 Web 托管、修改、`.moc3`/纹理再分发及预期商业用途的作者/销售方许可，并在发布记录中引用证据；或
2. 从 Git、`public`、`dist` 和代码包中排除模型资产，只保留加载接口，由部署者在私有环境放置合法持有的副本。

建议增加发布 gate：当 `licenseStatus != verified-for-public-redistribution` 且构建制品包含该模型目录时，release job 必须失败。普通 `npm run build` 可保留供本机开发，但不得被误当作可发布制品。

## 5. 审查中已关闭的问题

### 5.1 重复 contact 与主指针校验旁路 — 已修复

初始实现同时在 `onPointerDown` 与 `onDrag(state.first)` 调用 `beginContact`。真实 E2E 中一次 tap 的 `sequenceDelta` 曾为 touch=4、desktop=5，而契约的 contact/tap/release 应为 3；`onDrag` 回退路径还没有重复校验 `isPrimary`/鼠标左键。

最终实现删除 `onDrag` 的二次建联，只允许经过 `onPointerDown` 校验的接触建立活动状态。E2E 现在要求触摸精确为 3；桌面允许 3 或 4（额外一个合法 hover-enter），最终六种 viewport 结果为：desktop=4，其余触摸 viewport=3。

### 5.2 重复 `start()` 可保留旧 press timer — 已修复

初始 `start()` 只销毁旧 Gesture handle，没有清理活动接触、hover 和 press timer。最终 `AvatarInteractionController.ts:94-103` 在重绑前销毁旧实例、清 timer、清 active/hover，并在旧实例存在时把 gaze 归零；`AvatarInteractionController.test.ts:428-441` 验证旧 timer 不会在重绑后发出 press。

### 5.3 新依赖的 MIT notice 未随 dist 分发 — 已修复

初始 notice 位于 `web/` 根目录，Vite 不会复制到 `dist`。最终文件迁移到 `web/public/THIRD_PARTY_NOTICES.md`；`scripts/check.ps1:41-43` 检查构建制品，`web/e2e/video-call.mjs:302-307` 还会通过 HTTP 验证版本声明。最终 `dist/THIRD_PARTY_NOTICES.md` 存在。

## 6. 依赖与供应链结果

- `package.json` 和 lockfile 对 `@use-gesture/vanilla` 使用精确版本 `10.3.1`；
- 安装树仅新增 `@use-gesture/vanilla@10.3.1 -> @use-gesture/core@10.3.1`；
- lockfile 包含 registry URL、SHA-512 integrity 和 MIT license 元数据；
- `npm audit --omit=dev --json`：生产依赖 6 个，已知漏洞 0（critical/high/moderate/low/info 均为 0）；
- 依赖被隔离在 `AvatarInteractionController` 的 factory/port 后，替换不会要求修改 Live2D、对话或记忆层；
- 独立供应链记录见 `docs/reviews/2026-07-13-use-gesture-supply-chain-review.md`。其结论为没有达到“两项及以上风险因素”的高风险新依赖；上游未提供专用 security contact，作为持续监控项保留。

## 7. 测试覆盖

### 7.1 已执行

| 命令 | 最终结果 |
| --- | --- |
| `npm run check` | 17 个测试文件、67 个测试全部通过；包含 `tsc --noEmit` |
| `npm run build` | 通过；42 modules transformed；notice 与 Live2D 静态资产进入 dist |
| `npm run e2e` | 通过；桌面、320/390 手机、平板横竖屏、手机横屏共 6 个 viewport，page error 为 0 |
| `npm audit --omit=dev --json` | 0 个已知生产依赖漏洞 |
| `git diff --check HEAD -- new_code/web` | 通过；仅有 Windows LF/CRLF 提示 |

### 7.2 已覆盖行为

- 主指针与鼠标左键过滤、键盘主交互；
- tap、380 ms press、48 ms stroke 节流、方向归一化、cancel、release；
- 语义事件不包含原始坐标/轨迹；
- Gesture/timer 的 destroy 与重复 start 清理；
- Pixi mapper 的 `this` 绑定和 canvas 比例回退；
- 未知 HitArea 丢弃、重叠区域优先级、桌面/移动/manifest 同步；
- director 的亲近/回避、speaking 衰减和过期；
- 真实 Chromium 的鼠标、触摸、键盘以及 notice HTTP 可达性。

### 7.3 覆盖缺口

- Chromium E2E 的命中探测在 5 个 viewport 命中 face、1 个命中 `ear.left`；尚未逐一验证手、臂、躯干、裙摆和双腿的真实动作中命中正确率；
- 没有 Firefox、WebKit/iOS Safari 或真实手机；桌面触摸仿真不能证明系统级手势竞争、误触率和 pointer capture 行为；
- 没有长时间 soak、listener 数量快照、WebGL/heap 曲线或高频触摸下的 60 FPS P95；
- 模型 HitArea 当前依赖 drawable AABB；测试证明配置同步和至少一个区域可响应，但不能证明透明区域/动作变形后的像素级准确度；
- 未取得模型作者源 `.cmo3`，无法核验或导出专用低多边形碰撞 ArtMesh；
- `npm audit` 只覆盖已知公告，不是恶意包、维护者账号接管或 provenance 证明。

## 8. Blast radius

### 8.1 直接调用面

- `AvatarInteractionController`、`InteractionDirector`、`Live2DHitTestPort` 只有 `Live2DStageController` 一个生产组合点；
- `InteractionDirector.sample()` 只在 `Live2DStageController.updateFrame()` 进入 `SignalMixer`；
- `AvatarStage` 只新增焦点/键盘入口，不改变 call controls、media capture 或 realtime client；
- backend、WebSocket 协议、Memory/RAG、LLM/TTS/Vision 无调用者，也没有 schema 变化。

### 8.2 运行时影响

- Gesture 监听覆盖整个 `.presence` 舞台；stroke 语义事件最多约 20.8 次/秒，pointer move 只更新本地 gaze；
- DOM 侧最多保留最后一次固定语义 dataset 和一个 560 ms feedback timer，销毁时清理；
- 模型 HitArea 同时修改桌面与移动 model3，共享同一 `.moc3`；映射错误会影响所有浏览器命中，但不会扩展到服务端数据；
- 新 npm 代码进入每个 V2 Web bundle，故 lockfile、notice 和供应链监控覆盖所有客户端；
- Vite 会复制完整模型目录，所以模型许可问题的发布爆炸半径是所有 V2 静态站点和代码分发渠道。

## 9. Git 历史与基线比较

- `a6be655` 首次引入 Live2D Stage 和模型资产；基线使用两个显式 `pointermove/pointerleave` 监听，并在 `destroy()` 中对称移除；
- `ad660b6` 增加 `AvatarActionScheduler`，本差分没有绕过其 capability/generation 门控；
- 当前交互目录是未跟踪的新实现，因此没有可用的 `git blame` 或历史修复记录；风险判断主要依赖调用图、运行时 E2E 与新单元测试；
- 差分用 Gesture handle 的 `destroy()` 取代手写 listener 移除，并在 Stage destroy 中继续清理 resize observer、feedback timer、dataset、Live2D hook、scheduler 和 Pixi resources；没有发现基线清理逻辑被静默删除；
- 模型许可风险从 `a6be655` 起已经存在，本差分通过 manifest/notice 把它显式化，但尚未真正闭环。

## 10. 建议与合并门禁

### 合并前/当前分支

1. 保留 touch 精确 sequence delta、重复 start、原始坐标否定断言和 notice 构建检查，禁止为了“测试稳定”放宽为 `>= 3`；
2. 保持交互事件本地化。如果未来进入服务端，必须新增版本化 schema、客户端限频、服务端限流、用户同意和数据生命周期，并继续禁止原始轨迹；
3. 不把 `data-interaction-*` 或 pointer 事件当可信业务信号。

### 公网/比赛制品发布前

1. **必须关闭 V2-INT-001**：取得可审计模型许可或从公开制品排除模型；
2. 为授权状态增加自动 release gate，并验证压缩包/CDN/Git LFS 等所有分发路径，而不只检查文档；
3. 在真实目标手机上逐区域验收 HitArea、横竖屏、动作变形、误触和 pointer capture；
4. 运行至少 30 分钟交互 soak，记录 Live2D frame time P50/P95、listener/timer 数量和 JS heap 趋势。

## 11. 方法与限制

本审查按以下顺序完成：

1. `git status/diff/log/blame/show` 建立 `19621a2` 基线、当前差分和历史；
2. 检索所有交互类型与调用者，确认不存在 backend/realtime/memory 出边；
3. 逐文件审阅事件验证、命中映射、语义收敛、dataset、timer/listener/WebGL 清理；
4. 审阅 package/lock、安装包 LICENSE、静态 vendor、模型目录和构建产物；
5. 构造普通触摸、非主指针、重复绑定、悬挂 timer、未知 HitArea、公开静态资产等对抗/失败场景；
6. 在并行实现完成后于 21:15 重新读取最终 diff，并重新执行 check/build/audit/E2E。

限制：本轮没有运行 CodeQL/Semgrep 全库扫描，因为目标是 focused differential review；没有审阅既有 V2 身份鉴权、WebSocket Origin/限流等非本差分问题，它们由 `2026-07-13-v2-differential-security-review.md` 单独覆盖；也没有法律文本、真实设备或模型作者工程源文件可用于关闭许可与精确命中问题。

## 附录 A：重点文件

- `web/src/features/avatar/interaction/AvatarInteractionController.ts`
- `web/src/features/avatar/interaction/InteractionDirector.ts`
- `web/src/features/avatar/interaction/Live2DHitTestPort.ts`
- `web/src/features/avatar/interaction/StrawberryRabbitHitAreas.ts`
- `web/src/features/avatar/interaction/types.ts`
- `web/src/features/avatar/Live2DStageController.ts`
- `web/src/features/avatar/SignalMixer.ts`
- `web/e2e/video-call.mjs`
- `web/public/live2d/Strawberry_Rabbit/*.model3.json`
- `web/public/live2d/Strawberry_Rabbit/manifest.json`
- `web/public/THIRD_PARTY_NOTICES.md`
- `scripts/check.ps1`

## 附录 B：最终判断

| 维度 | 判断 |
| --- | --- |
| 浏览器手势输入校验 | 通过；仅作为不可信本地 UI 信号 |
| 原始坐标/轨迹隐私 | 通过；未越过 renderer-local 边界 |
| dataset 暴露 | 通过；固定枚举、无原始坐标、销毁清理 |
| timer/listener 生命周期 | 通过；destroy 与重复 start 有回归测试 |
| npm 依赖/CVE/notice | 通过；精确锁定、audit 0、notice 随 dist |
| 模型资产授权 | **不通过；公网发布阻断** |
| 单元/Chromium E2E | 通过；仍缺真机、全区域与 soak |
