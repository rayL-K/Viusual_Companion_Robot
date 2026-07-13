import type { ComponentChildren } from "preact";

type ExternalLinkProps = {
  href: string;
  class?: string;
  children: ComponentChildren;
  ariaLabel?: string;
};

export function ExternalLink({ href, class: className, children, ariaLabel }: ExternalLinkProps) {
  return (
    <a
      class={className}
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      aria-label={ariaLabel}
    >
      {children}
      {!ariaLabel && <span class="sr-only">（在新窗口打开）</span>}
    </a>
  );
}
