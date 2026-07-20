import { DIFY_BLUE } from "./dify-glyphs";
import { DifyWordmark } from "./DifyWordmark";

type Size = "sm" | "md" | "lg";

const SIZES: Record<Size, { mark: string; label: string }> = {
  sm: { mark: "h-[18px]", label: "text-[17px]" },
  md: { mark: "h-[22px]", label: "text-[21px]" },
  lg: { mark: "h-[28px]", label: "text-[26px]" },
};

/** Header lockup: real Dify wordmark + “Console” in brand blue. */
export default function BrandLockup({
  className,
  size = "md",
}: {
  className?: string;
  size?: Size;
}) {
  const s = SIZES[size];
  return (
    <div className={`flex items-center gap-[0.45rem] ${className ?? ""}`}>
      <DifyWordmark className={`${s.mark} w-auto shrink-0`} />
      <span
        className={`${s.label} font-bold leading-none tracking-[-0.03em]`}
        style={{ color: DIFY_BLUE }}
      >
        Console
      </span>
    </div>
  );
}
