# Visual Companion Robot 微信小游戏

该目录是 ELF2/RK3588 陪伴机器人的微信小游戏交互层（为保留历史路径，目录名仍为 `miniprogram`）。模型推理、记忆、ASR、TTS 和 FER+ 继续运行在开发板；小游戏负责 Canvas Live2D、麦克风、播放、文字交互和运行状态展示。默认通过 `https://robot.veyralux.org` 连接 Cloudflare Tunnel，因此手机只要联网即可使用。

交互层使用 `game.js + game.json` 入口、单屏 WebGL Live2D 舞台、固定四宫格工具 Dock 和 Canvas 功能面板。全面屏安全区、按钮居中、面板遮挡与模型/聊天气泡隔离均在布局层统一计算。Live2D 使用 Cubism Core 5.1.0，并持续写入模型说明中 `Ctrl+Shift` 水印热键对应的 `Param261 = 1`，因此水印默认关闭且不会被动作重新打开。

## 开发模式

1. 在微信开发者工具中导入本目录。
2. 工程使用正式小游戏 AppID `wx8b9c56c00cb5c9ec`。
3. 在小游戏后台把 `https://robot.veyralux.org` 加入服务器合法域名。
4. 公网模式无需填写令牌：Cloudflare Worker 使用服务端 Secret 向 ELF2 代签，令牌不会进入小游戏包。
5. 公网不可用时可切换“局域网调试”，直接连接 ELF2 有线或 Wi-Fi 地址；此模式可按板端配置携带设备令牌。

## 如何在微信中打开

当前 `0.3.1` 是已上传的开发版，不是已经发布的线上版本，因此无法通过微信搜索找到。入口会先用原生 WebGL 提交首帧，并补齐部分微信真机缺少的 `Intl` 全局，再加载 Pixi/Cubism/Live2D；连续视觉建立后复用同源 WSS，连接失败时才回退 HTTPS。v1 中残留的局域网配置会在首次启动时恢复为公网模式，避免离开原 Wi-Fi 后 ELF2 与模型资源同时离线。
开发者或已添加的体验成员应点击微信开发者工具顶部“预览”，或执行：

```powershell
New-Item -ItemType Directory -Force "$PWD\..\..\output\wechat" | Out-Null
& 'C:\Program Files (x86)\Tencent\微信web开发者工具\cli.bat' preview `
  --project "$PWD" `
  --qr-format image `
  --qr-output "$PWD\..\..\output\wechat\visual-companion-game-preview.png"
```

使用微信扫描生成的二维码即可打开当前工作区构建。二维码只用于开发预览；可公开搜索前仍需在小游戏后台
配置合法域名、隐私声明和服务类目，完成真机权限验收，并提交审核与发布。

## 自动化检查

```powershell
cd main/miniprogram
npm run check
npm test
```

正式发布前还需配置合法域名，并完成小游戏基本资料、服务类目、隐私声明和录音权限审核。
