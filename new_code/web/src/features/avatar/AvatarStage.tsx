import type { Signal } from "@preact/signals";

import { phaseLabel, type ReplyPhase } from "../../core/state/session";

type AvatarStageProps = {
  phase: Signal<ReplyPhase>;
};

export function AvatarStage({ phase }: AvatarStageProps) {
  return (
    <section class="avatar-stage" aria-label="Live2D 角色舞台">
      <div class="stage-light stage-light--one" />
      <div class="stage-light stage-light--two" />
      <div class="presence" data-phase={phase.value}>
        <div class="presence__halo" />
        <div class="presence__core" aria-hidden="true">
          <span class="presence__eye presence__eye--left" />
          <span class="presence__eye presence__eye--right" />
          <span class="presence__smile" />
        </div>
        <canvas id="live2d-canvas" class="live2d-canvas" />
      </div>
      <p class="stage-presence-label"><span />{phaseLabel(phase.value)}</p>
    </section>
  );
}
