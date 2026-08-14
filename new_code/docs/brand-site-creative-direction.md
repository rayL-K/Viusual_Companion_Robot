# VeyraLux 品牌站与 Anima 产品入口

> 本文记录已落地站点的产品边界和回归门槛，不再保留被实际站点取代的分页式创意旧稿。

## 域名职责

| 域名 | 职责 | 不应承担 |
| --- | --- | --- |
| `veyralux.org` | VeyraLux 品牌门户、理念、工程架构和 Anima 介绍 | 摄像头/麦克风权限、实时会话或隐式 WebSocket |
| `anima.veyralux.org` | Anima v0.0.1 的 Web/App 产品入口 | 品牌站长文叙事或与对话无关的营销转场 |

品牌站到 Anima 的 CTA 要显示完整目标域名。跨域链接不携带 session、用户 ID、密钥、供应商参数或内部部署状态。

## 已落地的视觉语法

- 一个连续、原生滚动的视觉叙事，不使用 scroll-snap 伪装 PPT 分页；
- Canvas living field、环境光洗、signal spine 和深度视差贯穿页面；
- Hero -> presence stream -> pipeline -> architecture -> Anima release -> orbit closing 形成连续空间；
- 桌面端保留精细层次，移动端减少装饰计算，低高度横屏取消长 sticky；
- `prefers-reduced-motion`、Save-Data 和页面 visibility 都会降低/暂停非必要动画；
- 锚点跳转考虑固定顶部高度，不遮挡标题。

## 文案原则

1. 产品对外统一为 **Anima v0.0.1**。
2. 说清“产品运行于可替换的 Linux Server，并通过 Provider 接口接入模型能力”，不把任何硬件写成产品的唯一形态。
3. 可用自动化证据说明“已通过本机浏览器验证”，但不把它写成真实手机、目标服务器或公网 SLO 成绩。
4. “60 FPS”只写为 Live2D/本地预览目标，直到有真机 p50/p95 证据。
5. 不用“毫秒级无等待”、虚构用户量、虚构识别率或虚构发布进度。
6. Live2D 运行库和模型再分发权分开表述，公开制品只使用授权闭环的资产。

## 隐私与性能边界

- 品牌站不请求摄像头、麦克风、通知或位置；
- 不嵌入会自动连接 Anima realtime endpoint 的隐藏 iframe；
- 不使用会话录屏、精细鼠标轨迹或输入内容分析；
- Canvas 在后台、reduced-motion 或 Save-Data 下停止/降频，不让品牌动效和 Anima 通话争夺移动端资源；
- 外部链接使用 `rel="noopener noreferrer"`，可访问名称说明将打开产品入口。

## 回归门槛

- 1440×900、390×844、320×568 无 body/文字溢出和主要 CTA 裁切；
- 滚动中不出现 snap/pin spacer 锁屏感；
- Canvas 前台持续运动，页面后台停止，返回后恢复；
- 动态切换 Save-Data/reduced-motion 时不重载也生效；
- 标题锚点停在顶部导航之下；
- unknown route 返回 404，CSP 和 Permissions-Policy 不因动效放宽。
