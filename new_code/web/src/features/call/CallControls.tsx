type CallControlsProps = {
  cameraEnabled: boolean;
  microphoneEnabled: boolean;
  onToggleCamera: () => void;
  onToggleMicrophone: () => void;
  onEnd: () => void;
};

export function CallControls(props: CallControlsProps) {
  return (
    <nav class="call-controls" aria-label="通话控制">
      <button
        type="button"
        class={props.microphoneEnabled ? "" : "is-off"}
        onClick={props.onToggleMicrophone}
        aria-pressed={props.microphoneEnabled}
        aria-label={props.microphoneEnabled ? "关闭麦克风" : "打开麦克风"}
      >
        <ControlIcon kind="microphone" disabled={!props.microphoneEnabled} />
        <small>麦克风</small>
      </button>
      <button
        type="button"
        class={props.cameraEnabled ? "" : "is-off"}
        onClick={props.onToggleCamera}
        aria-pressed={props.cameraEnabled}
        aria-label={props.cameraEnabled ? "关闭摄像头" : "打开摄像头"}
      >
        <ControlIcon kind="camera" disabled={!props.cameraEnabled} />
        <small>摄像头</small>
      </button>
      <button type="button" class="call-controls__end" onClick={props.onEnd} aria-label="结束通话">
        <ControlIcon kind="hangup" />
        <small>结束</small>
      </button>
    </nav>
  );
}

type ControlIconProps = {
  kind: "microphone" | "camera" | "hangup";
  disabled?: boolean;
};

function ControlIcon({ kind, disabled = false }: ControlIconProps) {
  return (
    <span class="call-controls__icon" aria-hidden="true">
      <svg viewBox="0 0 24 24" focusable="false">
        {kind === "microphone" && (
          <>
            <rect x="8" y="3" width="8" height="12" rx="4" />
            <path d="M5.5 11.5a6.5 6.5 0 0 0 13 0M12 18v3M8.5 21h7" />
          </>
        )}
        {kind === "camera" && (
          <>
            <rect x="3" y="6" width="13" height="12" rx="3" />
            <path d="m16 10 5-3v10l-5-3Z" />
          </>
        )}
        {kind === "hangup" && <path d="M4 15.5c4.6-3.8 11.4-3.8 16 0l-2.4 3-3-2v-2.1a11 11 0 0 0-5.2 0v2.1l-3 2Z" />}
        {disabled && <path class="call-controls__slash" d="M4 4 20 20" />}
      </svg>
    </span>
  );
}
