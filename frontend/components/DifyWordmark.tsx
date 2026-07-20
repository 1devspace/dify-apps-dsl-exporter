import { D_PATH, DIFY_BLUE, DIFY_INK, DIFY_VIEWBOX, F_PATH, I_DOT_PATH, Y_PATH } from "./dify-glyphs";

type Variant = "dify" | "if";

export function DifyWordmark({ className, variant = "dify" }: { className?: string; variant?: Variant }) {
  if (variant === "if") {
    return (
      <svg viewBox="14 0 22 18" className={className} aria-hidden>
        <path fill={DIFY_BLUE} d={I_DOT_PATH} />
        <path fill={DIFY_BLUE} d={F_PATH} />
      </svg>
    );
  }

  return (
    <svg viewBox={DIFY_VIEWBOX} className={className} aria-hidden>
      <path fillRule="evenodd" fill={DIFY_INK} d={D_PATH} />
      <path fill={DIFY_BLUE} d={I_DOT_PATH} />
      <path fill={DIFY_BLUE} d={F_PATH} />
      <path fill={DIFY_INK} d={Y_PATH} />
    </svg>
  );
}
