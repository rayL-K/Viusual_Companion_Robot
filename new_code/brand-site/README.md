# VeyraLux 品牌站

独立的 VeyraLux 微睿霖光品牌介绍站，桌面端优先并适配移动端。站点用于说明低时延多模态虚拟陪伴、RK3588 边云协同架构，以及 V1 与 V2 的演进关系，不承载推理 API。

## 入口边界

- **V1 / Robot：** [`https://robot.veyralux.org`](https://robot.veyralux.org) 为当前公开、可用的产品入口。
- **V2 / Anima：** `https://anima.veyralux.org` 是 V2 预留域。品牌站只显示开发状态，在 V2 完成实机、鉴权和公网验收前不会生成可点击主入口。
- **品牌站域名：** 本目录以独立 Static Assets Worker 精确绑定 `veyralux.org`。Custom Domain 只匹配 apex hostname，不会接管 `robot` 或 `anima`。

仓库现有 V1 Cloudflare Gateway 位于 `tools/cloudflare/gateway/`，负责产品流量和板端回源，不能与本品牌站的纯静态 Worker 混用。

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
```

`deploy:dry-run` 只验证 Cloudflare Workers Static Assets 包，不会部署。`wrangler.jsonc` 只包含精确的 `veyralux.org` Custom Domain，禁止使用通配符或复用 V1 Gateway。

## 技术与结构

- Vite + Preact + TypeScript
- GSAP + ScrollTrigger；移动端关闭重视差，系统设置 `prefers-reduced-motion` 时停用编排动画
- 章节自然滚动、键盘可达、跳过导航、清晰焦点与语义化页面结构
- Cloudflare Workers Static Assets 预配置；未知路径返回真实 404，不启用 SPA fallback

主要实现按章节拆分在 `src/sections/`，通用品牌组件在 `src/components/`，动画生命周期集中于 `src/hooks/useBrandMotion.ts`。

## 素材来源

- `public/images/elf2-board.webp`：项目实拍 ELF 2 / RK3588 开发板
- `public/images/anima-console.webp`：仓库内 Anima V2 桌面端开发截图
- `public/THIRD_PARTY_NOTICES.txt`：Preact、Manrope 与 GSAP 的版权和许可证声明

团队：王文康、夏鑫祥。
