"use client";

import { useEffect, useRef, useState } from "react";
import { api, Job } from "@/lib/api";

const STATUS_STYLES: Record<Job["status"], string> = {
  queued: "bg-slate-100 text-slate-600",
  running: "bg-blue-100 text-blue-700",
  success: "bg-green-100 text-green-700",
  error: "bg-red-100 text-red-700",
};

export default function JobDrawer({
  jobId,
  onClose,
  onFinished,
}: {
  jobId: string | null;
  onClose: () => void;
  onFinished?: (job: Job) => void;
}) {
  const [job, setJob] = useState<Job | null>(null);
  const logEndRef = useRef<HTMLDivElement>(null);
  const finishedNotified = useRef(false);

  useEffect(() => {
    if (!jobId) return;
    setJob(null);
    finishedNotified.current = false;
    let active = true;

    async function poll() {
      try {
        const j = await api.job(jobId!);
        if (!active) return;
        setJob(j);
        if (j.status === "success" || j.status === "error") {
          if (!finishedNotified.current) {
            finishedNotified.current = true;
            onFinished?.(j);
          }
          return; // stop polling
        }
      } catch {
        /* keep trying */
      }
      if (active) setTimeout(poll, 800);
    }
    poll();
    return () => {
      active = false;
    };
  }, [jobId, onFinished]);

  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [job?.log?.length]);

  if (!jobId) return null;

  return (
    <div className="fixed inset-0 z-40 flex justify-end">
      <div className="absolute inset-0 bg-slate-900/30" onClick={onClose} />
      <div className="relative z-10 flex h-full w-full max-w-xl flex-col bg-white shadow-2xl">
        <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4">
          <div className="flex items-center gap-3">
            <h2 className="text-base font-semibold capitalize">{job?.type || "Job"}</h2>
            {job && (
              <span
                className={`rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_STYLES[job.status]}`}
              >
                {job.status}
              </span>
            )}
          </div>
          <button
            onClick={onClose}
            className="rounded-md p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
          >
            ✕
          </button>
        </div>
        <div className="flex-1 overflow-auto bg-slate-950 px-4 py-3 font-mono text-xs text-slate-200">
          {!job && <p className="text-slate-400">Starting…</p>}
          {job?.log?.length === 0 && job.status === "running" && (
            <p className="text-slate-400">Running…</p>
          )}
          {job?.log?.map((line, i) => (
            <div key={i} className="whitespace-pre-wrap leading-relaxed">
              {line}
            </div>
          ))}
          {job?.error && <div className="mt-2 text-red-400">Error: {job.error}</div>}
          <div ref={logEndRef} />
        </div>
        {job && (job.status === "success" || job.status === "error") && job.result != null && (
          <div className="max-h-48 overflow-auto border-t border-slate-200 bg-slate-50 px-4 py-3">
            <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
              Result
            </p>
            <pre className="whitespace-pre-wrap text-xs text-slate-700">
              {JSON.stringify(job.result, null, 2)}
            </pre>
          </div>
        )}
      </div>
    </div>
  );
}
