"use client";

import { useState } from "react";

export default function PruneModal({
  markedCount,
  onPreview,
  onConfirm,
  onClose,
}: {
  markedCount: number;
  onPreview: () => void;
  onConfirm: () => void;
  onClose: () => void;
}) {
  const [typed, setTyped] = useState("");
  const armed = typed.trim().toUpperCase() === "DELETE";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center px-4">
      <div className="absolute inset-0 bg-slate-900/40" onClick={onClose} />
      <div className="relative z-10 w-full max-w-md rounded-2xl bg-white p-6 shadow-2xl">
        <h2 className="text-lg font-semibold text-slate-900">Prune workflows</h2>
        <p className="mt-2 text-sm text-slate-600">
          This deletes every workflow marked <span className="font-medium">Delete</span> in the
          tracker from Dify, archives a local YAML backup, flags the tracker rows, and notifies
          Slack.
        </p>
        <p className="mt-2 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-800">
          {markedCount} workflow{markedCount === 1 ? "" : "s"} currently marked{" "}
          <span className="font-medium">Delete</span>.
        </p>

        <button
          onClick={onPreview}
          className="mt-4 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50"
        >
          Preview (dry run) — no changes
        </button>

        <div className="mt-5 border-t border-slate-200 pt-4">
          <label className="mb-1 block text-sm font-medium text-slate-700">
            Type <span className="font-mono">DELETE</span> to enable deletion
          </label>
          <input
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-red-500 focus:outline-none focus:ring-1 focus:ring-red-500"
            placeholder="DELETE"
          />
          <div className="mt-4 flex gap-2">
            <button
              onClick={onClose}
              className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-600 hover:bg-slate-50"
            >
              Cancel
            </button>
            <button
              onClick={onConfirm}
              disabled={!armed}
              className="flex-1 rounded-lg bg-red-600 px-3 py-2 text-sm font-medium text-white transition hover:bg-red-700 disabled:opacity-40"
            >
              Delete now
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
