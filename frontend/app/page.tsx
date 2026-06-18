"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { api, ApiError, Dashboard, Job, User, WorkflowRecord } from "@/lib/api";
import JobDrawer from "@/components/JobDrawer";
import PruneModal from "@/components/PruneModal";

type StatusFilter = "pending" | "missing_env" | "marked_delete" | "removed";

const STATUS_FILTERS: [StatusFilter, string][] = [
  ["pending", "Pending"],
  ["missing_env", "Missing env"],
  ["marked_delete", "Marked delete"],
  ["removed", "Removed"],
];

const ENV_TAGS = ["prod", "dev", "test"];

function matchesStatus(r: WorkflowRecord, f: StatusFilter): boolean {
  switch (f) {
    case "pending":
      return r.live_in_dify && !r.informations_added;
    case "missing_env":
      return r.live_in_dify && r.missing_env_tag;
    case "marked_delete":
      return r.live_in_dify && r.decision.trim().toLowerCase() === "delete";
    case "removed":
      return r.removed_from_dify;
  }
}

function envBadges(tags: string) {
  const tokens = tags
    .split(",")
    .map((t) => t.trim().toLowerCase())
    .filter(Boolean);
  return ENV_TAGS.filter((e) => tokens.includes(e));
}

export default function DashboardPage() {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [data, setData] = useState<Dashboard | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState<Set<StatusFilter>>(new Set());

  function toggleFilter(f: StatusFilter) {
    setActive((prev) => {
      const next = new Set(prev);
      if (next.has(f)) next.delete(f);
      else next.add(f);
      return next;
    });
  }
  const [activeJob, setActiveJob] = useState<string | null>(null);
  const [showPrune, setShowPrune] = useState(false);
  const [busy, setBusy] = useState(false);

  const loadData = useCallback(async () => {
    setRefreshing(true);
    try {
      setData(await api.workflows());
      setError(null);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        router.push("/login");
        return;
      }
      setError(err instanceof Error ? err.message : "Failed to load");
    } finally {
      setRefreshing(false);
      setLoading(false);
    }
  }, [router]);

  useEffect(() => {
    (async () => {
      try {
        setUser(await api.me());
      } catch {
        router.push("/login");
        return;
      }
      await loadData();
    })();
  }, [router, loadData]);

  const onJobFinished = useCallback(
    (job: Job) => {
      if (["sync", "tags", "prune", "export"].includes(job.type)) loadData();
    },
    [loadData]
  );

  async function startJob(type: "sync" | "tags" | "export") {
    setBusy(true);
    try {
      const job = await api.startJob(type);
      setActiveJob(job.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start job");
    } finally {
      setBusy(false);
    }
  }

  async function startPrune(confirm: boolean) {
    setBusy(true);
    setShowPrune(false);
    try {
      const job = await api.startPrune(confirm);
      setActiveJob(job.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start prune");
    } finally {
      setBusy(false);
    }
  }

  async function logout() {
    await api.logout();
    router.push("/login");
  }

  const records = data?.records ?? [];
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return records.filter((r) => {
      if (q && !`${r.name} ${r.author} ${r.tags}`.toLowerCase().includes(q)) return false;
      // No filters selected: show everything still live in Dify (removed are
      // available via the Removed chip).
      if (active.size === 0) return !r.removed_from_dify;
      // Otherwise show the union of the selected filters.
      for (const f of active) if (matchesStatus(r, f)) return true;
      return false;
    });
  }, [records, query, active]);

  const s = data?.summary;

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center text-slate-400">Loading…</div>
    );
  }

  return (
    <div className="min-h-screen">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-4">
          <div>
            <h1 className="text-lg font-semibold text-slate-900">Dify Workflow Console</h1>
            {data && (
              <p className="text-xs text-slate-500">
                {data.dify_host} · synced {data.synced_at} ·{" "}
                <a
                  href={data.tracker_url}
                  target="_blank"
                  rel="noreferrer"
                  className="text-brand hover:underline"
                >
                  Confluence tracker
                </a>
              </p>
            )}
          </div>
          <div className="flex items-center gap-3 text-sm">
            <span className="text-slate-600">
              {user?.name}{" "}
              <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-500">
                {user?.role}
              </span>
            </span>
            <button onClick={logout} className="text-slate-500 hover:text-slate-800">
              Sign out
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-6 py-6">
        {error && (
          <div className="mb-4 rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>
        )}

        {/* Summary cards */}
        {s && (
          <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
            <Card label="Live in Dify" value={s.live} />
            <Card label="Pending info" value={s.pending} accent="amber" />
            <Card label="Missing env tag" value={s.missing_env_tag} accent="amber" />
            <Card label="Marked delete" value={s.marked_delete} accent="red" />
            <Card label="New (untracked)" value={s.new} accent="blue" />
            <Card label="Removed" value={s.removed_from_dify} />
          </div>
        )}

        {/* Actions */}
        <div className="mb-5 flex flex-wrap items-center gap-2">
          <ActionButton onClick={() => startJob("sync")} disabled={busy}>
            Sync tracker
          </ActionButton>
          <ActionButton onClick={() => startJob("tags")} disabled={busy}>
            Sync env tags
          </ActionButton>
          <ActionButton onClick={() => startJob("export")} disabled={busy}>
            Export YAML
          </ActionButton>
          <button
            onClick={() => setShowPrune(true)}
            disabled={busy || !user?.is_admin}
            title={user?.is_admin ? "Delete workflows marked Delete" : "Requires admin role"}
            className="rounded-lg border border-red-300 bg-red-50 px-3 py-2 text-sm font-medium text-red-700 transition hover:bg-red-100 disabled:cursor-not-allowed disabled:opacity-50"
          >
            Prune…
          </button>
          <button
            onClick={loadData}
            disabled={refreshing}
            className="ml-auto rounded-lg px-3 py-2 text-sm text-slate-500 hover:text-slate-800"
          >
            {refreshing ? "Refreshing…" : "↻ Refresh"}
          </button>
        </div>

        {/* Filters */}
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search name, author, tag…"
            className="w-64 rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
          />
          <button
            onClick={() => setActive(new Set())}
            className={`rounded-full px-3 py-1 text-sm transition ${
              active.size === 0
                ? "bg-brand text-white"
                : "bg-white text-slate-600 ring-1 ring-slate-200 hover:bg-slate-50"
            }`}
          >
            All
          </button>
          {STATUS_FILTERS.map(([f, label]) => (
            <button
              key={f}
              onClick={() => toggleFilter(f)}
              className={`rounded-full px-3 py-1 text-sm transition ${
                active.has(f)
                  ? "bg-brand text-white"
                  : "bg-white text-slate-600 ring-1 ring-slate-200 hover:bg-slate-50"
              }`}
            >
              {label}
            </button>
          ))}
          <span className="ml-auto text-sm text-slate-400">{filtered.length} shown</span>
        </div>

        {/* Table */}
        <div className="overflow-hidden rounded-xl border border-slate-200 bg-white">
          <table className="w-full text-left text-sm">
            <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-4 py-3">Workflow</th>
                <th className="px-4 py-3">Author</th>
                <th className="px-4 py-3">Env</th>
                <th className="px-4 py-3">Decision</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {filtered.map((r) => (
                <Row key={r.app_id} r={r} />
              ))}
              {filtered.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-4 py-10 text-center text-slate-400">
                    No workflows match.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </main>

      <JobDrawer jobId={activeJob} onClose={() => setActiveJob(null)} onFinished={onJobFinished} />
      {showPrune && (
        <PruneModal
          markedCount={s?.marked_delete ?? 0}
          onPreview={() => startPrune(false)}
          onConfirm={() => startPrune(true)}
          onClose={() => setShowPrune(false)}
        />
      )}
    </div>
  );
}

