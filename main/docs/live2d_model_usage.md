# Strawberry_Rabbit 模型使用说明整理

来源文件：`E:/jieya/草莓兔兔-DLC+(2)/草莓猫猫兔使用说明.txt`

整理日期：2026-05-12

## 关键结论

- 模型说明中写明“消除水印 ctrl+shift”。
- 对应 VTube Studio 配置文件 `草莓兔兔.vtube.json` 中的热键为 `LeftControl + LeftShift`。
- 该热键动作是 `ToggleExpression`，表达式文件是 `水印.exp3.json`。
- `水印.exp3.json` 实际写入 `Param261 = 1.0`。
- 因此在我们的 Web Live2D 展示台中，应持续设置 `Param261 = 1` 来模拟“已开启消除水印”状态。

## VTube Studio 热键对应关系

| 功能 | 热键 | 表达式/动作文件 |
| --- | --- | --- |
| 消除水印 | `Ctrl + Shift` | `水印.exp3.json` |
| 右抬手 | `Numpad1` | `右抬手.exp3.json` |
| 左抬手 | `Numpad2` | `左抬手.exp3.json` |
| 双马尾 | `Numpad3` | `双马尾.exp3.json` |
| 麦克风 | `Numpad4` | `话筒.exp3.json` |
| 比心 | `Numpad5` | `比心.exp3.json` |
| 游戏机 | `Numpad6` | `打游戏.exp3.json` |
| 黑脸 | `Numpad7` | `黑脸.exp3.json` |
| 哭哭 | `Numpad8` | `哭哭.exp3.json` |
| 爱心眼 | `Numpad9` | `爱心.exp3.json` |
| 星星眼 | `Ctrl + 1` | `星星眼.exp3.json` |
| 晕晕 | `Ctrl + 2` | `晕晕.exp3.json` |
| 流汗 | `Ctrl + 3` | `流汗.exp3.json` |
| 着急 | `Ctrl + 4` | `着急.exp3.json` |
| 生气 | `Ctrl + 5` | `生气.exp3.json` |
| 脸红 | `Ctrl + 6` | `红脸.exp3.json` |
| 花花 | `Ctrl + 7` | `花花.exp3.json` |
| 问号 | `Ctrl + 8` | `问号.exp3.json` |
| 黑化 | `Ctrl + 9` | `黑化.exp3.json` |
| 舰长轮盘 | `Ctrl + Z` | `舰长.motion3.json` |
| 提督轮盘 | `Ctrl + X` | `提督.motion3.json` |
| 总督轮盘 | `Ctrl + C` | `总督.motion3.json` |

## 对当前展示台的影响

我们当前的 `main/live2d_stage` 不运行 VTube Studio，因此不能直接触发 VTube Studio 热键。正确做法是：

1. 从 `.vtube.json` 和表达式文件中提取热键背后的表达式/参数。
2. 在 Web 展示台中直接写入对应 Live2D 参数。
3. 对 LLM 暴露的是语义化表情名，而不是键盘热键。

当前已在 Web 展示台和微信小程序中落地：

- 初始化和每帧更新时写入 `Param261 = 1`，用于消除水印。
- 聊天气泡位于模型舞台之外的独立阅读区，不与模型或水印重叠。
- LLM 控制层只允许白名单参数，不允许任意写模型参数。
