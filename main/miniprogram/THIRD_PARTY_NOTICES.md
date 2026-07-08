# 第三方组件

## pixi-miniprogram

- 来源：https://github.com/skyfish-qc/pixi-miniprogram
- 固定提交：`d82bbfa135293ebaa41ed9f4aa23960d8e6c8d04`
- 许可证：MIT，原文位于 `libs/pixi-miniprogram.LICENSE`
- 使用文件：Pixi 小程序适配器、Cubism 4 适配层和 `pixi-live2d-display` 小程序构建。

## Live2D Cubism Core

- 来源：Live2D 官方托管版本 `https://cubism.live2d.com/sdk-web/cubismcore/live2dcubismcore.min.js`
- 核心版本：5.1.0（支持 MocVersion 5）
- 许可证：文件头所列 Live2D Proprietary Software License Agreement
- 本地适配：文件末尾仅追加 CommonJS 导出，以供微信小程序 `require()` 使用。

这些文件作为供应商代码保存；业务代码不得直接修改。升级时必须重新核对来源、许可证、Moc 兼容性，并完成微信开发者工具与真机回归。
