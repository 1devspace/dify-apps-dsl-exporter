import { F_PATH, I_DOT_PATH, DIFY_BLUE } from "./dify-glyphs";

type Variant = "if-blue" | "if-white" | "dot-blue";

/** Favicon / small mark — cropped from Dify’s real logo (the blue “if”), not invented letters. */
export default function LogoMark({
  className,
  variant = "if-blue",
}: {
  className?: string;
  variant?: Variant;
}) {
  if (variant === "dot-blue") {
    return (
      <svg viewBox="0 0 32 32" aria-hidden className={className}>
        <rect width="32" height="32" rx="8.5" fill={DIFY_BLUE} />
        <circle cx="16" cy="16" r="5.5" fill="#fff" />
      </svg>
    );
  }

  const tile = variant === "if-blue" ? DIFY_BLUE : "#fff";
  const ink = variant === "if-blue" ? "#fff" : DIFY_BLUE;

  return (
    <svg viewBox="0 0 32 32" aria-hidden className={className}>
      <rect width="32" height="32" rx="8.5" fill={tile} />
      <g transform="translate(5.2 7.4) scale(0.92)">
        <svg viewBox="14 0 22 18" width="21.6" height="17.6">
          <path fill={ink} d={I_DOT_PATH} />
          <path fill={ink} d={F_PATH} />
        </svg>
      </g>
    </svg>
  );
}
