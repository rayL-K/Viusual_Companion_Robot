# Anima v0.0.1：ELF2 / Linux Server 安全部署

ELF2（Ubuntu 22.04 aarch64 / RK3588）目前作为 Anima 的边缘实时服务器：浏览器只承担 Live2D、摄像头预览和音频采集；语音、视觉语义、对话、记忆、TTS 与同源 Web 入口都运行在板端。公网入口固定为 `https://anima.veyralux.org`，由专用 Cloudflare Tunnel 回源到 `127.0.0.1:8875`。

本文将**一次性的 root 控制面安装**与**日常 release 发布**分开。日常发布绝不会从 release、`source` 或用户可写目录安装/替换 systemd unit。

`/v2/health`、`/v2/realtime` 中的 `v2` 仅为 wire protocol 版本；产品名为 **Anima v0.0.1**。

## 1. 不变量与目录边界

| 路径 / 单元 | 所有者与用途 | 可写者 |
| --- | --- | --- |
| `/home/wenkang/anima/source` | 日常发布输入；只允许白名单运行时制品 | `wenkang` |
| `/home/wenkang/anima/releases/<id>` | root 创建、SHA-256 清单校验后的不可变 release | root |
| `/home/wenkang/anima/current`、`candidate` | root 原子切换的符号链接 | root |
| `/home/wenkang/anima/.venv`、`models` | 共享运行时/模型，只读 bind mount 到服务沙箱 | root |
| `/opt/anima-control`、`/usr/local/sbin/anima-deploy` | root 受信控制面 | root |
| `/etc/anima` | 生产密钥、candidate 空密钥配置、Tunnel token | root |
| `/var/lib/anima` | active 用户数据和记忆库 | `anima-gateway` |
| `/var/lib/anima-candidate` | candidate 独立临时数据 | `anima-candidate` |
| `/var/lib/anima-deploy` | root-only 健康/回滚状态 | root |

系统仅管理 `anima.service`、`anima-candidate.service` 与 `anima-cloudflared.service`，不会停止或改写旧项目服务。

安全门：

1. 日常发布以 `flock` 串行化；同一时间仅允许一个 stage/health/activate/rollback。
2. stage 只复制 `backend/src`、`backend/pyproject.toml`、`web/dist`、`config/persona.md`；拒绝链接、设备、FIFO、socket 和权限/所有者异常的 release。
3. candidate 只绑定 `127.0.0.1:8876`，使用独立 UID、数据根和空的 LLM/Turnstile/HMAC 值；它不读取生产密钥或 `/var/lib/anima`。
4. health 除了检查 unit 的 `MainPID` 实际监听 loopback 端口，还验证 `/v2/health.releaseDigest` 等于候选 release 的 `.release.sha256` 哈希，防止被另一进程伪造健康结果。
5. active 仅在 candidate 通过后原子替换 `current`；active 健康后才启动 Tunnel。失败会恢复上一已验证 release。
6. systemd 的 `EnvironmentFile` 不得定义 host、端口、路径、准入、origin 或 `PYTHONPATH` 等保留键；这些安全不变量由 `ExecStart=/usr/bin/env …` 最后强制设置。

## 2. 板端前置条件

- Ubuntu 22.04 / systemd、Python 3.10–3.12、`curl`、`sha256sum`、`flock`、`cloudflared`。
- `/home/wenkang/anima/models` 已有匹配 aarch64 的 Sherpa ASR/TTS 模型。
- 可访问所选 LLM API；公网使用 Cloudflare remote-config Tunnel。
- 候选健康门默认要求 `MemAvailable >= 1800 MiB`。空间或内存不足时 fail-closed，不会为发布自动停掉其他服务。

运行时虚拟环境固定为 `/home/wenkang/anima/.venv`，必须在板端构建并归 root 所有：

```bash
sudo python3 -m venv /home/wenkang/anima/.venv
sudo /home/wenkang/anima/.venv/bin/python -m pip install --upgrade pip
sudo /home/wenkang/anima/.venv/bin/python -m pip install \
  '/home/wenkang/anima/source/backend[gateway,models]'
sudo chown -R root:root /home/wenkang/anima/.venv
sudo chmod -R go-w /home/wenkang/anima/.venv
```

