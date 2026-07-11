import { effect, type Signal } from "@preact/signals";
import { useEffect, useRef, useState } from "preact/hooks";

import { phaseLabel, speechAudioRms, type ReplyPhase } from "../../core/state/session";
import { Live2DStageController } from "./Live2DStageController";

type AvatarStageProps = {
  phase: Signal<ReplyPhase>;
};

export function AvatarStage({ phase }: AvatarStageProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const hostRef = useRef<HTMLDivElement>(null);
  const controllerRef = useRef<Live2DStageController | null>(null);
  const [stageState, setStageState] = useState<"loading" | "ready" | "fallback">("loading");

  useEffect(() => {
    if (!canvasRef.current || !hostRef.current) return;
    let mounted = true;
    const controller = new Live2DStageController(canvasRef.current, hostRef.current);
    controllerRef.current = controller;
    controller.setPhase(phase.value);
    void controller.start().then(
      () => { if (mounted) setStageState("ready"); },
      (error: unknown) => {
        if (!mounted) return;
        console.error("Live2D 舞台加载失败，已保留轻量回退角色", error);
        setStageState("fallback");
      },
    );
    return () => {
      mounted = false;
      controller.destroy();
      controllerRef.current = null;
    };
  }, []);

  useEffect(() => controllerRef.current?.setPhase(phase.value), [phase.value]);

  useEffect(() => effect(() => controllerRef.current?.setAudioRms(speechAudioRms.value)), []);

  return (
    <section class="avatar-stage" aria-label="Live2D 角色舞台">
      <div class="stage-light stage-light--one" />
      <div class="stage-light stage-light--two" />
      <div ref={hostRef} class={`presence presence--${stageState}`} data-phase={phase.value}>
        <div class="presence__halo" />
        {stageState !== "ready" && (
          <div class="presence__core" aria-hidden="true">
            <span class="presence__eye presence__eye--left" />
            <span class="presence__eye presence__eye--right" />
            <span class="presence__smile" />
          </div>
        )}
        <canvas ref={canvasRef} id="live2d-canvas" class="live2d-canvas" />
      </div>
      <p class="stage-presence-label"><span />{phaseLabel(phase.value)}</p>
    </section>
  );
}
