export const SITE_LINKS = {
  v1: "https://robot.veyralux.org",
  v2: "https://anima.veyralux.org",
  github: "https://github.com/rayL-K/Viusual_Companion_Robot",
} as const;

// V2 的域名已预留，但在实际公开验收通过前不向访客提供可点击入口。
export const V2_PUBLIC = false;

export const NAV_ITEMS = [
  { id: "vision", label: "愿景" },
  { id: "pipeline", label: "实时链路" },
  { id: "architecture", label: "边云协同" },
  { id: "products", label: "V1 / V2" },
] as const;

export type SectionId = "top" | (typeof NAV_ITEMS)[number]["id"];
