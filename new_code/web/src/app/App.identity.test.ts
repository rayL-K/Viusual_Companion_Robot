import { describe, expect, it } from "vitest";

import { connectionLabel, PRODUCT_NAME, PRODUCT_VERSION } from "./App";

describe("Anima product identity", () => {
  it("uses productized service-node connection labels", () => {
    expect(connectionLabel("connecting")).toBe("正在接入服务节点");
    expect(connectionLabel("online")).toBe("服务节点已连接");
    expect(connectionLabel("offline")).toBe("服务节点暂不可用");
    expect(connectionLabel("error")).toBe("服务节点连接异常");
  });

  it("exports the canonical product identity used by the shell", () => {
    expect(PRODUCT_NAME).toBe("Anima");
    expect(PRODUCT_VERSION).toBe("v0.0.1");
  });
});
