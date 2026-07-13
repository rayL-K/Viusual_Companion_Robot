# VeyraSoul Web 第三方组件声明

本文覆盖 V2 Web 当前生产依赖和随站点分发的 vendor 运行库。版本以本目录 `package-lock.json`、实际 `node_modules` 元数据及 `public/vendor` 文件头为准。仅用于构建和测试且不会进入浏览器制品的工具不在此逐项展开。

## npm 生产依赖

| 组件 | 当前版本 | 来源 | 许可证 | 版权声明 |
| --- | ---: | --- | --- | --- |
| `@use-gesture/vanilla` | 10.3.1 | <https://github.com/pmndrs/use-gesture/tree/main/packages/vanilla> | MIT | Copyright (c) 2018-present Paul Henschel `<drcmda@gmail.com>` |
| `@use-gesture/core` | 10.3.1 | <https://github.com/pmndrs/use-gesture/tree/main/packages/core> | MIT | Copyright (c) 2018-present Paul Henschel `<drcmda@gmail.com>` |
| `preact` | 10.29.7 | <https://github.com/preactjs/preact> | MIT | Copyright (c) 2015-present Jason Miller |
| `@preact/signals` | 2.9.3 | <https://github.com/preactjs/signals/tree/main/packages/preact> | MIT | Copyright (c) 2022-present Preact Team |
| `@preact/signals-core` | 1.14.4 | <https://github.com/preactjs/signals/tree/main/packages/core> | MIT | Copyright (c) 2022-present Preact Team |

`@use-gesture/core` 与 `@preact/signals-core` 是上述直接依赖带入的浏览器运行时依赖。版本和 license 字段已分别与以下实际文件核对：

- `node_modules/@use-gesture/vanilla/package.json` 与 `LICENSE`；
- `node_modules/@use-gesture/core/package.json` 与 `LICENSE`；
- `node_modules/preact/package.json` 与 `LICENSE`；
- `node_modules/@preact/signals/package.json` 与 `LICENSE`；
- `node_modules/@preact/signals-core/package.json` 与 `LICENSE`。

## 随站点分发的 vendor 运行库

### PixiJS 6.5.10

- 文件：`public/vendor/pixi-6.5.10.min.js`
- 来源：<https://github.com/pixijs/pixijs>
- 许可证：MIT
- 版权：Copyright (c) 2013-2017 Mathew Groves, Chad Engler
- 随附原文：`public/vendor/pixi-6.5.10.LICENSE`

### pixi-live2d-display 0.4.0（Cubism 4 构建）

- 文件：`public/vendor/pixi-live2d-display-0.4.0-cubism4.min.js`
- 来源：<https://github.com/guansss/pixi-live2d-display>
- 许可证：MIT
- 版权：Copyright (c) 2020 Guan
- 随附原文：`public/vendor/pixi-live2d-display-0.4.0.LICENSE`

### Live2D Cubism Core 5.1.0

- 文件：`public/vendor/live2dcubismcore.min.js`
- 来源：Live2D 官方 Cubism SDK for Web Redistributable Code
- 文件头版权：Copyright (C) 2019 Live2D Inc. All rights reserved.
- 许可证：Live2D Proprietary Software License Agreement，而非 MIT
- 协议地址：<https://www.live2d.com/eula/live2d-proprietary-software-license-agreement_en.html>

该文件的许可证和再分发条件以 Live2D 协议及文件头为准。PixiJS 或 `pixi-live2d-display` 的 MIT License 不会改变 Cubism Core 的专有许可条件。

## MIT License 原文

以下条款适用于上文明确标注为 MIT 的组件；各组件对应的版权声明保留在上表或 vendor LICENSE 文件中。

```text
Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Live2D 模型与美术资源不属于上述软件授权

`public/live2d/Strawberry_Rabbit` 中的 `.moc3`、纹理、动作、表情和其他美术文件不是因为使用 Cubism Core 或 MIT 运行库就自动取得公开再分发权。当前 `manifest.json` 将其状态标为 `verification-required-before-public-redistribution`。

在将这些模型资源放入公开站点、开源仓库或比赛代码包之前，发布者必须另行核验并保存模型作者/销售方许可。若无可验证授权，必须从公开制品中排除该模型资源，改由部署者提供其合法持有的副本。

## 维护要求

- 升级依赖时同时更新 lockfile、版本表和对应版权/许可证文本；
- 不直接修改 `public/vendor` 压缩文件；需要升级时从可信上游重新取得并核对哈希、文件头和 API 兼容性；
- 生产构建发布前检查所有进入 bundle 或静态目录的第三方文件，不能仅依据 `package.json` 的直接依赖列表；
- 本声明用于保留第三方通知，不替代任何模型购买协议、素材授权或 Live2D 专有许可义务。
