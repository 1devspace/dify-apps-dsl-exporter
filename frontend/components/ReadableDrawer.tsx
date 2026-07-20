"use client";

import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api, ApiError } from "@/lib/api";
import Mermaid from "./Mermaid";

export type ReadableTarget = { app_id: string; name: string };

export default function ReadableDrawer({
  target,
  onClose,
}: {
  target: ReadableTarget | null;
  onClose: () => void;
}) {
  const [markdown, setMarkdown] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!target) return;
    setMarkdown(null);
    setError(null);
    let active = true;
    api
      .readable(target.app_id, target.name)
      .then((r) => active && setMarkdown(r.markdown))
      .catch((e) => active && setError(e instanceof ApiError ? e.message : "Failed to load"));
    return () => {
      active = false;
    };
  }, [target]);

  if (!target) return null;

  return (
    <div className="fixed inset-0 z-40 flex justify-end">
      <div className="absolute inset-0 bg-slate-900/30" onClick={onClose} />
      <div className="relative z-10 flex h-full w-full max-w-3xl flex-col bg-white shadow-2xl">
        <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4">
          <div>
            <h2 className="text-base font-semibold text-slate-900">{target.name}</h2>
            <p className="text-xs text-slate-500">Readable workflow documentation</p>
          </div>
          <button
            onClick={onClose}
            className="rounded-md p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
          >
            ✕
          </button>
        </div>
        <div className="readable flex-1 overflow-auto px-6 py-5">
          {error && <p className="rounded bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
          {!markdown && !error && <p className="text-sm text-slate-400">Generating…</p>}
          {markdown && (
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={{
                pre: ({ children }) => <>{children}</>,
                code({ className, children, ...props }) {
                  const text = String(children).replace(/\n$/, "");
                  if (/language-mermaid/.test(className || "")) {
                    return <Mermaid chart={text} />;
                  }
                  if ((className || "").startsWith("language-")) {
                    return (
                      <pre className="my-3 overflow-auto rounded bg-slate-950 p-3 text-xs text-slate-100">
                        <code className={className} {...props}>
                          {children}
                        </code>
                      </pre>
                    );
                  }
                  return (
                    <code className="rounded bg-slate-100 px-1 py-0.5 text-[0.85em]" {...props}>
                      {children}
                    </code>
                  );
                },
              }}
            >
              {markdown}
            </ReactMarkdown>
          )}
        </div>
      </div>
    </div>
  );
}
