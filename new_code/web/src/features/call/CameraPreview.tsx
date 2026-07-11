import type { RefObject } from "preact";

type CameraPreviewProps = {
  videoRef: RefObject<HTMLVideoElement>;
  visible: boolean;
  cameraEnabled: boolean;
};

export function CameraPreview({ videoRef, visible, cameraEnabled }: CameraPreviewProps) {
  return (
    <section class={`camera-pip ${visible ? "camera-pip--visible" : ""}`} aria-label="本机摄像头预览">
      <video ref={videoRef} autoPlay muted playsInline />
      {!cameraEnabled && <div class="camera-pip__off">摄像头已关闭</div>}
      <div class="camera-pip__label"><i />你</div>
    </section>
  );
}
