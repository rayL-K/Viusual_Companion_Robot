# Cloudflare Tunnel 部署

公网入口统一为 `https://robot.veyralux.org`。Cloudflare Worker 通过 Workers VPC Service 进入 ELF2 的专用 Tunnel，再访问 IPv4 回环地址控制网关；控制网关通过 `127.0.0.1:8766` 调用 FER+，不直接暴露情绪服务或家庭公网 IP。

## 首次创建

```bash
wrangler tunnel create visual-companion-elf2
wrangler vpc service create visual-companion-elf2-api \
  --type http \
  --tunnel-id <TUNNEL_UUID> \
  --ipv4 127.0.0.1 \
  --http-port 8765
```

本项目的 systemd 单元使用远程管理 Tunnel token。把 token 以仅 root 可读的方式保存为 `/etc/cloudflared/token`，然后安装并启动 `visual-companion-cloudflared.service`：

```bash
sudo install -m 600 tunnel-token.txt /etc/cloudflared/token
sudo systemctl enable --now visual-companion-cloudflared
```

服务使用 `--protocol auto`：网络允许时优先 QUIC，手机热点或受限网络阻断 UDP 时可自动回退到 HTTP/2。

`config.yml.example` 保留给需要本地管理凭据文件的部署方式；两种方式不要同时启用。

边缘 Worker 位于 `gateway/`，配置 VPC Service binding 和 `robot.veyralux.org` 自定义域：

```bash
cd tools/cloudflare/gateway
npm ci
npm run check
npm run deploy
```

## 微信侧

在微信公众平台的“开发管理 → 开发设置 → 服务器域名”中，将 `https://robot.veyralux.org` 配置为 `request` 与 `downloadFile` 合法域名。正式版不启用“不校验合法域名”。

## 安全边界

- Tunnel 只建立出站连接，无需路由器端口映射。
- ELF2 的 `/chat`、`/tts`、`/asr`、`/emotion` 等接口仍要求 `X-Device-Token`；Worker 从 `DEVICE_TOKEN` Secret 注入，客户端包和浏览器均不持有令牌。
- 通过 `wrangler secret put DEVICE_TOKEN` 配置边缘凭据；不要把令牌写入 `wrangler.jsonc`、源码或前端存储。
- `/voices` 只返回公开元数据，不返回模型路径、参考音频路径或内部端点。
- FER+ 仅监听 `127.0.0.1:8766`。
