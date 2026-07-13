import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { fireEvent, render, screen } from "@testing-library/preact";
import { describe, expect, it } from "vitest";

import { App } from "./App";

describe("VeyraLux brand site", () => {
  it("renders the brand promise and both product entry points", () => {
    render(<App />);

    expect(screen.getByRole("heading", { level: 1, name: /让陪伴/ })).toBeTruthy();
    expect(screen.getAllByRole("link", { name: /进入 V1/ })[0]?.getAttribute("href")).toBe(
      "https://robot.veyralux.org",
    );
    expect(screen.queryByRole("link", { name: /探索 V2/ })).toBeNull();
    expect(screen.getByLabelText("Anima V2 尚未公开")).toBeTruthy();
  });

  it("provides keyboard-first navigation and descriptive product imagery", () => {
    render(<App />);

    expect(screen.getByRole("link", { name: "跳到主要内容" }).getAttribute("href")).toBe("#main-content");
    expect(screen.getByRole("navigation", { name: "主要导航" })).toBeTruthy();
    expect(screen.getByAltText(/ELF 2.*开发板/)).toBeTruthy();
    expect(screen.getByAltText(/Anima V2/)).toBeTruthy();
    expect(screen.getByText(/王文康/)).toBeTruthy();
    expect(screen.getAllByRole("link", { name: /GitHub/ })[0]?.getAttribute("href")).toContain("github.com");
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
