export const SITE_LINKS = {
  anima: "https://anima.veyralux.org",
  github: "https://github.com/rayL-K/Viusual_Companion_Robot",
} as const;

// Anima 的域名已预留；公开入口只在实际验收通过后启用。
export const ANIMA_PUBLIC = false;

export const NAV_ITEMS = [
  { id: "vision", label: "愿景" },
  { id: "pipeline", label: "实时链路" },
  { id: "architecture", label: "边云协同" },
  { id: "products", label: "Anima v0.0.1" },
] as const;

export type SectionId = "top" | (typeof NAV_ITEMS)[number]["id"];
