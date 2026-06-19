"use client";

import { ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useRouter } from "next/navigation";
import { api, ApiError, Dashboard, Job, User, WorkflowRecord } from "@/lib/api";
import JobDrawer from "@/components/JobDrawer";
import PruneModal from "@/components/PruneModal";
import BrandLockup from "@/components/BrandLockup";
import SettingsPanel from "@/components/SettingsPanel";
import LogoMark from "@/components/LogoMark";

type SortKey = "name" | "author" | "decision" | "status";
type ColKey = "source" | "author" | "env" | "decision" | "status";
type ColFilters = Record<ColKey, Set<string>>;
type Toast = { id: string; message: string; kind: "success" | "error" | "info" };
type Option = { value: string; label: string };

const NONE = "(none)";
const ENV_TAGS = ["prod", "dev", "test"];

const ENV_STYLES: Record<string, string> = {
  prod: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  dev: "bg-sky-50 text-sky-700 ring-sky-200",
  test: "bg-amber-50 text-amber-700 ring-amber-200",
};

function emptyColFilters(): ColFilters {
  return { source: new Set(), author: new Set(), env: new Set(), decision: new Set(), status: new Set() };
}

function anyFilterActive(cf: ColFilters): number {
  return Object.values(cf).reduce((n, s) => n + s.size, 0);
}

function rowStatus(r: WorkflowRecord): "pending" | "done" | "removed" {
  if (r.removed_from_dify) return "removed";
  if (r.informations_added) return "done";
  return "pending";
}

function statusRank(r: WorkflowRecord): number {
  const s = rowStatus(r);
  return s === "removed" ? 2 : s === "done" ? 1 : 0;
}

function rowSource(r: WorkflowRecord): "new" | "tracked" {
  return r.source === "new" ? "new" : "tracked";
}

// Tracker cells sometimes use placeholder text instead of a blank author.
const UNKNOWN_AUTHORS = new Set(["unknown", "unassigned", "n/a", "na", "tbd", "-", "—"]);

function splitAuthors(raw: string | null | undefined): string[] {
  return (raw ?? "")
    .split(",")
    .map((a) => a.trim())
    .filter((a) => a && !UNKNOWN_AUTHORS.has(a.toLowerCase()));
}

function rowAuthors(r: WorkflowRecord): string[] {
  const a = splitAuthors(r.author);
  return a.length ? a : [NONE];
}

function rowDecision(r: WorkflowRecord): string {
  return r.decision?.trim() || NONE;
}

function rowEnvs(r: WorkflowRecord): string[] {
  const e = envBadges(r.tags);
  return e.length ? e : [NONE];
}

function rowMatches(r: WorkflowRecord, cf: ColFilters): boolean {
  if (cf.source.size && !cf.source.has(rowSource(r))) return false;
  if (cf.author.size && !rowAuthors(r).some((a) => cf.author.has(a))) return false;
  if (cf.decision.size && !cf.decision.has(rowDecision(r))) return false;
  if (cf.env.size && !rowEnvs(r).some((e) => cf.env.has(e))) return false;
  if (cf.status.size) {
    if (!cf.status.has(rowStatus(r))) return false;
  } else if (r.removed_from_dify) {
    // No status filter: hide removed by default (choose "removed" to see them).
    return false;
  }
  return true;
}

function relativeTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const secs = Math.round((Date.now() - then) / 1000);
  if (secs < 60) return "just now";
  const mins = Math.round(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.round(hrs / 24)}d ago`;
}

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

// Deterministic, muted pastel color per author. Chips stay quiet (neutral
// slate text on a soft tint); the avatar carries the color accent.
const AUTHOR_COLORS = [
  { chip: "bg-rose-50/60 ring-rose-100", dot: "bg-rose-100 text-rose-600", text: "text-rose-600" },
  { chip: "bg-amber-50/60 ring-amber-100", dot: "bg-amber-100 text-amber-600", text: "text-amber-600" },
  { chip: "bg-emerald-50/60 ring-emerald-100", dot: "bg-emerald-100 text-emerald-600", text: "text-emerald-600" },
  { chip: "bg-sky-50/60 ring-sky-100", dot: "bg-sky-100 text-sky-600", text: "text-sky-600" },
  { chip: "bg-violet-50/60 ring-violet-100", dot: "bg-violet-100 text-violet-600", text: "text-violet-600" },
  { chip: "bg-teal-50/60 ring-teal-100", dot: "bg-teal-100 text-teal-600", text: "text-teal-600" },
  { chip: "bg-indigo-50/60 ring-indigo-100", dot: "bg-indigo-100 text-indigo-600", text: "text-indigo-600" },
  { chip: "bg-cyan-50/60 ring-cyan-100", dot: "bg-cyan-100 text-cyan-600", text: "text-cyan-600" },
  { chip: "bg-stone-100/70 ring-stone-200", dot: "bg-stone-200 text-stone-600", text: "text-stone-600" },
  { chip: "bg-lime-50/60 ring-lime-100", dot: "bg-lime-100 text-lime-700", text: "text-lime-700" },
];

function authorColor(name: string) {
  let hash = 0;
  for (let i = 0; i < name.length; i++) hash = (hash * 31 + name.charCodeAt(i)) >>> 0;
  return AUTHOR_COLORS[hash % AUTHOR_COLORS.length];
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
  const [colFilters, setColFilters] = useState<ColFilters>(emptyColFilters);
  const activeCount = anyFilterActive(colFilters);

  function toggleColFilter(col: ColKey, value: string) {
    setColFilters((prev) => {
      const next: ColFilters = { ...prev, [col]: new Set(prev[col]) };
      if (next[col].has(value)) next[col].delete(value);
      else next[col].add(value);
      return next;
    });
  }

  function clearFilters() {
    setColFilters(emptyColFilters());
  }
  const [sort, setSort] = useState<{ key: SortKey; dir: "asc" | "desc" }>({
    key: "name",
    dir: "asc",
  });

  function toggleSort(key: SortKey) {
    setSort((prev) =>
      prev.key === key ? { key, dir: prev.dir === "asc" ? "desc" : "asc" } : { key, dir: "asc" }
    );
  }
  const [view, setView] = useState<"dashboard" | "operations" | "settings">("dashboard");
  const [collapsed, setCollapsed] = useState(false);
  useEffect(() => {
    setCollapsed(localStorage.getItem("sidebarCollapsed") === "1");
  }, []);
  useEffect(() => {
    localStorage.setItem("sidebarCollapsed", collapsed ? "1" : "0");
  }, [collapsed]);
  const [activeJob, setActiveJob] = useState<string | null>(null);
  const [showPrune, setShowPrune] = useState(false);
  const [busy, setBusy] = useState(false);
  const [docLinks, setDocLinks] = useState<Record<string, string>>({});
  const [docIndexUrl, setDocIndexUrl] = useState<string | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [toasts, setToasts] = useState<Toast[]>([]);

  const pushToast = useCallback((message: string, kind: Toast["kind"] = "info") => {
    const id = Math.random().toString(36).slice(2);
    setToasts((prev) => [...prev, { id, message, kind }]);
    setTimeout(() => setToasts((prev) => prev.filter((t) => t.id !== id)), 5000);
  }, []);

  const loadJobs = useCallback(async () => {
    try {
      const r = await api.jobs();
      setJobs(r.jobs || []);
    } catch {
      /* non-critical */
    }
  }, []);

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

  // Best-effort: which workflows already have a published Confluence doc.
  const loadDocLinks = useCallback(async () => {
    try {
      const dl = await api.docLinks();
      setDocLinks(dl.links || {});
      setDocIndexUrl(dl.index_url);
    } catch {
      /* docs are optional; the menu falls back to generating one */
    }
  }, []);

  useEffect(() => {
    (async () => {
      try {
        setUser(await api.me());
      } catch {
        router.push("/login");
        return;
      }
      await loadData();
      await loadDocLinks();
      await loadJobs();
    })();
  }, [router, loadData, loadDocLinks, loadJobs]);

  const onJobFinished = useCallback(
    (job: Job) => {
      loadJobs();
      pushToast(
        job.status === "success"
          ? `${job.type} finished`
          : `${job.type} failed${job.error ? `: ${job.error}` : ""}`,
        job.status === "success" ? "success" : "error"
      );
      if (job.type === "doc") {
        loadDocLinks();
        return;
      }
      if (["sync", "tags", "prune", "export"].includes(job.type)) loadData();
    },
    [loadData, loadDocLinks, loadJobs, pushToast]
  );

  async function startDoc(appId: string, name: string) {
    try {
      const job = await api.startDoc(appId, name);
      setActiveJob(job.id);
      loadJobs();
    } catch (err) {
      pushToast(err instanceof Error ? err.message : "Failed to start doc job", "error");
    }
  }

  async function startJob(type: "sync" | "tags" | "export") {
    setBusy(true);
    try {
      const job = await api.startJob(type);
      setActiveJob(job.id);
      loadJobs();
    } catch (err) {
      pushToast(err instanceof Error ? err.message : "Failed to start job", "error");
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
      loadJobs();
    } catch (err) {
      pushToast(err instanceof Error ? err.message : "Failed to start prune", "error");
    } finally {
      setBusy(false);
    }
  }

  async function logout() {
    await api.logout();
    router.push("/login");
  }

  const records = data?.records ?? [];

  const options = useMemo(() => {
    const authors = new Set<string>();
    const decisions = new Set<string>();
    const sources = new Set<string>();
    let hasNoAuthor = false;
    let hasNoDecision = false;
    for (const r of records) {
      const names = splitAuthors(r.author);
      if (names.length) names.forEach((n) => authors.add(n));
      else hasNoAuthor = true;
      const d = r.decision?.trim();
      if (d) decisions.add(d);
      else hasNoDecision = true;
      sources.add(rowSource(r));
    }
    const sortStr = (arr: string[]) => arr.sort((a, b) => a.localeCompare(b, undefined, { sensitivity: "base" }));
    const author: Option[] = sortStr([...authors]).map((v) => ({ value: v, label: v }));
    if (hasNoAuthor) author.push({ value: NONE, label: "— none —" });
    const decision: Option[] = sortStr([...decisions]).map((v) => ({ value: v, label: v }));
    if (hasNoDecision) decision.push({ value: NONE, label: "— none —" });
    const source: Option[] = [
      { value: "tracked", label: "Tracked" },
      { value: "new", label: "New" },
    ].filter((o) => sources.has(o.value));
    const env: Option[] = [
      { value: "prod", label: "prod" },
      { value: "dev", label: "dev" },
      { value: "test", label: "test" },
      { value: NONE, label: "— none —" },
    ];
    const status: Option[] = [
      { value: "pending", label: "Pending" },
      { value: "done", label: "Done" },
      { value: "removed", label: "Removed" },
    ];
    return { author, decision, source, env, status };
  }, [records]);

  const deleteVals = useMemo(
    () => options.decision.filter((o) => o.value.toLowerCase() === "delete").map((o) => o.value),
    [options]
  );
  const markedDeleteActive = deleteVals.some((v) => colFilters.decision.has(v));

  function toggleMarkedDelete() {
    setColFilters((prev) => {
      const next: ColFilters = { ...prev, decision: new Set(prev.decision) };
      const on = deleteVals.some((v) => next.decision.has(v));
      for (const v of deleteVals) {
        if (on) next.decision.delete(v);
        else next.decision.add(v);
      }
      return next;
    });
  }

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const out = records.filter((r) => {
      if (q && !`${r.name} ${r.author} ${r.tags}`.toLowerCase().includes(q)) return false;
      return rowMatches(r, colFilters);
    });
    const dir = sort.dir === "asc" ? 1 : -1;
    out.sort((a, b) => {
      let cmp = 0;
      if (sort.key === "status") cmp = statusRank(a) - statusRank(b);
      else {
        const av = (sort.key === "name" ? a.name : sort.key === "author" ? a.author : a.decision) || "";
        const bv = (sort.key === "name" ? b.name : sort.key === "author" ? b.author : b.decision) || "";
        cmp = av.localeCompare(bv, undefined, { sensitivity: "base" });
      }
      return cmp !== 0 ? cmp * dir : a.name.localeCompare(b.name);
    });
    return out;
  }, [records, query, colFilters, sort]);

  const lastRun = useMemo(() => {
    const m: Record<string, Job> = {};
    for (const j of jobs) {
      if (j.status === "success" && !m[j.type]) m[j.type] = j;
    }
    return m;
  }, [jobs]);

  const s = data?.summary;

  if (loading) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-3 text-slate-400">
        <LogoMark className="h-10 w-10 rounded-xl" />
        <div className="flex items-center gap-2 text-sm">
          <RefreshIcon className="h-4 w-4 animate-spin" />
          Loading workspace…
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen bg-slate-50">
      <aside
        className={`sticky top-0 z-30 flex h-screen shrink-0 flex-col border-r border-slate-200 bg-white transition-all duration-200 ${
          collapsed ? "w-16" : "w-56"
        }`}
      >
        <button
          onClick={() => setCollapsed((v) => !v)}
          title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          className="absolute -right-2.5 top-6 z-40 flex h-5 w-5 items-center justify-center rounded-full bg-white text-slate-300 ring-1 ring-slate-200/70 transition hover:text-slate-600 hover:ring-slate-300"
        >
          <ChevronDownIcon className={`h-3 w-3 ${collapsed ? "-rotate-90" : "rotate-90"}`} />
        </button>
        <div className={`flex h-14 items-center ${collapsed ? "justify-center px-2" : "px-4"}`}>
          {collapsed ? <DifyMark className="h-6 w-6" /> : <BrandLockup size="sm" />}
        </div>
        <nav className={`flex-1 space-y-1 py-3 ${collapsed ? "px-2" : "px-3"}`}>
          <SideItem
            icon={<GridIcon className="h-4 w-4" />}
            label="Dashboard"
            collapsed={collapsed}
            active={view === "dashboard"}
            onClick={() => setView("dashboard")}
          />
          <SideItem
            icon={<BoltIcon className="h-4 w-4" />}
            label="Operations"
            collapsed={collapsed}
            active={view === "operations"}
            onClick={() => setView("operations")}
          />
          {user?.is_admin && (
            <SideItem
              icon={<GearIcon className="h-4 w-4" />}
              label="Settings"
              collapsed={collapsed}
              active={view === "settings"}
              onClick={() => setView("settings")}
            />
          )}
        </nav>
        {data && (
          <div className={collapsed ? "px-2 pb-2" : "px-3 pb-2"}>
            <div
              title={collapsed ? `Synced ${data.synced_at}` : undefined}
              className={`flex items-center gap-2.5 rounded-lg py-1.5 text-[11px] font-medium text-slate-500 ${
                collapsed ? "justify-center px-0" : "px-3"
              }`}
            >
              <span className="text-slate-400">
                <ClockIcon className="h-3.5 w-3.5" />
              </span>
              {!collapsed && (
                <span className="flex items-baseline gap-1.5">
                  <span className="text-slate-400">Synced</span>
                  <span className="tabular-nums text-slate-600">{data.synced_at}</span>
                </span>
              )}
            </div>
          </div>
        )}
        <div className={`border-t border-slate-100 p-3 ${collapsed ? "flex flex-col items-center" : ""}`}>
          {collapsed ? (
            <>
              <span
                title={user?.name}
                className="flex h-8 w-8 items-center justify-center rounded-full bg-brand-600 text-[10px] font-semibold text-white"
              >
                {initials(user?.name || "?")}
              </span>
              <button
                onClick={logout}
                title="Sign out"
                className="mt-2 rounded-lg p-2 text-slate-400 transition hover:bg-slate-100 hover:text-slate-800"
              >
                <LogoutIcon className="h-4 w-4" />
              </button>
            </>
          ) : (
            <>
              <div className="flex items-center gap-2 px-1 py-1">
                <span className="flex h-7 w-7 items-center justify-center rounded-full bg-brand-600 text-[10px] font-semibold text-white">
                  {initials(user?.name || "?")}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-xs font-medium text-slate-700">{user?.name}</p>
                  {user?.role && (
                    <p className="truncate text-[10px] uppercase tracking-wide text-slate-400">
                      {user.role}
                    </p>
                  )}
                </div>
              </div>
              <button
                onClick={logout}
                className="mt-1 w-full rounded-lg px-3 py-1.5 text-left text-xs font-medium text-slate-500 transition hover:bg-slate-100 hover:text-slate-800"
              >
                Sign out
              </button>
            </>
          )}
        </div>
      </aside>

      <div className="flex min-h-screen flex-1 flex-col">
        <header className="sticky top-0 z-20 flex h-14 items-center justify-between gap-4 border-b border-slate-200/80 bg-white/80 px-6 backdrop-blur">
          <h1 className="text-sm font-semibold capitalize text-slate-800">{view}</h1>
          <div className="flex items-center gap-3">
            {data && (
              <span className="hidden items-center gap-1.5 text-xs font-medium text-slate-600 md:inline-flex">
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
                {data.dify_host.replace(/^https?:\/\//, "")}
              </span>
            )}
            <LinksMenu trackerUrl={data?.tracker_url} docIndexUrl={docIndexUrl} />
          </div>
        </header>

        <main className="mx-auto w-full max-w-7xl flex-1 px-6 py-6">
          {error && (
          <div className="mb-4 rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>
        )}

        {view === "dashboard" && (
          <>
        {/* Filter cards (click to filter; multi-select) */}
        {s && (
          <div className="mb-5 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
            <StatCard
              label="Live in Dify"
              value={s.live}
              active={activeCount === 0}
              onClick={clearFilters}
              hint="Active workflows in Dify"
            />
            <StatCard
              label="Pending info"
              value={s.pending}
              accent="amber"
              active={colFilters.status.has("pending")}
              onClick={() => toggleColFilter("status", "pending")}
              hint="Tracker row not completed yet"
            />
            <StatCard
              label="Missing env"
              value={s.missing_env_tag}
              accent="amber"
              active={colFilters.env.has(NONE)}
              onClick={() => toggleColFilter("env", NONE)}
              hint="No prod / dev / test tag"
            />
            <StatCard
              label="Marked delete"
              value={s.marked_delete}
              accent="red"
              active={markedDeleteActive}
              onClick={toggleMarkedDelete}
              hint="Decision set to Delete"
            />
            <StatCard
              label="New (untracked)"
              value={s.new}
              accent="blue"
              active={colFilters.source.has("new")}
              onClick={() => toggleColFilter("source", "new")}
              hint="In Dify, not yet on the tracker"
            />
            <StatCard
              label="Removed"
              value={s.removed_from_dify}
              active={colFilters.status.has("removed")}
              onClick={() => toggleColFilter("status", "removed")}
              hint="On tracker, gone from Dify"
            />
          </div>
        )}

        {/* Search / refresh (column filters live in the table headers) */}
        <div className="mb-3 flex items-center gap-2">
          <div className="relative">
            <SearchIcon className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search…"
              className="w-72 rounded-lg border border-transparent bg-slate-100 py-2 pl-9 pr-3 text-sm text-slate-700 placeholder:text-slate-400 transition focus:border-brand focus:bg-white focus:outline-none focus:ring-1 focus:ring-brand"
            />
          </div>
          <button
            onClick={loadData}
            disabled={refreshing}
            title="Refresh"
            className="rounded-lg p-2 text-slate-400 transition hover:bg-slate-100 hover:text-slate-700 disabled:opacity-50"
          >
            <RefreshIcon className={`h-4 w-4 ${refreshing ? "animate-spin" : ""}`} />
          </button>
          {activeCount > 0 && (
            <button
              onClick={clearFilters}
              className="rounded-lg px-2.5 py-2 text-xs font-medium text-brand transition hover:bg-brand-50"
            >
              Clear filters ({activeCount})
            </button>
          )}
          <div className="ml-auto flex items-center gap-2 text-xs text-slate-400">
            <span className="hidden sm:inline">Showing</span>
            <span className="rounded-full bg-slate-100 px-2 py-0.5 font-medium tabular-nums text-slate-600">
              {filtered.length}
              <span className="font-normal text-slate-400"> / {records.length}</span>
            </span>
          </div>
        </div>

        {/* Table */}
        <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-card">
          <div className="max-h-[68vh] overflow-auto">
            <table className="w-full text-left text-sm">
              <thead className="sticky top-0 z-10 bg-slate-50/95 text-xs uppercase tracking-wide text-slate-500 backdrop-blur">
                <tr className="border-b border-slate-200">
                  <ColHeader label="Workflow" k="name" sort={sort} onSort={toggleSort} />
                  <ColHeader
                    label="Author"
                    k="author"
                    sort={sort}
                    onSort={toggleSort}
                    options={options.author}
                    selected={colFilters.author}
                    onToggle={(v) => toggleColFilter("author", v)}
                  />
                  <ColHeader
                    label="Env"
                    sort={sort}
                    onSort={toggleSort}
                    options={options.env}
                    selected={colFilters.env}
                    onToggle={(v) => toggleColFilter("env", v)}
                  />
                  <ColHeader
                    label="Decision"
                    k="decision"
                    sort={sort}
                    onSort={toggleSort}
                    options={options.decision}
                    selected={colFilters.decision}
                    onToggle={(v) => toggleColFilter("decision", v)}
                  />
                  <ColHeader
                    label="Status"
                    k="status"
                    sort={sort}
                    onSort={toggleSort}
                    options={options.status}
                    selected={colFilters.status}
                    onToggle={(v) => toggleColFilter("status", v)}
                  />
                  <th className="px-4 py-3"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {filtered.map((r) => (
                  <Row
                    key={r.app_id}
                    r={r}
                    isAdmin={!!user?.is_admin}
                    meName={user?.name || ""}
                    meEmail={user?.email || ""}
                    docUrl={docLinks[r.name]}
                    onGenerate={() => startDoc(r.app_id, r.name)}
                    onChanged={loadData}
                    onToast={pushToast}
                  />
                ))}
                {filtered.length === 0 && (
                  <tr>
                    <td colSpan={6} className="px-4 py-16 text-center">
                      <div className="flex flex-col items-center gap-1 text-slate-400">
                        <SearchIcon className="h-6 w-6 text-slate-300" />
                        <p className="text-sm font-medium text-slate-500">No workflows match</p>
                        <p className="text-xs">Try clearing filters or your search.</p>
                      </div>
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
          </>
        )}

        {view === "operations" && (
          <section className="mx-auto max-w-3xl">
            <div className="mb-4">
              <h2 className="text-lg font-semibold text-slate-800">Operations</h2>
              <p className="text-sm text-slate-500">
                Run governance jobs against Dify and the Confluence tracker. Progress streams live;
                results aren&apos;t kept after a refresh.
              </p>
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <OpCard
                label="Sync tracker"
                desc="Refresh the Confluence tracker from Dify and notify Slack."
                variant="primary"
                disabled={busy}
                lastRun={lastRun["sync"]}
                onClick={() => startJob("sync")}
              />
              <OpCard
                label="Sync env tags"
                desc="Push prod / dev / test tags from the tracker into Dify."
                disabled={busy}
                lastRun={lastRun["tags"]}
                onClick={() => startJob("tags")}
              />
              <OpCard
                label="Export YAML"
                desc={
                  user?.is_admin
                    ? "Download every workflow's DSL to the local export folder (admin only)."
                    : "Requires an admin / owner Dify role."
                }
                disabled={busy || !user?.is_admin}
                lastRun={lastRun["export"]}
                onClick={() => startJob("export")}
              />
              <OpCard
                label="Prune deleted"
                desc={
                  user?.is_admin
                    ? "Delete workflows marked Delete in the tracker (admin only)."
                    : "Requires an admin / owner Dify role."
                }
                variant="danger"
                disabled={busy || !user?.is_admin}
                lastRun={lastRun["prune"]}
                onClick={() => setShowPrune(true)}
              />
            </div>
          </section>
        )}

        {view === "settings" && user?.is_admin && <SettingsPanel onToast={pushToast} />}
        </main>
      </div>

      <JobDrawer jobId={activeJob} onClose={() => setActiveJob(null)} onFinished={onJobFinished} />
      {showPrune && (
        <PruneModal
          markedCount={s?.marked_delete ?? 0}
          onPreview={() => startPrune(false)}
          onConfirm={() => startPrune(true)}
          onClose={() => setShowPrune(false)}
        />
      )}
      <Toaster toasts={toasts} onDismiss={(id) => setToasts((p) => p.filter((t) => t.id !== id))} />
    </div>
  );
}

function StatCard({
  label,
  value,
  accent,
  active,
  onClick,
  hint,
}: {
  label: string;
  value: number;
  accent?: "amber" | "red" | "blue";
  active: boolean;
  onClick: () => void;
  hint?: string;
}) {
  const accentClass =
    accent === "amber"
      ? "text-amber-600"
      : accent === "red"
        ? "text-red-600"
        : accent === "blue"
          ? "text-brand-600"
          : "text-slate-900";
  return (
    <button
      onClick={onClick}
      title={hint}
      aria-pressed={active}
      className={`group flex cursor-pointer flex-col rounded-xl border p-4 text-left shadow-card transition ${
        active
          ? "border-brand-300 bg-brand-50/40 ring-2 ring-brand/30"
          : "border-slate-200 bg-white hover:-translate-y-0.5 hover:border-brand-200 hover:shadow-md"
      }`}
    >
      <p className="flex items-center justify-between text-xs font-medium text-slate-500">
        {label}
        {active ? (
          <span className="relative flex h-2 w-2">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-brand opacity-75" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-brand" />
          </span>
        ) : (
          <FilterIcon className="h-3.5 w-3.5 text-slate-300 opacity-0 transition group-hover:opacity-100" />
        )}
      </p>
      <p className={`mt-1 text-2xl font-semibold tabular-nums ${accentClass}`}>{value}</p>
    </button>
  );
}

function SideItem({
  icon,
  label,
  active,
  collapsed,
  onClick,
}: {
  icon: ReactNode;
  label: string;
  active: boolean;
  collapsed?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      aria-current={active ? "page" : undefined}
      title={collapsed ? label : undefined}
      className={`flex w-full items-center gap-2.5 rounded-lg py-2 text-sm font-medium transition ${
        collapsed ? "justify-center px-0" : "px-3"
      } ${
        active
          ? "bg-brand-50 text-brand-700"
          : "text-slate-500 hover:bg-slate-100 hover:text-slate-800"
      }`}
    >
      <span className={active ? "text-brand-600" : "text-slate-400"}>{icon}</span>
      {!collapsed && label}
    </button>
  );
}

function LogoutIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
      className={className}
    >
      <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
      <path d="M16 17l5-5-5-5M21 12H9" />
    </svg>
  );
}

function DifyMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden className={className}>
      <path
        d="M7.043 6.487c1.635 0 2.241-1.003 2.241-2.243S8.681 2 7.044 2C5.405 2 4.801 3.003 4.801 4.244c0 1.24.604 2.243 2.241 2.243z"
        fill="#0033FF"
      />
      <path
        d="M14.883 6.97v1.443h-3.679v3.203h3.68v8.012H8.801V8.41h-8v3.203h4.48v8.012H0v3.203h24v-3.203h-5.6v-8.012H24V8.41h-5.6V5.206H24V2.003h-4.161a4.97 4.97 0 00-4.961 4.967h.005z"
        fill="#0033FF"
      />
    </svg>
  );
}

function GridIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
      className={className}
    >
      <rect x="3" y="3" width="7" height="7" rx="1.5" />
      <rect x="14" y="3" width="7" height="7" rx="1.5" />
      <rect x="3" y="14" width="7" height="7" rx="1.5" />
      <rect x="14" y="14" width="7" height="7" rx="1.5" />
    </svg>
  );
}

function BoltIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
      className={className}
    >
      <path d="M13 2 4 14h7l-1 8 9-12h-7z" />
    </svg>
  );
}

function ClockIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
      className={className}
    >
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3 2" />
    </svg>
  );
}

function GearIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
      className={className}
    >
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
    </svg>
  );
}

function LinksMenu({
  trackerUrl,
  docIndexUrl,
}: {
  trackerUrl?: string;
  docIndexUrl?: string | null;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener("click", close);
    return () => window.removeEventListener("click", close);
  }, [open]);
  const items: { label: string; href: string }[] = [];
  if (trackerUrl) items.push({ label: "Confluence tracker", href: trackerUrl });
  if (docIndexUrl) items.push({ label: "Docs index", href: docIndexUrl });
  if (items.length === 0) return null;
  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium text-slate-500 transition hover:bg-slate-100 hover:text-slate-800"
      >
        <LinkIcon className="h-3.5 w-3.5" />
        Links
        <ChevronDownIcon className={`h-3 w-3 transition ${open ? "rotate-180" : ""}`} />
      </button>
      {open && (
        <div className="absolute right-0 z-40 mt-1 w-48 rounded-lg border border-slate-200 bg-white p-1 text-sm shadow-lg">
          {items.map((it) => (
            <a
              key={it.label}
              href={it.href}
              target="_blank"
              rel="noreferrer"
              onClick={() => setOpen(false)}
              className="flex items-center gap-2 rounded px-2 py-1.5 text-slate-600 hover:bg-slate-50"
            >
              <LinkIcon className="h-3.5 w-3.5 text-slate-400" />
              {it.label}
            </a>
          ))}
        </div>
      )}
    </div>
  );
}

function OpCard({
  label,
  desc,
  variant = "secondary",
  disabled,
  lastRun,
  onClick,
}: {
  label: string;
  desc: string;
  variant?: "primary" | "secondary" | "danger";
  disabled?: boolean;
  lastRun?: Job;
  onClick: () => void;
}) {
  const btn = {
    primary: "bg-brand text-white hover:bg-brand-dark",
    secondary: "bg-slate-800 text-white hover:bg-slate-700",
    danger: "bg-red-600 text-white hover:bg-red-700",
  }[variant];
  return (
    <div
      className={`flex flex-col rounded-xl border bg-white p-4 shadow-card ${
        variant === "danger" ? "border-red-100" : "border-slate-200"
      }`}
    >
      <p className="text-sm font-semibold text-slate-800">{label}</p>
      <p className="mt-1 flex-1 text-xs leading-relaxed text-slate-500">{desc}</p>
      <div className="mt-3 flex items-center justify-between">
        <span className="text-[11px] text-slate-400">
          {lastRun ? `ran ${relativeTime(lastRun.finished_at)}` : ""}
        </span>
        <button
          onClick={onClick}
          disabled={disabled}
          className={`rounded-lg px-3 py-1.5 text-xs font-semibold transition disabled:cursor-not-allowed disabled:opacity-50 ${btn}`}
        >
          Run
        </button>
      </div>
    </div>
  );
}

function ColHeader({
  label,
  k,
  sort,
  onSort,
  options,
  selected,
  onToggle,
  onClear,
}: {
  label: string;
  k?: SortKey;
  sort: { key: SortKey; dir: "asc" | "desc" };
  onSort: (k: SortKey) => void;
  options?: Option[];
  selected?: Set<string>;
  onToggle?: (value: string) => void;
  onClear?: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);
  const btnRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const isSortActive = k && sort.key === k;
  const selectedCount = selected ? selected.size : 0;
  const hasFilter = !!options && options.length > 0 && !!onToggle && !!selected;

  function openMenu() {
    if (open) {
      setOpen(false);
      return;
    }
    setQuery("");
    const rect = btnRef.current?.getBoundingClientRect();
    if (rect) setPos({ top: rect.bottom + 6, left: rect.right });
    setOpen(true);
  }

  useEffect(() => {
    if (!open) return;
    const close = () => setOpen(false);
    // Ignore scrolls that happen inside the (scrollable) menu itself.
    const onScroll = (e: Event) => {
      if (menuRef.current && e.target instanceof Node && menuRef.current.contains(e.target)) return;
      setOpen(false);
    };
    window.addEventListener("click", close);
    window.addEventListener("scroll", onScroll, true);
    window.addEventListener("resize", close);
    return () => {
      window.removeEventListener("click", close);
      window.removeEventListener("scroll", onScroll, true);
      window.removeEventListener("resize", close);
    };
  }, [open]);

  const shown = options
    ? options.filter((o) => o.label.toLowerCase().includes(query.trim().toLowerCase()))
    : [];

  return (
    <th className="px-4 py-3 font-medium">
      <div className="flex items-center gap-1">
        {k ? (
          <button
            onClick={() => onSort(k)}
            className={`inline-flex items-center gap-1 transition hover:text-slate-700 ${
              isSortActive ? "text-slate-800" : ""
            }`}
          >
            {label}
            <span
              className={`text-[9px] leading-none ${isSortActive ? "opacity-100" : "opacity-30"}`}
            >
              {isSortActive && sort.dir === "desc" ? "▼" : "▲"}
            </span>
          </button>
        ) : (
          <span>{label}</span>
        )}
        {hasFilter && (
          <button
            ref={btnRef}
            onClick={(e) => {
              e.stopPropagation();
              openMenu();
            }}
            title="Filter"
            className={`inline-flex items-center rounded p-0.5 transition ${
              selectedCount > 0 ? "text-brand" : "text-slate-300 hover:text-slate-500"
            }`}
          >
            <FilterIcon className="h-3.5 w-3.5" />
            {selectedCount > 0 && (
              <span className="ml-0.5 rounded-full bg-brand px-1 text-[9px] leading-tight text-white">
                {selectedCount}
              </span>
            )}
          </button>
        )}
      </div>
      {open &&
        pos &&
        hasFilter &&
        selected &&
        onToggle &&
        typeof document !== "undefined" &&
        createPortal(
          <div
            ref={menuRef}
            onClick={(e) => e.stopPropagation()}
            style={{ top: pos.top, left: pos.left }}
            className="fixed z-[70] flex max-h-80 w-56 -translate-x-full flex-col rounded-lg border border-slate-200 bg-white text-left text-xs font-normal normal-case tracking-normal text-slate-700 shadow-lg"
          >
            <div className="flex items-center justify-between border-b border-slate-100 px-2 py-1.5">
              <span className="font-medium text-slate-500">Filter {label.toLowerCase()}</span>
              {selectedCount > 0 && (
                <button
                  onClick={() => (onClear ? onClear() : selected.forEach((v) => onToggle(v)))}
                  className="text-brand hover:underline"
                >
                  Clear
                </button>
              )}
            </div>
            {options && options.length > 8 && (
              <div className="border-b border-slate-100 p-1.5">
                <input
                  autoFocus
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Search…"
                  className="w-full rounded border border-slate-200 px-2 py-1 text-xs focus:border-brand focus:outline-none"
                />
              </div>
            )}
            <div className="overflow-auto p-1">
              {shown.length === 0 && <p className="px-2 py-2 text-slate-400">No values</p>}
              {shown.map((o) => {
                const on = selected.has(o.value);
                return (
                  <button
                    key={o.value}
                    onClick={() => onToggle(o.value)}
                    className="flex w-full items-center gap-2 rounded px-2 py-1.5 hover:bg-slate-50"
                  >
                    <span
                      className={`flex h-4 w-4 shrink-0 items-center justify-center rounded border text-[10px] ${
                        on ? "border-brand bg-brand text-white" : "border-slate-300"
                      }`}
                    >
                      {on ? "✓" : ""}
                    </span>
                    <span className="truncate">{o.label}</span>
                  </button>
                );
              })}
            </div>
          </div>,
          document.body
        )}
    </th>
  );
}

function LinkIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
      className={className}
    >
      <path d="M10 13a5 5 0 0 0 7 0l2-2a5 5 0 0 0-7-7l-1 1" />
      <path d="M14 11a5 5 0 0 0-7 0l-2 2a5 5 0 0 0 7 7l1-1" />
    </svg>
  );
}

function FilterIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
      className={className}
    >
      <path d="M3 5h18l-7 8v6l-4-2v-4z" />
    </svg>
  );
}

function Toaster({
  toasts,
  onDismiss,
}: {
  toasts: Toast[];
  onDismiss: (id: string) => void;
}) {
  return (
    <div className="fixed bottom-4 right-4 z-[60] flex w-80 flex-col gap-2">
      {toasts.map((t) => {
        const style =
          t.kind === "success"
            ? "border-emerald-200 bg-emerald-50 text-emerald-800"
            : t.kind === "error"
              ? "border-red-200 bg-red-50 text-red-800"
              : "border-slate-200 bg-white text-slate-700";
        return (
          <div
            key={t.id}
            className={`flex items-start gap-2 rounded-lg border px-3 py-2 text-sm shadow-card ${style}`}
          >
            <span className="flex-1 capitalize">{t.message}</span>
            <button
              onClick={() => onDismiss(t.id)}
              className="text-slate-400 transition hover:text-slate-600"
            >
              ✕
            </button>
          </div>
        );
      })}
    </div>
  );
}

function StatusPill({ removed, done }: { removed: boolean; done: boolean }) {
  const { dot, text, label } = removed
    ? { dot: "bg-red-500", text: "text-red-700", label: "removed" }
    : done
      ? { dot: "bg-emerald-500", text: "text-emerald-700", label: "done" }
      : { dot: "bg-amber-500", text: "text-amber-700", label: "pending" };
  return (
    <span className={`inline-flex items-center gap-1.5 text-xs font-medium ${text}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${dot}`} />
      {label}
    </span>
  );
}

function SearchIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
      className={className}
    >
      <circle cx="11" cy="11" r="7" />
      <path d="m20 20-3.5-3.5" />
    </svg>
  );
}

function ConfluenceIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden className={className}>
      <path d="M.87 18.257c-.248.382-.53.875-.763 1.245a.764.764 0 00.255 1.04l4.965 3.054a.764.764 0 001.058-.26c.199-.332.456-.764.733-1.221 1.967-3.247 3.945-2.853 7.508-1.146l4.957 2.337a.764.764 0 001.028-.382l2.364-5.346a.764.764 0 00-.382-.998c-1.046-.49-3.137-1.475-5.017-2.39C10.42 10.553 5.16 10.836.87 18.257zM23.131 5.743c.248-.382.53-.875.763-1.245a.764.764 0 00-.255-1.04L18.674.404a.764.764 0 00-1.058.26c-.199.332-.456.764-.733 1.221-1.967 3.247-3.945 2.853-7.508 1.146L4.418.694a.764.764 0 00-1.028.382L1.026 6.422a.764.764 0 00.382.998c1.046.49 3.137 1.475 5.017 2.39 6.502 3.149 11.762 2.866 16.706-4.067z" />
    </svg>
  );
}

function ChevronDownIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
      className={className}
    >
      <path d="M6 9l6 6 6-6" />
    </svg>
  );
}

function RefreshIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
      className={className}
    >
      <path d="M3 12a9 9 0 0 1 15-6.7L21 8M21 3v5h-5M21 12a9 9 0 0 1-15 6.7L3 16M3 21v-5h5" />
    </svg>
  );
}

function DocMenu({
  docUrl,
  onGenerate,
}: {
  docUrl?: string;
  onGenerate: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);
  const btnRef = useRef<HTMLButtonElement>(null);

  function toggle() {
    if (open) {
      setOpen(false);
      return;
    }
    const rect = btnRef.current?.getBoundingClientRect();
    if (rect) setPos({ top: rect.bottom + 6, left: rect.right });
    setOpen(true);
  }

  useEffect(() => {
    if (!open) return;
    const close = () => setOpen(false);
    window.addEventListener("click", close);
    window.addEventListener("scroll", close, true);
    window.addEventListener("resize", close);
    return () => {
      window.removeEventListener("click", close);
      window.removeEventListener("scroll", close, true);
      window.removeEventListener("resize", close);
    };
  }, [open]);

  return (
    <>
      <button
        ref={btnRef}
        onClick={(e) => {
          e.stopPropagation();
          toggle();
        }}
        aria-haspopup="menu"
        aria-expanded={open}
        title={docUrl ? "Documentation (published)" : "Documentation (not published yet)"}
        className={`inline-flex items-center gap-0.5 transition ${
          open ? "text-[#2684FF]" : docUrl ? "text-[#2684FF] hover:opacity-70" : "text-slate-400 hover:text-[#2684FF]"
        }`}
      >
        <ConfluenceIcon className="h-4 w-4" />
        <ChevronDownIcon
          className={`h-3 w-3 transition-transform ${open ? "rotate-180" : ""}`}
        />
      </button>
      {open &&
        pos &&
        typeof document !== "undefined" &&
        createPortal(
          <div
            onClick={(e) => e.stopPropagation()}
            style={{ top: pos.top, left: pos.left }}
            className="fixed z-[70] w-56 -translate-x-full overflow-hidden rounded-lg border border-slate-200 bg-white py-1 text-left text-sm shadow-lg"
          >
            {docUrl && (
              <a
                href={docUrl}
                target="_blank"
                rel="noreferrer"
                onClick={() => setOpen(false)}
                className="flex items-center gap-2 px-3 py-2 text-slate-700 hover:bg-slate-50"
              >
                <ConfluenceIcon className="h-4 w-4 text-[#2684FF]" />
                Open in Confluence
              </a>
            )}
            <button
              onClick={() => {
                setOpen(false);
                onGenerate();
              }}
              className="flex w-full items-center gap-2 px-3 py-2 text-slate-700 hover:bg-slate-50"
            >
              <RefreshIcon className="h-4 w-4 text-slate-400" />
              {docUrl ? "Regenerate & publish" : "Generate & publish"}
            </button>
          </div>,
          document.body
        )}
    </>
  );
}

function WorkflowIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
      className={className}
    >
      <circle cx="5" cy="6" r="2" />
      <circle cx="5" cy="18" r="2" />
      <circle cx="19" cy="12" r="2" />
      <path d="M7 6h6a4 4 0 0 1 4 4M7 18h6a4 4 0 0 0 4-4" />
    </svg>
  );
}

function PlusIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
      className={className}
    >
      <path d="M12 5v14M5 12h14" />
    </svg>
  );
}

function XIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
      className={className}
    >
      <path d="M6 6l12 12M18 6L6 18" />
    </svg>
  );
}

function TrashIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
      className={className}
    >
      <path d="M3 6h18M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2m2 0v14a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V6" />
      <path d="M10 11v6M14 11v6" />
    </svg>
  );
}

function Row({
  r,
  isAdmin,
  meName,
  meEmail,
  docUrl,
  onGenerate,
  onChanged,
  onToast,
}: {
  r: WorkflowRecord;
  isAdmin: boolean;
  meName: string;
  meEmail: string;
  docUrl?: string;
  onGenerate: () => void;
  onChanged: () => void;
  onToast: (msg: string, kind: Toast["kind"]) => void;
}) {
  const [busy, setBusy] = useState(false);
  const envs = envBadges(r.tags);
  const authors = splitAuthors(r.author);
  const missingEnvs = ENV_TAGS.filter((e) => !envs.includes(e));
  const canEdit = r.live_in_dify;
  const isTracked = r.source !== "new";
  const myLocal = meEmail.split("@")[0]?.toLowerCase() || "";
  const isMe = (name: string) => {
    const n = name.trim().toLowerCase();
    return (n && n === meName.trim().toLowerCase()) || (myLocal && n === myLocal);
  };

  async function addEnv(env: string) {
    setBusy(true);
    try {
      await api.addEnvTags(r.app_id, [env]);
      onToast(`Tagged "${r.name}" as ${env}`, "success");
      onChanged();
    } catch (e) {
      onToast(e instanceof Error ? e.message : "Failed to add tag", "error");
    } finally {
      setBusy(false);
    }
  }

  async function removeEnv(env: string) {
    setBusy(true);
    try {
      await api.removeEnvTag(r.app_id, env);
      onToast(`Removed ${env} tag from "${r.name}"`, "success");
      onChanged();
    } catch (e) {
      onToast(e instanceof Error ? e.message : "Failed to remove tag", "error");
    } finally {
      setBusy(false);
    }
  }

  async function assignToMe() {
    setBusy(true);
    try {
      const res = await api.assignAuthor(r.app_id);
      onToast(`Assigned "${r.name}" to ${res.author}`, "success");
      onChanged();
    } catch (e) {
      onToast(e instanceof Error ? e.message : "Failed to assign author", "error");
    } finally {
      setBusy(false);
    }
  }

  async function unassign(name: string) {
    setBusy(true);
    try {
      await api.unassignAuthor(r.app_id, name);
      onToast(`Removed ${name} from "${r.name}"`, "success");
      onChanged();
    } catch (e) {
      onToast(e instanceof Error ? e.message : "Failed to remove author", "error");
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!window.confirm(`Delete "${r.name}" from Dify? This cannot be undone.`)) return;
    setBusy(true);
    try {
      await api.deleteWorkflow(r.app_id);
      onToast(`Deleted "${r.name}" from Dify`, "success");
      onChanged();
    } catch (e) {
      onToast(e instanceof Error ? e.message : "Failed to delete", "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <tr className="transition hover:bg-slate-50/70">
      <td className="px-4 py-3">
        <div className="flex items-center gap-2">
          <span className="font-medium text-slate-800">{r.name}</span>
          {r.source === "new" && (
            <span
              title="Live in Dify but not yet on the Confluence tracker. The next sync will add it."
              className="rounded-full bg-brand-50 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-brand-700 ring-1 ring-brand-100"
            >
              new
            </span>
          )}
        </div>
      </td>
      <td className="px-4 py-3">
        {authors.length ? (
          <div className="flex flex-wrap items-center gap-1.5">
            {authors.map((name) => {
              const c = authorColor(name);
              return (
                <span
                  key={name}
                  className={`inline-flex items-center gap-1.5 rounded-full py-0.5 pl-0.5 ${
                    canEdit && isTracked && isMe(name) ? "pr-1" : "pr-2"
                  } text-xs font-medium ring-1 ring-inset ${c.chip} ${c.text}`}
                >
                  <span
                    className={`flex h-5 w-5 items-center justify-center rounded-full text-[9px] font-semibold ${c.dot}`}
                  >
                    {initials(name)}
                  </span>
                  {name}
                  {canEdit && isTracked && isMe(name) && (
                    <button
                      onClick={() => unassign(name)}
                      disabled={busy}
                      title="Remove yourself as author"
                      className="-mr-0.5 rounded-full p-0.5 opacity-60 transition hover:bg-black/10 hover:opacity-100 disabled:opacity-30"
                    >
                      <XIcon className="h-3 w-3" />
                    </button>
                  )}
                </span>
              );
            })}
          </div>
        ) : r.source === "new" ? (
          <span
            title="Add this workflow to the tracker (run Sync) before assigning an author."
            className="text-slate-300"
          >
            —
          </span>
        ) : (
          <button
            onClick={assignToMe}
            disabled={busy}
            title="Assign this workflow to yourself in the tracker"
            className="inline-flex items-center gap-1 rounded-full border border-dashed border-slate-300 px-2 py-0.5 text-xs text-slate-400 transition hover:border-brand hover:text-brand disabled:opacity-50"
          >
            <PlusIcon className="h-3 w-3" />
            Assign to me
          </button>
        )}
      </td>
      <td className="px-4 py-3">
        <div className="flex flex-wrap items-center gap-1">
          {envs.map((e) => (
            <span
              key={e}
              className={`inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-xs font-medium ring-1 ring-inset ${
                ENV_STYLES[e] || "bg-slate-100 text-slate-600 ring-slate-200"
              }`}
            >
              {e}
              {canEdit && (
                <button
                  onClick={() => removeEnv(e)}
                  disabled={busy}
                  title={`Remove ${e} tag in Dify`}
                  className="-mr-0.5 rounded-full p-0.5 opacity-60 transition hover:bg-black/10 hover:opacity-100 disabled:opacity-30"
                >
                  <XIcon className="h-3 w-3" />
                </button>
              )}
            </span>
          ))}
          {/* A workflow should carry a single environment tag, so only offer
              suggestions when none is set yet. */}
          {canEdit &&
            envs.length === 0 &&
            missingEnvs.map((e) => (
              <button
                key={e}
                onClick={() => addEnv(e)}
                disabled={busy}
                title={`Tag this workflow as ${e} in Dify`}
                className="rounded-md border border-dashed border-slate-300 px-1.5 py-0.5 text-xs text-slate-400 transition hover:border-brand hover:text-brand disabled:opacity-50"
              >
                + {e}
              </button>
            ))}
        </div>
      </td>
      <td className="px-4 py-3">
        {r.decision ? (
          <span
            className={`rounded-md px-1.5 py-0.5 text-xs font-medium ${
              r.decision.trim().toLowerCase() === "delete"
                ? "bg-red-50 text-red-700 ring-1 ring-inset ring-red-200"
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
        <StatusPill removed={r.removed_from_dify} done={r.informations_added} />
      </td>
      <td className="px-4 py-3">
        <div className="flex items-center justify-end gap-3 whitespace-nowrap">
          {canEdit && <DocMenu docUrl={docUrl} onGenerate={onGenerate} />}
          {r.url && (
            <a
              href={r.url}
              target="_blank"
              rel="noreferrer"
              title="Open in Dify"
              className="text-slate-400 hover:text-brand"
            >
              <WorkflowIcon className="h-4 w-4" />
            </a>
          )}
          {isAdmin && canEdit && (
            <button
              onClick={remove}
              disabled={busy}
              title="Delete from Dify"
              className="text-slate-400 hover:text-red-600 disabled:opacity-50"
            >
              <TrashIcon className="h-4 w-4" />
            </button>
          )}
        </div>
      </td>
    </tr>
  );
}
