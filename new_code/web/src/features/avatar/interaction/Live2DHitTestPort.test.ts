import { describe, expect, it, vi } from "vitest";

import { Live2DHitTestPort } from "./Live2DHitTestPort";

describe("Live2DHitTestPort", () => {
  it("uses the renderer interaction mapper and applies hit-area priority", () => {
    const hitTest = vi.fn(() => ["Torso", "Face", "HandVisualLeft"]);
    const interaction = {
      offsetX: 100,
      offsetY: 200,
      mapPositionToPoint: vi.fn(function (
        this: { offsetX: number; offsetY: number },
        point: { x: number; y: number },
        clientX: number,
        clientY: number,
      ) {
        point.x = clientX + this.offsetX;
        point.y = clientY + this.offsetY;
      }),
    };
    const getBoundingClientRect = vi.fn();
    const port = new Live2DHitTestPort(
      { hitTest },
      { plugins: { interaction } },
      { getBoundingClientRect } as unknown as HTMLCanvasElement,
    );

    expect(port.hitTest({ clientX: 12, clientY: 34 })).toBe("hand.left");
    expect(interaction.mapPositionToPoint).toHaveBeenCalledWith({ x: 112, y: 234 }, 12, 34);
    expect(hitTest).toHaveBeenCalledWith(112, 234);
    expect(getBoundingClientRect).not.toHaveBeenCalled();
  });

  it("falls back to canvas-to-renderer scaling when no Pixi mapper is available", () => {
    const hitTest = vi.fn(() => ["EarVisualRight", "Face"]);
    const canvas = {
      getBoundingClientRect: () => ({ left: 100, top: 50, width: 200, height: 100 }),
    } as unknown as HTMLCanvasElement;
    const port = new Live2DHitTestPort(hitTestModel(hitTest), { screen: { width: 800, height: 600 } }, canvas);

    expect(port.hitTest({ clientX: 150, clientY: 75 })).toBe("ear.right");
    expect(hitTest).toHaveBeenCalledWith(200, 150);
  });
});

function hitTestModel(hitTest: (x: number, y: number) => string[]) {
  return { hitTest };
}
