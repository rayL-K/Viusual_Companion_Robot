# 通用服务器部署预检

这是 Anima 的默认部署预检，面向 **Ubuntu 22.04/24.04 x86_64 或 aarch64 Server**，不依赖特定开发板的目录或用户名。

```bash
chmod +x deploy/portable/portable-preflight.sh
deploy/portable/portable-preflight.sh \
  --source /srv/anima/release-input \
  --profile gateway
```

它只做本地只读检查，不会安装包、读取 `/etc/anima/*.env`、读取 Cloudflare Token 或调用任何云 API。具体迁移顺序见 [`../../docs/portable-server-migration.md`](../../docs/portable-server-migration.md)。

`gateway` profile 不要求本地模型，可组合 DeepSeek LLM 与 OpenAI-compatible ASR/TTS；`speech`、`asr`、`perception` profile 逐级增加 sherpa TTS、sherpa streaming ASR 和 loopback `local-vlm` 的本地资产预检。脚本只验证所选 profile 的本地前置条件，不读取或探测云端密钥与 Provider。
