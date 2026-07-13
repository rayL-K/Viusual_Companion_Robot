import { selectStrawberryRabbitBodyArea } from "./StrawberryRabbitHitAreas";
import type { AnimaBodyArea, AvatarHitTestPort, BrowserPoint } from "./types";

type HitTestModel = {
  hitTest: (x: number, y: number) => string[];
};

type MutablePoint = { x: number; y: number };

type HitTestRenderer = {
  screen?: { width: number; height: number };
  plugins?: {
    interaction?: {
      mapPositionToPoint: (point: MutablePoint, clientX: number, clientY: number) => void;
    };
  };
};

export class Live2DHitTestPort implements AvatarHitTestPort {
  constructor(
    private readonly model: HitTestModel,
    private readonly renderer: HitTestRenderer,
    private readonly canvas: HTMLCanvasElement,
  ) {}

  hitTest(point: BrowserPoint): AnimaBodyArea | null {
    const world = this.toRendererPoint(point);
    return selectStrawberryRabbitBodyArea(this.model.hitTest(world.x, world.y));
  }

  private toRendererPoint(point: BrowserPoint): MutablePoint {
    const mapped = { x: 0, y: 0 };
    const interaction = this.renderer.plugins?.interaction;
    if (interaction) {
      interaction.mapPositionToPoint(mapped, point.clientX, point.clientY);
      return mapped;
    }

    const rect = this.canvas.getBoundingClientRect();
    const width = Math.max(rect.width, 1);
    const height = Math.max(rect.height, 1);
    return {
      x: (point.clientX - rect.left) / width * (this.renderer.screen?.width ?? width),
      y: (point.clientY - rect.top) / height * (this.renderer.screen?.height ?? height),
    };
  }
}
