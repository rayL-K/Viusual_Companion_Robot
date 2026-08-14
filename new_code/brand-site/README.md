# VeyraLux 品牌站

独立的 VeyraLux 微睿霖光品牌介绍站，围绕 **Anima v0.0.1** 展示 API-first 的低时延多模态虚拟陪伴架构：浏览器负责交互与呈现，通用 Linux Server 承载实时编排，语音、语言、记忆等能力通过可替换 Provider 接入。站点桌面端优先，并提供移动端、低高度横屏、弱动效与省流模式适配；品牌站本身不承载产品 API。

## 入口边界

- **品牌站：** [`https://veyralux.org`](https://veyralux.org)，由独立 Static Assets Worker 精确绑定 apex hostname。
- **Anima：** `https://anima.veyralux.org` 为 Anima v0.0.1 的预留产品域；完成生产、鉴权与公网验收前，品牌站不会生成可点击的产品入口。
- **隔离原则：** `wrangler.jsonc` 不使用通配符，品牌站不会接管其他子域，也不会混入产品后端路由、Provider 凭据或运行时配置。

## 本地运行

```bash
npm ci
npm run dev
```

## 验证

```bash
npm run typecheck
npm test
npm run build
npm run deploy:dry-run
npm run qa:motion
```

`deploy:dry-run` 只验证 Cloudflare Workers Static Assets 包，不会部署。动效契约测试默认访问 `http://127.0.0.1:4173`，可通过 `BASE_URL` 与 `CHROME_PATH` 环境变量覆盖。

## 技术与结构

- Vite + Preact + TypeScript
- GSAP + ScrollTrigger 驱动连续章节叙事，不使用 `scroll-snap` 或滚动劫持
- Canvas 2D 全局光场与 Signal Spine 贯穿页面；滚动、指针和章节状态共享同一视觉语言
- 架构章节使用纯 HTML / CSS 拓扑表达 Browser、通用 Linux 运行时与 Provider 边界，不依赖设备照片
- 移动端降低粒子与 DPR，低高度横屏取消长 Sticky；`prefers-reduced-motion` 与 Save-Data 自动降级
- 章节自然滚动、键盘可达、跳过导航、清晰焦点与语义化页面结构
- Cloudflare Workers Static Assets 预配置；未知路径返回真实 404，不启用 SPA fallback

主要实现按章节拆分在 `src/sections/`，通用品牌组件在 `src/components/`，动效生命周期集中于 `src/hooks/useBrandMotion.ts` 与 `src/hooks/useLivingField.ts`。

## 产品叙事边界

- ASR、LLM 与 TTS 以可替换 Provider 描述，避免把产品锁定到某一家上游服务。
- 记忆 / RAG、用户与 Anima 数据隔离属于服务端编排边界，不由品牌站执行。
- 视觉保留 Provider / sidecar 接口，但目前仍在接入阶段；站点不会宣称云端视觉已经上线。

## 素材来源

- `public/images/anima-console.webp`：仓库内 Anima v0.0.1 桌面端开发截图
- `public/THIRD_PARTY_NOTICES.txt`：Preact、Manrope 与 GSAP 的版权和许可证声明

团队：王文康、夏鑫祥。
