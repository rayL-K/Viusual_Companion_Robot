export function SignalPresence() {
  return (
    <div class="hero__signal" aria-hidden="true">
      <div class="signal-presence">
        <span class="signal-presence__orbit signal-presence__orbit--outer" />
        <span class="signal-presence__orbit signal-presence__orbit--middle" />
        <span class="signal-presence__orbit signal-presence__orbit--inner" />
        <span class="signal-presence__axis signal-presence__axis--x" />
        <span class="signal-presence__axis signal-presence__axis--y" />
        <span class="signal-presence__core"><i /><b /></span>
        <span class="signal-presence__label signal-presence__label--vision">VISION</span>
        <span class="signal-presence__label signal-presence__label--speech">SPEECH</span>
        <span class="signal-presence__label signal-presence__label--memory">MEMORY</span>
        <span class="signal-presence__label signal-presence__label--motion">MOTION</span>
      </div>
      <p><span /> 感知与回应正在同一条链路上发生</p>
    </div>
  );
}
