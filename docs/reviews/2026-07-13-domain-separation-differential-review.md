# V1/V2 域名隔离差异安全审查

审查日期：2026-07-13

基线：`7206a02`

历史依据：`77bdb4c` 曾将 V1 入口迁移到 `anima.veyralux.org`；本次按新的版本边界恢复并隔离域名。

范围：当前工作区中 V1 客户端、ELF2 默认配置、Cloudflare Worker 路由、V2 部署文档和对应测试。

## 结论

**通过，可以发布 V1 域名隔离配置。未发现本次变更引入的安全回归。**

- V1 唯一公网入口为 `robot.veyralux.org`。
- V2 预留入口为 `anima.veyralux.org`，当前不回源到 V1。
- Worker 的自定义域和运行时主机白名单同步收窄为单一 V1 域名，未出现“配置移除、代码仍接受”的偏差。
- 上游 Origin 固定为 V1 正式域名，保持与 ELF2 的精确域名校验一致。
- `DEVICE_TOKEN` 缺失时仍返回 503，保持 fail-closed；本次没有增加默认令牌、宽松主机匹配或通配域。

## 风险分级与差异分析

| 范围 | 风险 | 结果 |
|---|---:|---|
| `tools/cloudflare/gateway/src/index.ts` | 高 | 公网主机白名单由两个域名收窄为 V1 单域名；外部调用面减少 |
| `tools/cloudflare/gateway/wrangler.jsonc` | 高 | 自定义域路由同步移除 V2 预留域；与运行时白名单一致 |
| `main/**`、`tools/board/**` | 中 | V1 默认 URL、CORS 主机和验收脚本统一切回 `robot`；有对应自动化测试 |
| `new_code/**` | 低 | 仅明确 V2/V1 入口边界和未来发布门禁，不激活部署 |
| 根文档与提交说明 | 低 | 评委当前 V1 链接改回 `robot`，不改变权限模型 |

## 攻击面与爆炸半径

- 入口层：1 个 Cloudflare Worker、1 个 custom domain、1 个 VPC Service 回源链路。
- 客户端层：V1 Web、微信小游戏和板端验收脚本的默认域名。
- V2 层：只改发布说明；V2 Gateway、认证、数据和媒体代码未被触碰。
- 未扩大 Host/Origin allowlist，未增加跨域访问，未新增外部请求目标。

具体对抗检查：

1. 请求 `anima.veyralux.org` 不再落入 V1 Worker，无法借 V2 预留域访问 V1。
2. 伪造其他 `*.veyralux.org` 主机不能通过精确 `Set` 白名单；代码未使用后缀或子串匹配。
3. 缺少 `DEVICE_TOKEN` 时 Worker 继续拒绝回源，不存在无凭据运行默认值。
4. 浏览器发送的 Origin 在 V1 回源前被规范化为唯一正式 Origin，不接受客户端提供的任意跨域值。

## 测试证据

- V1 Web：8/8 通过。
- 微信小游戏：35/35 通过。
- ELF2 运行契约：4/4 通过。
- Cloudflare Worker：TypeScript 检查及 Wrangler dry-run 通过。
- V1 Web 生产构建通过。
- 发布后 `https://robot.veyralux.org` 与 `/health` 返回 200；`https://anima.veyralux.org` 不再提供 V1 内容。

## 既有风险（非本次引入）

ELF2 V1 控制服务仍允许不带 Origin 的本地请求，安全性依赖回环监听、Cloudflare VPC 回源和设备令牌。该行为未被本次域名隔离放宽；V2 上线前仍须完成一次性 WebSocket ticket、严格 Origin、连接限流与用户对象授权。

## 覆盖限制

- 已验证 Cloudflare 实际路由结果和 HTTP 健康响应；未在本次域名变更中重启或修改 ELF2 上的 V1 服务。
- `anima.veyralux.org` 目前只是 V2 预留域，不代表 V2 已达到发布门槛。
