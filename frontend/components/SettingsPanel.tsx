"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { api, SettingGroup, SettingsTest } from "@/lib/api";

type Values = Record<string, string | boolean>;
type Toast = (msg: string, kind: "success" | "error" | "info") => void;

export default function SettingsPanel({ onToast }: { onToast: Toast }) {
  const [groups, setGroups] = useState<SettingGroup[] | null>(null);
  const [values, setValues] = useState<Values>({});
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [test, setTest] = useState<SettingsTest | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await api.settings();
      setGroups(res.groups);
      const v: Values = {};
      for (const g of res.groups) {
        for (const f of g.fields) {
          v[f.key] = f.type === "bool" ? f.value === "true" : f.value;
        }
      }
      setValues(v);
      setDirty(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load settings");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // Only send fields the user actually changed (so blank secrets stay intact).
  const changed = useMemo(() => {
    if (!groups) return {} as Values;
    const out: Values = {};
    for (const g of groups) {
      for (const f of g.fields) {
        const cur = values[f.key];
        const orig = f.type === "bool" ? f.value === "true" : f.value;
        if (cur !== orig) out[f.key] = cur;
      }
    }
    return out;
  }, [groups, values]);

  function set(key: string, val: string | boolean) {
    setValues((p) => ({ ...p, [key]: val }));
    setDirty(true);
  }

  async function save() {
    setSaving(true);
    setError(null);
    try {
      const res = await api.updateSettings(changed as Record<string, string | boolean>);
      setGroups(res.groups);
      const v: Values = {};
      for (const g of res.groups)
        for (const f of g.fields) v[f.key] = f.type === "bool" ? f.value === "true" : f.value;
      setValues(v);
      setDirty(false);
      onToast("Settings saved", "success");
    } catch (e) {
      onToast(e instanceof Error ? e.message : "Failed to save settings", "error");
    } finally {
      setSaving(false);
    }
  }

  async function runTest() {
    setTesting(true);
    setTest(null);
    try {
      const res = await api.testSettings(changed as Record<string, string | boolean>);
      setTest(res);
    } catch (e) {
      onToast(e instanceof Error ? e.message : "Test failed", "error");
    } finally {
      setTesting(false);
    }
  }

  if (error)
    return (
      <div className="mx-auto max-w-3xl rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700">
        {error}
      </div>
    );

  if (!groups)
    return <div className="mx-auto max-w-3xl text-sm text-slate-400">Loading settings…</div>;

  return (
    <section className="mx-auto max-w-3xl pb-24">
      <div className="mb-4">
        <h2 className="text-lg font-semibold text-slate-800">Settings</h2>
        <p className="text-sm text-slate-500">
          Configuration for Dify, Confluence and Slack. Saved values override <code>.env</code> and
          apply immediately to new operations.
        </p>
      </div>

      <div className="space-y-4">
        {groups.map((g) => (
          <div key={g.group} className="rounded-xl border border-slate-200 bg-white p-4 shadow-card">
            <h3 className="mb-3 text-sm font-semibold text-slate-700">{g.group}</h3>
            <div className="space-y-3">
              {g.fields.map((f) => (
                <div key={f.key} className="grid grid-cols-1 gap-1 sm:grid-cols-3 sm:items-start sm:gap-3">
                  <label htmlFor={f.key} className="pt-1.5 text-sm font-medium text-slate-600">
                    {f.label}
                    {f.secret && f.is_set && (
                      <span className="ml-1.5 rounded bg-emerald-50 px-1 py-0.5 text-[10px] font-medium text-emerald-600 ring-1 ring-emerald-200">
                        set
                      </span>
                    )}
                  </label>
                  <div className="sm:col-span-2">
                    {f.type === "bool" ? (
                      <button
                        type="button"
                        onClick={() => set(f.key, !values[f.key])}
                        className={`relative inline-flex h-6 w-11 items-center rounded-full transition ${
                          values[f.key] ? "bg-brand" : "bg-slate-300"
                        }`}
                      >
                        <span
                          className={`inline-block h-5 w-5 transform rounded-full bg-white shadow transition ${
                            values[f.key] ? "translate-x-5" : "translate-x-0.5"
                          }`}
                        />
                      </button>
                    ) : (
                      <input
                        id={f.key}
                        type={f.type === "password" ? "password" : "text"}
                        value={(values[f.key] as string) ?? ""}
                        onChange={(e) => set(f.key, e.target.value)}
                        placeholder={f.secret && f.is_set ? "•••••••• (leave blank to keep)" : ""}
                        autoComplete="off"
                        className="w-full rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm shadow-sm transition focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
                      />
                    )}
                    {f.help && <p className="mt-1 text-xs text-slate-400">{f.help}</p>}
                  </div>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>

      {test && (
        <div className="mt-4 grid gap-2 sm:grid-cols-2">
          <TestRow label="Confluence" result={test.confluence} />
          <TestRow label="Dify" result={test.dify} />
        </div>
      )}

      {/* Sticky action bar */}
      <div className="fixed inset-x-0 bottom-0 z-20 border-t border-slate-200 bg-white/90 backdrop-blur">
        <div className="mx-auto flex max-w-3xl items-center justify-between gap-3 px-6 py-3">
          <span className="text-xs text-slate-400">
            {dirty ? `${Object.keys(changed).length} unsaved change(s)` : "All changes saved"}
          </span>
          <div className="flex items-center gap-2">
            <button
              onClick={runTest}
              disabled={testing}
              className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 transition hover:bg-slate-50 disabled:opacity-50"
            >
              {testing ? "Testing…" : "Test connection"}
            </button>
            <button
              onClick={save}
              disabled={saving || !dirty}
              className="rounded-lg bg-brand px-4 py-1.5 text-sm font-semibold text-white shadow-sm transition hover:bg-brand-dark disabled:opacity-50"
            >
              {saving ? "Saving…" : "Save changes"}
            </button>
          </div>
        </div>
      </div>
    </section>
  );
}

function TestRow({ label, result }: { label: string; result: { ok: boolean; detail: string } }) {
  return (
    <div
      className={`flex items-start gap-2 rounded-lg border px-3 py-2 text-sm ${
        result.ok
          ? "border-emerald-200 bg-emerald-50 text-emerald-700"
          : "border-red-200 bg-red-50 text-red-700"
      }`}
    >
      <span className="mt-0.5 font-semibold">{result.ok ? "✓" : "✕"}</span>
      <div>
        <p className="font-medium">{label}</p>
        <p className="text-xs opacity-90">{result.detail}</p>
      </div>
    </div>
  );
}
