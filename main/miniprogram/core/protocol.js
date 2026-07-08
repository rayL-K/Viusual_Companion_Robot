const DEFAULT_SPEECH_RATE = 1.12;

function clamp(value, minValue, maxValue) {
  const number = Number(value);
  return Number.isFinite(number) ? Math.max(minValue, Math.min(maxValue, number)) : minValue;
}

function normalizeAction(action, knownActions) {
  if (!action || typeof action !== "object") {
    return null;
  }
  const name = String(action.name || action.expression || action.motion || "");
  if (!knownActions.has(name)) {
    return null;
  }
  const mode = ["hold", "pulse", "off"].includes(action.mode) ? action.mode : "pulse";
  return {
    name,
    mode,
    durationMs: clamp(Number(action.durationMs || action.duration_ms || 2600), 300, 10000),
    delayMs: clamp(Number(action.delayMs || action.delay_ms || 0), 0, 30000),
  };
}

function normalizePlan(plan, actions) {
  const knownActions = new Set(actions.map((action) => action.name));
  return {
    text: String(plan?.text || "主人，草莓兔兔已经准备好啦。").slice(0, 2000),
    emotion: String(plan?.emotion || "neutral"),
    expression: plan?.expression ? String(plan.expression) : "",
    motion: plan?.motion ? String(plan.motion) : "",
    actions: Array.isArray(plan?.actions)
      ? plan.actions.map((action) => normalizeAction(action, knownActions)).filter(Boolean)
      : [],
    speech: {
      voice: String(plan?.speech?.voice || "female_zh"),
      rate: clamp(Number(plan?.speech?.rate || DEFAULT_SPEECH_RATE), 0.85, 1.35),
      pitch: clamp(Number(plan?.speech?.pitch || 1.15), 0.8, 1.4),
    },
    parameters: plan?.parameters && typeof plan.parameters === "object" ? plan.parameters : {},
  };
}

module.exports = {
  DEFAULT_SPEECH_RATE,
  clamp,
  normalizeAction,
  normalizePlan,
};