不要使用裸 `sudo pip`：它可能写入系统 Python，而 systemd 实际运行的是上述共享 venv。安装器和日常发布器都会显式导入 `fastapi`、`httpx`、`numpy`、`sherpa_onnx`、`uvicorn`、`websockets.exceptions`，并确认模块来自共享 venv、Uvicorn 含 `websockets-sansio`，残缺运行时会在启动 candidate 前 fail-closed。

依赖升级是单独维护动作：先用 candidate 验证新旧 release 兼容，再更新共享 venv；代码 rollback 不会自动回滚依赖。生产打包应固定已验收的 aarch64 wheelhouse 与 SHA-256 清单，不能在日常发布时联网解析宽范围依赖。

## 3. 构建并上传日常发布输入

本机先通过完整检查并构建前端：

```powershell
cd E:\CODE\Visual_Companion_Robot\new_code
./scripts/check.ps1
cd web
npm ci
npm run check
npm run build
```

上传时只同步白名单输入到板端的 `source`，不要上传 `.venv`、模型、密钥、数据、`node_modules`、Git 元数据或任意 release：

```bash
# 在本机执行；按实际 SSH alias 调整。
rsync -a --delete \
  --include='/backend/' --include='/backend/src/***' --include='/backend/pyproject.toml' \
  --include='/web/' --include='/web/dist/***' \
  --include='/config/' --include='/config/persona.md' \
  --exclude='*' \
  /path/to/Visual_Companion_Robot/new_code/ anima-elf2:/home/wenkang/anima/source/
```

发布器会再次校验类型、链接、权限、SHA-256 与 release 所有者；上面的 `rsync` 只是方便，不是安全边界。

## 4. 仅首次或控制面升级时：受信安装

从已审阅的工作树/签名制品执行一次。这个命令**显式**安装 root-owned 控制脚本和三个 systemd unit；后续普通 deploy 不会做此事：

```bash
# 首次可先上传完整 new_code 到 source，且 models 已放在 /home/wenkang/anima/models。
ssh -t anima-elf2 'sudo bash /home/wenkang/anima/source/deploy/install-control-plane.sh'
```

安装器会：创建 `anima-gateway`、`anima-candidate`、`anima-tunnel` 三个无登录服务用户；建立 root-owned 控制面与目录；将共享 venv 收紧为 root-owned、group/other 不可写；将模型目录/文件规范化为 root-owned 的 `0755/0644`，使隔离 UID 只能读取和遍历；执行运行时导入预检；安装空配置模板；执行 `systemctl daemon-reload`。它不会启动公网服务、不会填写密钥、不会迁移或删除用户数据。

如果以后需要修改 systemd hardening 或发布器本身，重复这一**受信安装**步骤；不要通过 release 更新 unit。

## 5. 生产配置、Tunnel 与数据

### 5.1 配置

```bash
sudoedit /etc/anima/anima.env
sudoedit /etc/anima/anima-candidate.env
sudo install -m 600 -o root -g root /dev/null /etc/anima/tunnel-token
sudoedit /etc/anima/tunnel-token
```

`/etc/anima/anima.env` 以仓库 `deploy/anima.env.example` 为模板。至少填写：

- `ANIMA_LLM_API_KEY`
- `ANIMA_ADMISSION_SECRET`（独立、至少 32 字节随机 ASCII）
- `ANIMA_TELEMETRY_HMAC_KEY`（独立、至少 32 字节随机 ASCII）
- `ANIMA_TURNSTILE_SITE_KEY` 与 `ANIMA_TURNSTILE_SECRET`
- 实际的 `ANIMA_ASR_MODEL_DIR`、`ANIMA_TTS_MODEL_DIR`（服务内均应为 `/opt/anima/models/...`）

生产 env 不得定义 `ANIMA_HOST`、`ANIMA_PORT`、`ANIMA_WEB_DIST`、`ANIMA_DATA_ROOT`、`ANIMA_MEMORY_PATH`、`ANIMA_PERSONA_PATH`、`ANIMA_ADMISSION_REQUIRED`、`ANIMA_ALLOWED_ORIGINS` 或 `PYTHONPATH`。发布器会拒绝此类覆盖。