function Card({
  label,
  value,
  accent,
}: {
  label: string;
  value: number;
  accent?: "amber" | "red" | "blue";
}) {
  const accentClass =
    accent === "amber"
      ? "text-amber-600"
      : accent === "red"
        ? "text-red-600"
        : accent === "blue"
          ? "text-blue-600"
          : "text-slate-900";
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4">
      <p className="text-xs text-slate-500">{label}</p>
      <p className={`mt-1 text-2xl font-semibold ${accentClass}`}>{value}</p>
    </div>
  );
}

function ActionButton({
  children,
  onClick,
  disabled,
}: {
  children: React.ReactNode;
  onClick: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className="rounded-lg bg-brand px-3 py-2 text-sm font-medium text-white transition hover:bg-brand-dark disabled:opacity-50"
    >
      {children}
    </button>
  );
}

function Row({ r }: { r: WorkflowRecord }) {
  const envs = envBadges(r.tags);
  return (
    <tr className="hover:bg-slate-50">
      <td className="px-4 py-3">
        <div className="font-medium text-slate-800">{r.name}</div>
        {r.source === "new" && (
          <span className="text-xs text-blue-600">new — not yet on tracker</span>
        )}
      </td>
      <td className="px-4 py-3 text-slate-600">{r.author || <span className="text-slate-300">—</span>}</td>
      <td className="px-4 py-3">
        {envs.length ? (
          <div className="flex gap-1">
            {envs.map((e) => (
              <span key={e} className="rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-600">
                {e}
              </span>
            ))}
          </div>
        ) : (
          <span className="rounded bg-amber-50 px-1.5 py-0.5 text-xs text-amber-700">missing</span>
        )}
      </td>
      <td className="px-4 py-3">
        {r.decision ? (
          <span
            className={`rounded px-1.5 py-0.5 text-xs ${
              r.decision.trim().toLowerCase() === "delete"
                ? "bg-red-50 text-red-700"
                : "bg-slate-100 text-slate-600"
            }`}
          >
            {r.decision}
          </span>
        ) : (
          <span className="text-slate-300">—</span>
        )}
      </td>
      <td className="px-4 py-3">
        {r.removed_from_dify ? (
          <span className="rounded bg-red-50 px-1.5 py-0.5 text-xs text-red-700">removed</span>
        ) : r.informations_added ? (
          <span className="rounded bg-green-50 px-1.5 py-0.5 text-xs text-green-700">done</span>
        ) : (
          <span className="rounded bg-amber-50 px-1.5 py-0.5 text-xs text-amber-700">pending</span>
        )}
      </td>
      <td className="px-4 py-3 text-right">
        {r.url && (
          <a href={r.url} target="_blank" rel="noreferrer" className="text-brand hover:underline">
            Open
          </a>
        )}
      </td>
    </tr>
  );
}
