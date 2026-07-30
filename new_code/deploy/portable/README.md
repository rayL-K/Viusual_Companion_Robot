# 通用服务器部署预检

这是 Anima 的默认部署预检，面向 **Ubuntu 22.04/24.04 x86_64 或 aarch64 Server**，不依赖 ELF2 的目录或用户名。

```bash
chmod +x deploy/portable/portable-preflight.sh
deploy/portable/portable-preflight.sh \
  --source /srv/anima/release-input \
  --tts-model /srv/anima/models/tts/matcha-zh-baker \
  --profile speech
```

它只做本地只读检查，不会安装包、读取 `/etc/anima/*.env`、读取 Cloudflare Token 或调用任何云 API。具体迁移顺序见 [`../../docs/portable-server-migration.md`](../../docs/portable-server-migration.md)。

当前代码可真实组合的 Provider 只有：DeepSeek 云端 LLM、sherpa-onnx 本地 TTS、可选 sherpa-onnx streaming ASR、可选独立部署且 loopback 可访问的 `local-vlm`。脚本不会把尚未实现的云 ASR、云 TTS、云 VLM 当成可用功能。
