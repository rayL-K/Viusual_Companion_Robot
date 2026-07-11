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
        aria-label={props.microphoneEnabled ? "关闭麦克风" : "打开麦克风"}
      >
        <span>{props.microphoneEnabled ? "⌁" : "×"}</span><small>麦克风</small>
      </button>
      <button
        type="button"
        class={props.cameraEnabled ? "" : "is-off"}
        onClick={props.onToggleCamera}
        aria-label={props.cameraEnabled ? "关闭摄像头" : "打开摄像头"}
      >
        <span>{props.cameraEnabled ? "▣" : "×"}</span><small>摄像头</small>
      </button>
      <button type="button" class="call-controls__end" onClick={props.onEnd} aria-label="结束通话">
        <span>⌒</span><small>结束</small>
      </button>
    </nav>
  );
}
