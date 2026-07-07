import { useMemo, useState } from "react";
import { api } from "../api/client";
import { useApi } from "../api/useApi";
import type { Council, Credential, Venue } from "../api/types";
import { DataState, Empty, Panel } from "../components/ui";

interface Category { title: string; groups: string[]; note: string; testMode?: string; }

const CATEGORIES: Category[] = [
  { title: "LLM council", groups: ["openai", "anthropic", "gemini"],
    note: "Provider keys for the advisory council. A saved key resolves in-app first, then env." },
  { title: "Paper venue", groups: ["alpaca"], testMode: "paper",
    note: "Alpaca handles all paper trading and paper market data. It has no live path." },
  { title: "Live venue", groups: ["ibkr"], testMode: "live",
    note: "IBKR live connection settings. Live stays disabled behind the approval gate." },
  { title: "Crypto venue", groups: ["coinbase"], testMode: "paper",
    note: "Coinbase, simulated and paper only." },
  { title: "Whale data", groups: ["clankapp", "sec_api", "whale_alert"],
    note: "Free-first: ClankApp and SEC EDGAR need no paid key." },
];

function CredField({ c, onSaved }: { c: Credential; onSaved: () => void }) {
  const [val, setVal] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const placeholder = c.configured
    ? (c.source === "env" ? "set from env — leave blank to keep"
      : "set — leave blank to keep")
    : "not set";
  const save = async () => {
    if (!val.trim()) return;
    setBusy(true); setMsg(null);
    try {
      const r = await api.saveCredential(c.name, val);
      setMsg(r.ok ? "saved" : r.error ?? "failed");
      setVal("");
      onSaved();
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "failed");
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="field-row">
      <label>{c.label}{c.mode ? ` (${c.mode})` : ""}</label>
      <input className="input" type={c.secret ? "password" : "text"} value={val}
        placeholder={placeholder} style={{ maxWidth: 260 }}
        onChange={(e) => setVal(e.target.value)} />
      <button className="btn ghost" disabled={busy || !val.trim()} onClick={save}>
        {busy ? "…" : "Save"}
      </button>
      <span className={c.configured ? "pos" : "dim"} style={{ fontSize: 12 }}>
        {c.configured ? `● ${c.source}` : "not set"}
      </span>
      {msg && <span className="muted" style={{ fontSize: 12 }}>{msg}</span>}
    </div>
  );
}

export default function SettingsPage() {
  const credsApi = useApi(() => api.credentials(), 0, []);
  const councilApi = useApi<Council>(() => api.council(), 0, []);
  const venuesApi = useApi(() => api.venues(), 0, []);
  const [tests, setTests] = useState<Record<string, string>>({});

  const byGroup = useMemo(() => {
    const m: Record<string, Credential[]> = {};
    for (const c of credsApi.data?.credentials ?? []) (m[c.group] ??= []).push(c);
    return m;
  }, [credsApi.data]);

  const venueByName = useMemo(() => {
    const m: Record<string, Venue> = {};
    for (const v of venuesApi.data?.venues ?? []) m[v.venue] = v;
    return m;
  }, [venuesApi.data]);

  const runTest = async (group: string, mode?: string) => {
    try {
      const r = await api.testConnection(group, mode);
      setTests((t) => ({ ...t, [group]: `${r.ok ? "OK" : "not ready"} — ${r.message}` }));
    } catch (e) {
      setTests((t) => ({ ...t, [group]: e instanceof Error ? e.message : "failed" }));
    }
  };

  const models = councilApi.data?.models ?? {};

  return (
    <div>
      <h1 className="page-title">Settings &amp; APIs</h1>
      <p className="page-sub">
        Credentials are encrypted at rest in a local keystore and never written
        to YAML or logs. Resolution order: in-app saved value first, then env.
      </p>

      <Panel title="Active council models" style={{ marginBottom: 14 }}>
        {Object.keys(models).length ? (
          <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
            {Object.entries(models).map(([slot, id]) => (
              <div key={slot} style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <span className="dim" style={{ fontSize: 12 }}>{slot}</span>
                <span className="tag neutral mono">{id}</span>
              </div>
            ))}
          </div>
        ) : (
          <Empty>Council models unavailable.</Empty>
        )}
      </Panel>

      <DataState loading={credsApi.loading && !credsApi.data} error={credsApi.error}>
        {CATEGORIES.map((cat) => {
          const groups = cat.groups.filter((g) => byGroup[g]?.length);
          if (!groups.length) return null;
          return (
            <div key={cat.title} style={{ marginBottom: 14 }}>
              <Panel title={cat.title}>
                <p className="muted" style={{ fontSize: 12, marginTop: 0 }}>{cat.note}</p>
                {groups.map((g) => {
                  const creds = byGroup[g];
                  const v = venueByName[g];
                  const configured = creds.some((c) => c.configured);
                  return (
                    <div key={g} style={{
                      marginBottom: 12, paddingTop: 10,
                      borderTop: "1px solid var(--border)",
                    }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
                        <b>{creds[0].group_label}</b>
                        <span className={configured ? "pos" : "dim"} style={{ fontSize: 12 }}>
                          {configured ? "● configured" : "○ not configured"}
                        </span>
                        {v && (
                          <span className="dim" style={{ fontSize: 12 }}>
                            runtime: {v.runtime_mode ?? v.mode ?? "—"}
                            {v.live_enabled ? " · live enabled" : ""}
                          </span>
                        )}
                      </div>
                      {creds.map((c) => (
                        <CredField key={c.name} c={c} onSaved={credsApi.reload} />
                      ))}
                      <div style={{ display: "flex", gap: 10, alignItems: "center", marginTop: 6 }}>
                        <button className="btn ghost"
                          onClick={() => runTest(g, cat.testMode)}>
                          Test connection
                        </button>
                        {tests[g] && (
                          <span className="muted" style={{ fontSize: 12 }}>{tests[g]}</span>
                        )}
                      </div>
                    </div>
                  );
                })}
              </Panel>
            </div>
          );
        })}
      </DataState>
    </div>
  );
}
