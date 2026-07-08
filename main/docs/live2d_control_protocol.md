# Live2D 控制协议

本协议用于约束 LLM 输出，让模型只表达“控制意图”，真正的 Live2D 参数写入仍由前端白名单、范围裁剪和动作冲突组处理。

## 基本结构

```json
{
  "text": "要朗读给用户的回复。",
  "emotion": "happy",
  "expression": "heart",
  "motion": "scene1",
  "actions": [],
  "speech": {
    "voice": "female_zh",
    "rate": 1.0,
    "pitch": 1.18
  },
  "parameters": {
    "ParamAngleX": 4,
    "ParamMouthForm": 0.3
  }
}
```

## 动作计划

`actions` 用于表达可见动作、道具和姿态。不要把“之后、几秒后、然后”的动作计划只写在 `text` 中。

```json
{
  "text": "主人，我先举起双手，五秒后拿起游戏机。",
  "emotion": "happy",
  "expression": "gaming",
  "motion": "scene1",
  "actions": [
    { "name": "right_hand_up", "mode": "hold", "duration_ms": 3200, "delay_ms": 0 },
    { "name": "left_hand_up", "mode": "hold", "duration_ms": 3200, "delay_ms": 0 },
    { "name": "gaming", "mode": "hold", "duration_ms": 3200, "delay_ms": 5000 }
  ],
  "speech": { "voice": "female_zh", "rate": 1.0, "pitch": 1.18 },
  "parameters": {}
}
```

- `mode: "hold"` 表示持续保持，直到新动作冲突或显式 `off`。
- `mode: "pulse"` 表示短时动作，持续时间由 `duration_ms` 控制。
- `mode: "off"` 表示关闭同组动作。
- `delay_ms` 表示延迟执行时间，范围是 0 到 30000。
- 新一轮 LLM 回复到来时，前端会取消上一轮尚未触发的延时动作，避免旧计划干扰新对话。

## 动作冲突

右手和左手可以同时举起，但游戏机、麦克风、比心这类双手动作会关闭左右手姿态。这样可以表达“先举起双手，五秒后拿游戏机”这类计划。

## 非标准回复修复

LLM 可能偶发返回普通文本、Markdown 或损坏 JSON。服务端不会把这种情况直接交给前端，也不会让 Live2D 停止回复；处理规则如下：

- API 调用失败、密钥缺失、网络超时仍视为服务错误。
- LLM 已返回内容但不符合控制 JSON 时，服务端会把错误回复、解析错误和允许表情/动作再次发给 LLM，请它只输出标准 JSON。
- 修复后的 JSON 仍然要走同一套白名单、动作裁剪和参数范围限制。
- 如果结构修复仍失败，才降级为安全控制计划。
- 最终降级计划会尽量从普通文本或损坏 JSON 的 `text` 字段提取可朗读内容，只使用白名单表情、默认动作、固定女声、空动作列表和安全嘴型参数。

这样前端始终消费稳定结构，Live2D 展示层只负责渲染和白名单映射。
