# Web 端第三方运行库

生产页面固定并从 `anima.veyralux.org/vendor/` 同源提供以下运行库，避免外部 CDN
不可用时出现空白模型：

- Live2D Cubism Core 5.1.0：Live2D 官方托管构建，遵循文件头所列专有许可协议。
- PixiJS 6.5.10：MIT，许可证见 `public/vendor/pixi-6.5.10.LICENSE`。
- pixi-live2d-display 0.4.0：MIT，许可证见
  `public/vendor/pixi-live2d-display-0.4.0.LICENSE`。

供应商文件不得直接修改；升级版本时必须重新执行模型加载、PC、手机竖屏和手机横屏回归。
