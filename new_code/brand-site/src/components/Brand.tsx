export function Brand({ footer = false }: { footer?: boolean }) {
  return (
    <span class={`brand ${footer ? "brand--footer" : ""}`}>
      <BrandMark />
      <span class="brand__text">
        <strong>VeyraLux</strong>
        <small>微睿霖光</small>
      </span>
    </span>
  );
}

function BrandMark() {
  return <span class="brand-mark" aria-hidden="true"><i /><b /></span>;
}
