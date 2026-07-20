import { useMemo, useState } from "react";
import type { ActivityEvent } from "../api/types";
import Explain from "./Explain";

// Event kinds with no symbol, or stack-wide meaning, live in the SYSTEM row.
const SYSTEM_LABEL = "System";

// Blocks are first-class content: the engine refuses far more often than it
// acts, and the refusals carry the real numbers.
const BLOCK_KINDS = new Set(["risk_block", "provenance_block", "council_skip",
  "market_hours_entry", "market_hours", "discovery_blocked", "discovery_skip"]);
const ACT_KINDS = new Set(["trade", "trade_entry", "trade_exit"]);

function fmtNum(v: unknown): string {
  if (typeof v !== "number") return String(v ?? "—");
  if (Number.isInteger(v)) return String(v);
  return Math.abs(v) >= 100 ? v.toFixed(2) : v.toFixed(4);
}

// The payload keys worth showing inline for a block or an entry: the numbers
// the decision was actually judged on, next to their floors.
const NUMBER_KEYS = ["confidence", "min_confidence", "edge", "min_edge",
  "agreement", "required_agreement", "strength", "stop", "target", "notional",
  "reason", "tier", "factor", "regime", "bar_source"];

function PayloadLine({ payload }: { payload: Record<string, unknown> }) {
  const parts = NUMBER_KEYS.filter((k) => payload[k] !== undefined)
    .map((k) => `${k}=${fmtNum(payload[k])}`);
  if (!parts.length) return null;
  return <span className="mono dim payload-line"> {parts.join("  ")}</span>;
}

function timeOf(ts: string): string {
  return ts.length >= 19 ? ts.slice(11, 19) : ts;
}

interface Group {
  key: string;            // symbol or SYSTEM_LABEL
  events: ActivityEvent[]; // ascending
  blocks: number;
  acts: number;
  lastTs: string;
  summary: string;
}

// A one-line summary of recent activity: what a collapsed row says.
function summarize(events: ActivityEvent[]): string {
  const recent = events.slice(-60);
  const blockReasons = new Map<string, number>();
  let lastAct: ActivityEvent | null = null;
  for (const e of recent) {
    if (BLOCK_KINDS.has(e.kind)) {
      const reason = String(e.payload["reason"] ?? e.kind);
      blockReasons.set(reason, (blockReasons.get(reason) ?? 0) + 1);
    }
    if (ACT_KINDS.has(e.kind)) lastAct = e;
  }
  const parts: string[] = [];
  if (lastAct) {
    const side = String(lastAct.payload["factor"] ?? lastAct.kind);
    parts.push(`${lastAct.kind.replace("_", " ")} (${side}) at ${timeOf(lastAct.ts)}`);
  }
  const topBlock = [...blockReasons.entries()].sort((a, b) => b[1] - a[1])[0];
  if (topBlock) parts.push(`blocked ${topBlock[1]}x on ${topBlock[0]}`);
  if (!parts.length && recent.length)
    parts.push(recent[recent.length - 1].message.slice(0, 80));
  return parts.join(" · ") || "no recent activity";
}

export function groupEvents(events: ActivityEvent[]): Group[] {
  const by = new Map<string, ActivityEvent[]>();
  for (const e of events) {
    const key = e.symbol && e.symbol.length ? e.symbol : SYSTEM_LABEL;
    const arr = by.get(key);
    if (arr) arr.push(e);
    else by.set(key, [e]);
  }
  const groups: Group[] = [];
  for (const [key, evs] of by) {
    groups.push({
      key,
      events: evs,
      blocks: evs.filter((e) => BLOCK_KINDS.has(e.kind)).length,
      acts: evs.filter((e) => ACT_KINDS.has(e.kind)).length,
      lastTs: evs[evs.length - 1].ts,
      summary: summarize(evs),
    });
  }
  // Most recently active first; the system row stays last unless it is the
  // only thing talking.
  groups.sort((a, b) => {
    if (a.key === SYSTEM_LABEL) return 1;
    if (b.key === SYSTEM_LABEL) return -1;
    return a.lastTs < b.lastTs ? 1 : -1;
  });
  return groups;
}

function EventRow({ e }: { e: ActivityEvent }) {
  const cls = BLOCK_KINDS.has(e.kind) ? "ev-block"
    : ACT_KINDS.has(e.kind) ? "ev-act"
    : e.severity === "critical" ? "ev-critical"
    : e.severity === "warn" ? "ev-warn" : "";
  return (
    <div className={`ev-row ${cls}`} data-testid="event-row">
      <span className="mono dim">{timeOf(e.ts)}</span>
      <span className="ev-kind mono">{e.kind}</span>
      <span className="ev-msg">{e.message}</span>
      <PayloadLine payload={e.payload} />
    </div>
  );
}

export default function ActivityBySymbol({ events, connected }: {
  events: ActivityEvent[];
  connected: boolean;
}) {
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const groups = useMemo(() => groupEvents(events), [events]);

  if (!events.length) {
    return (
      <div className="empty" data-testid="activity-empty">
        No engine activity yet. Start the stack and every evaluation, block,
        and trade appears here, grouped by symbol.
      </div>
    );
  }
  return (
    <div data-testid="activity-groups">
      <Explain>
        Every event the engine writes, live, grouped by symbol. Blocks are the
        point: the engine refuses far more often than it acts, and each block
        line carries the numbers it was judged on against their floors.
        {connected ? "" : " (stream reconnecting, showing last known events)"}
      </Explain>
      {groups.map((g) => (
        <div className="sym-group" key={g.key} data-testid={`group-${g.key}`}>
          <button className="sym-head" data-testid={`group-head-${g.key}`}
            onClick={() => setOpen((p) => ({ ...p, [g.key]: !p[g.key] }))}>
            <span className="sym-name mono">{g.key}</span>
            <span className="sym-summary dim">{g.summary}</span>
            <span className="sym-counts mono dim">
              {g.acts > 0 ? `${g.acts} act ` : ""}{g.blocks} blocked · {g.events.length} events
            </span>
            <span className="sym-caret">{open[g.key] ? "▾" : "▸"}</span>
          </button>
          {open[g.key] && (
            <div className="sym-events" data-testid={`group-events-${g.key}`}>
              {[...g.events].reverse().map((e) => <EventRow e={e} key={e.id} />)}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