candidate env 不放任何生产 API key、Turnstile key/secret、admission/HMAC secret 或生产路径。候选单元强制 `ANIMA_ADMISSION_REQUIRED=false`，因为它只在 loopback 上用于运行时/模型健康门。

Tunnel token 只写入 `/etc/anima/tunnel-token`（root:root，0600）。`anima-cloudflared.service` 使用 systemd `LoadCredential=` 将其临时投递到 `/run/credentials/anima-cloudflared.service/anima-token`，再由独立的 `anima-tunnel` 进程通过 `--token-file` 读取；兼容 ELF2 的 systemd 249，token 不在进程参数、日志或 release 中。发布器要求 Tunnel 连续通过多次进程存活检查，不会把短暂的 `activating` 状态误判为已上线。remote-config Tunnel 已配置 ingress 时不要添加 `--url` 覆盖控制面规则。

### 5.2 旧数据迁移

发布器不会静默复制、删除或降级旧数据。首次迁移前：停止明确的旧写入进程；对 SQLite 执行 WAL checkpoint 和 `PRAGMA quick_check`；先做一致性备份；再把目标数据库恢复到 `/var/lib/anima/memory/anima.db`，并执行：

```bash
sudo chown -R anima-gateway:anima-gateway /var/lib/anima
sudo chmod -R go-rwx /var/lib/anima
```

在 candidate 的独立数据根做抽样恢复验证后，再开放 active。保留原始只读备份直到长时运行验收完成。

## 6. 日常一键发布、启动与回滚

控制面安装并完成配置后，唯一日常入口是 root-owned launcher：

```bash
# 一条命令：stage -> candidate:8876 health -> atomic activate -> active:8875 -> Tunnel
ssh -t anima-elf2 'sudo /usr/local/sbin/anima-deploy deploy 20260724T120000Z'

# 已激活版本的一键启动/重启
ssh -t anima-elf2 'sudo /usr/local/sbin/anima-deploy start'

# 状态、分步发布、回滚
ssh -t anima-elf2 'sudo /usr/local/sbin/anima-deploy status'
ssh -t anima-elf2 'sudo /usr/local/sbin/anima-deploy stage 20260724T120000Z'
ssh -t anima-elf2 'sudo /usr/local/sbin/anima-deploy health'
ssh -t anima-elf2 'sudo /usr/local/sbin/anima-deploy activate'
ssh -t anima-elf2 'sudo /usr/local/sbin/anima-deploy rollback'
```

release id 只能是最长 64 位的字母、数字、`.`、`_`、`-`。同名 release 绝不覆盖。不要直接运行 `/home/wenkang/anima/source/scripts/start-elf2.sh`：它不是 root 受信入口，设计上会拒绝。

如果管理员选择配置无密码 sudo，只允许固定命令 `/usr/local/sbin/anima-deploy`，不要授予 source 目录、shell、`systemctl` 或通配编辑权限。

## 7. 验收与故障定位

```bash
sudo /usr/local/sbin/anima-deploy status
sudo systemctl status anima.service anima-candidate.service anima-cloudflared.service --no-pager
curl -fsS http://127.0.0.1:8875/v2/health
sudo journalctl -u anima.service -u anima-cloudflared.service -n 120 --no-pager
```

`/v2/health` 是启动/路由/release 身份门，不替代真人验收。每次模型或依赖变更后至少验证：连续 ASR partial/final 与打断；LLM 首段与取消；中英混合 TTS 首音频；视觉预览 60 FPS 与 5 秒语义刷新解耦；视觉语义真实进入每轮上下文；真实 Live2D 模型、口型与身体交互；PC、平板、移动浏览器的 HTTPS/WSS、摄像头和麦克风权限；以及 8 小时 CPU/NPU/RSS/温度/断网重连。

## 8. 迁移到低端 Linux Server

该边界可直接迁移：新主机按目标 ABI 重建 root-owned `.venv` 和模型，恢复独立的 `/var/lib/anima` 一致快照，用 candidate 健康门和模态验收后，将同一个 `anima.veyralux.org` 专用 Tunnel 切换到新主机。客户端、Live2D 协议和用户数据布局无需感知底层是 RK3588 还是 x86_64。
