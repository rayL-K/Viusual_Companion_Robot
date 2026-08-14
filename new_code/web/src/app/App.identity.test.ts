import { describe, expect, it } from "vitest";

import type { ServerEvent } from "../core/realtime/protocol";
import {
  connectionLabel,
  mergeReplySegmentText,
  PRODUCT_NAME,
  PRODUCT_VERSION,
  type ReplyTextCursor,
} from "./App";

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

  it("renders streamed text on audio start and deduplicates the legacy event by generation/index", () => {
    const initial: ReplyTextCursor = { sessionId: "s1", generation: -1, nextIndex: 0 };
    const first = mergeReplySegmentText(
      "旧内容",
      initial,
      segmentEvent("reply.segment.started", 4, 0, "你好，"),
    );
    expect(first).toEqual({
      text: "你好，",
      cursor: { sessionId: "s1", generation: 4, nextIndex: 1 },
    });
    if (!first) throw new Error("首段未被接受");

    expect(mergeReplySegmentText(
      first.text,
      first.cursor,
      segmentEvent("reply.segment.ready", 4, 0, "你好，"),
    )).toBeNull();
    expect(mergeReplySegmentText(
      first.text,
      first.cursor,
      segmentEvent("reply.segment.started", 4, 1, "很高兴见到你。"),
    )?.text).toBe("你好，很高兴见到你。");
    expect(mergeReplySegmentText(
      first.text,
      first.cursor,
      segmentEvent("reply.segment.started", 3, 1, "过期"),
    )).toBeNull();
  });
});

function segmentEvent(
  type: "reply.segment.ready" | "reply.segment.started",
  generation: number,
  index: number,
  text: string,
): ServerEvent {
  return {
    v: 2,
    type,
    sessionId: "s1",
    turnId: `t${generation}`,
    generation,
    seq: index + 1,
    sentAtMs: 1,
    payload: { index, text },
  };
}
