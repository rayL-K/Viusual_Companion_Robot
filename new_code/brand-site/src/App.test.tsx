import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { fireEvent, render, screen } from "@testing-library/preact";
import { describe, expect, it } from "vitest";

import { App } from "./App";

describe("VeyraLux brand site", () => {
  it("renders the Anima v0.0.1 promise without legacy product references", () => {
    const { container } = render(<App />);

    expect(screen.getByRole("heading", { level: 1, name: /让陪伴/ })).toBeTruthy();
    expect(screen.getByRole("link", { name: /认识 Anima · v0\.0\.1/ }).getAttribute("href")).toBe("#products");
    expect(screen.getByLabelText("Anima v0.0.1 尚未公开")).toBeTruthy();
    expect(container.textContent).toContain("VERSION 0.0.1");
  });

  it("provides keyboard-first navigation and descriptive product imagery", () => {
    render(<App />);

    expect(screen.getByRole("link", { name: "跳到主要内容" }).getAttribute("href")).toBe("#main-content");
    expect(screen.getByRole("navigation", { name: "主要导航" })).toBeTruthy();
    expect(screen.getByLabelText("Anima 服务能力边界")).toBeTruthy();
    expect(screen.getAllByText(/视觉 Provider \/ sidecar 接入中/).length).toBeGreaterThan(0);
    expect(screen.getByAltText(/^Anima v0\.0\.1 桌面端/)).toBeTruthy();
    expect(document.querySelector('[data-motion-layer="living-field"]')).toBeTruthy();
    expect(screen.getByText(/王文康/)).toBeTruthy();
    expect(screen.getAllByRole("link", { name: /GitHub/ })[0]?.getAttribute("href")).toContain("github.com");
  });

  it("keeps public copy platform-neutral and explicit about unfinished vision integration", () => {
    const files = [
      "index.html",
      "README.md",
      "src/sections/Hero.tsx",
      "src/sections/Manifesto.tsx",
      "src/sections/Pipeline.tsx",
      "src/sections/Architecture.tsx",
      "src/sections/Products.tsx",
      "src/components/SiteFooter.tsx",
      "src/site-config.ts",
    ];
    const publicCopy = files
      .map((file) => readFileSync(resolve(process.cwd(), file), "utf8"))
      .join("\n");

    expect(publicCopy).toContain("视觉 Provider / sidecar 接入中");
    expect(publicCopy).toContain("通用 Linux");
    expect(publicCopy).toContain("Provider 可替换");
  });

  it("keeps every new-window link isolated from the opener", () => {
    const { container } = render(<App />);

    const links = [...container.querySelectorAll<HTMLAnchorElement>('a[target="_blank"]')];
    expect(links.length).toBeGreaterThan(0);
    expect(links.every((link) => link.relList.contains("noopener") && link.relList.contains("noreferrer"))).toBe(true);
  });

  it("closes the compact navigation with Escape", () => {
    render(<App />);

    const toggle = screen.getByRole("button", { name: "打开导航" });
    fireEvent.click(toggle);
    expect(screen.getByRole("button", { name: "关闭导航" }).getAttribute("aria-expanded")).toBe("true");

    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.getByRole("button", { name: "打开导航" }).getAttribute("aria-expanded")).toBe("false");
  });

  it("locks deployment to the exact apex and hardened static headers", () => {
    const config = JSON.parse(readFileSync(resolve(process.cwd(), "wrangler.jsonc"), "utf8"));
    const headers = readFileSync(resolve(process.cwd(), "public/_headers"), "utf8");
    const notices = readFileSync(resolve(process.cwd(), "public/THIRD_PARTY_NOTICES.txt"), "utf8");

    expect(config.workers_dev).toBe(false);
    expect(config.preview_urls).toBe(false);
    expect(config.assets.not_found_handling).toBe("none");
    expect(config.routes).toEqual([{ pattern: "veyralux.org", custom_domain: true }]);
    expect(JSON.stringify(config.routes)).not.toContain("*");
    expect(headers).toContain("frame-ancestors 'none'");
    expect(headers).toContain("base-uri 'none'");
    expect(headers).toContain("Permissions-Policy: camera=(), microphone=(), geolocation=()");
    expect(notices).toContain("Preact 10.29.7");
    expect(notices).toContain("SIL OPEN FONT LICENSE Version 1.1");
    expect(notices).toContain("GSAP 3.15.0");
  });
});
