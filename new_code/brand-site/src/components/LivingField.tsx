import { useLivingField } from "../hooks/useLivingField";

export interface LivingFieldProps {
  className?: string;
  intensity?: number;
  maxDpr?: number;
}

/**
 * A non-interactive, viewport-sized visual layer. Render it once near the top
 * of the site root; it never intercepts pointer, keyboard, or assistive input.
 */
export function LivingField({
  className,
  intensity = 1,
  maxDpr = 1.75,
}: LivingFieldProps) {
  const canvasRef = useLivingField({ intensity, maxDpr });

  return (
    <canvas
      ref={canvasRef}
      class={className}
      aria-hidden="true"
      data-motion-layer="living-field"
      data-motion-behavior="ambient"
      data-motion-scope="global"
      style={{
        position: "fixed",
        zIndex: 0,
        inset: 0,
        display: "block",
        width: "100%",
        height: "100%",
        contain: "strict",
        pointerEvents: "none",
        opacity: 0.82,
      }}
    />
  );
}
