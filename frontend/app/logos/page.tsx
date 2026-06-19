import type { ReactNode } from "react";
import BrandLockup from "@/components/BrandLockup";
import LogoMark from "@/components/LogoMark";
import { DifyWordmark } from "@/components/DifyWordmark";

const VARIANTS: { id: string; name: string; note: string; C: (p: { className?: string }) => ReactNode }[] = [
  {
    id: "lockup",
    name: "Dify + Console (header)",
    note: "Real Dify wordmark + “Console” in brand blue. Used in header & login.",
    C: ({ className }) => <BrandLockup size="lg" className={className} />,
  },
  {
    id: "if-blue",
    name: "Favicon — blue “if”",
    note: "Cropped from Dify’s logo (the blue letters). Default tab icon.",
    C: ({ className }) => <LogoMark variant="if-blue" className={className} />,
  },
  {
    id: "if-white",
    name: "Favicon — white tile",
    note: "Same “if” crop on white.",
    C: ({ className }) => <LogoMark variant="if-white" className={className} />,
  },
  {
    id: "dot",
    name: "Favicon — i dot",
    note: "Minimal: Dify’s rounded-square dot on blue.",
    C: ({ className }) => <LogoMark variant="dot-blue" className={className} />,
  },
  {
    id: "dify",
    name: "Dify wordmark (reference)",
    note: "Exact copy from dify/logo.svg.",
    C: ({ className }) => <DifyWordmark className={className} />,
  },
];

export default function LogoGallery() {
  return (
    <div className="mx-auto max-w-5xl px-6 py-10">
      <h1 className="text-xl font-semibold text-slate-900">Branding</h1>
      <p className="mt-2 max-w-2xl text-sm leading-relaxed text-slate-600">
        Dify&apos;s logo is a <strong>horizontal wordmark</strong>, not letters stuffed in a square.
        We stopped inventing a “DC” monogram. Header uses the real Dify logo + “Console”; the tab
        icon crops the blue <strong>if</strong> from their SVG.
      </p>

      <div className="mt-8 space-y-5">
        {VARIANTS.map(({ id, name, note, C }) => (
          <div
            key={id}
            className="flex flex-wrap items-center gap-8 rounded-xl border border-slate-200 bg-white p-6 shadow-card"
          >
            <div className="w-56 shrink-0">
              <p className="text-sm font-semibold text-slate-800">{name}</p>
              <p className="mt-0.5 text-xs text-slate-400">id: {id}</p>
              <p className="mt-2 text-xs leading-relaxed text-slate-500">{note}</p>
            </div>
            <C className={id === "lockup" ? "" : "h-16 w-16"} />
            {id !== "lockup" && (
              <>
                <C className="h-10 w-10" />
                <C className="h-4 w-4" />
              </>
            )}
          </div>
        ))}
      </div>

      <p className="mt-8 text-sm text-slate-500">
        Pick a favicon id (<code className="rounded bg-slate-100 px-1">if-blue</code>,{" "}
        <code className="rounded bg-slate-100 px-1">if-white</code>,{" "}
        <code className="rounded bg-slate-100 px-1">dot</code>) or share a reference image.
      </p>
    </div>
  );
}
