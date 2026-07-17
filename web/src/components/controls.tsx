import { useState } from "react";
import type { Prereqs } from "../api/types";

export function PrereqList({ prereqs }: { prereqs: Prereqs }) {
  return (
    <ul className="prereq-list" data-testid="prereq-list">
      {prereqs.checks.map((c) => (
        <li key={c.key} className={c.ok ? "ok" : "warn"}>
          <span className={`dot ${c.ok ? "g" : "a"}`} />
          <b>{c.label}</b> <span className="muted">{c.detail}</span>
        </li>
      ))}
    </ul>
  );
}

// An enable that arms, states what it starts, then fires. Disable is immediate:
// turning a spender OFF should never need a ceremony.
//
// Lives here rather than beside one caller because three controls now need it
// (discovery, the long-term strategy, and the research_satellite sleeve). It is
// the shared idiom for "an action with consequences asks twice", the same
// posture as the kill switch and the engine start.
//
// `prereqs` is optional: a control can have no prerequisite of its own and still
// deserve a confirm. The research_satellite sleeve is exactly that. It allocates
// capital, so it must state what it does before it does it, but nothing has to be
// reachable first for a sleeve to be enabled.
//
// `heading` is overridable because not every armed control spends. Enabling a
// sleeve ALLOCATES, and telling an operator "this starts spending" when it does
// not would train them to ignore the line that matters.
export function ArmedToggle({ on, label, what, prereqs, busy, onSet, testid,
                             heading = "This starts spending." }: {
  on: boolean;
  label: string;
  what: string;
  prereqs?: Prereqs;
  busy: boolean;
  onSet: (next: boolean) => void;
  testid: string;
  heading?: string;
}) {
  const [armed, setArmed] = useState(false);
  const blocked = !!prereqs && !prereqs.ok;

  return (
    <div className="disc-toggle" data-testid={testid}>
      <div className="disc-toggle-head">
        <span className={`dot ${on ? "g" : "d"}`} />
        <b>{label}</b>
        <span className={on ? "ok" : "dim"}>{on ? "ON" : "off"}</span>
        {on ? (
          <button className="btn ghost sm" disabled={busy}
            onClick={() => onSet(false)}>
            disable
          </button>
        ) : !armed ? (
          <button className="btn sm" disabled={busy || blocked}
            onClick={() => setArmed(true)}>
            enable
          </button>
        ) : (
          <>
            <button className="btn sm" disabled={busy}
              onClick={() => { onSet(true); setArmed(false); }}>
              {busy ? "…" : "confirm"}
            </button>
            <button className="btn ghost sm" disabled={busy}
              onClick={() => setArmed(false)}>
              cancel
            </button>
          </>
        )}
      </div>

      {/* The confirm states plainly what turning this on does, before it does
          it. An operator should never learn what a toggle does afterwards. */}
      {armed && (
        <div className="disc-confirm" data-testid={`${testid}-confirm`}>
          <b>{heading}</b> {what}
        </div>
      )}

      {blocked && !on && prereqs && (
        <div className="disc-blocked" data-testid={`${testid}-blocked`}>
          <b>Cannot enable yet.</b> Missing prerequisites:
          <PrereqList prereqs={prereqs} />
        </div>
      )}
    </div>
  );
}

// Gold toggle switch. Controlled: parent owns the value, the switch reports a
// requested change. Disabled toggles never fire.
export function Toggle({ on, disabled, onToggle }: {
  on: boolean; disabled?: boolean; onToggle: (next: boolean) => void;
}) {
  return (
    <button type="button" className={`toggle${on ? " on" : ""}`}
      disabled={disabled} aria-pressed={on}
      onClick={() => !disabled && onToggle(!on)}>
      <span className="knob" />
    </button>
  );
}

// Mock-versus-real source segmented control. The SOURCE axis is distinct from
// the enable Toggle: it only matters when the layer is on. Disabled (greyed)
// when the layer is off, since source is meaningless then.
export function SourceToggle({ source, disabled, onSelect }: {
  source: string; disabled?: boolean; onSelect: (next: "mock" | "real") => void;
}) {
  return (
    <div className={`srcseg${disabled ? " disabled" : ""}`} role="group"
      aria-label="source">
      {(["mock", "real"] as const).map((s) => (
        <button type="button" key={s}
          className={`srcseg-btn${source === s ? " active" : ""}`}
          aria-pressed={source === s} disabled={disabled}
          onClick={() => !disabled && source !== s && onSelect(s)}>
          {s}
        </button>
      ))}
    </div>
  );
}

export function Slider({ value, min = 0, max = 1, step = 0.01, disabled, onChange }: {
  value: number; min?: number; max?: number; step?: number;
  disabled?: boolean; onChange: (v: number) => void;
}) {
  return (
    <input type="range" min={min} max={max} step={step} value={value}
      disabled={disabled}
      onChange={(e) => onChange(Number(e.target.value))} />
  );
}

// Two-step confirm button. The first click arms, the second confirms. Used for
// every consequential control action (promote, rollback, weight apply).
export function ConfirmButton({ label, busyLabel, danger, disabled, onConfirm }: {
  label: string; busyLabel?: string; danger?: boolean; disabled?: boolean;
  onConfirm: () => Promise<void> | void;
}) {
  const [armed, setArmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const cls = `btn sm${danger ? " danger" : " ghost"}`;
  if (!armed) {
    return (
      <button className={cls} disabled={disabled}
        onClick={() => setArmed(true)}>{label}</button>
    );
  }
  return (
    <span style={{ display: "inline-flex", gap: 8 }}>
      <button className={`btn sm${danger ? " danger" : ""}`} disabled={busy}
        onClick={async () => {
          setBusy(true);
          try { await onConfirm(); } finally { setBusy(false); setArmed(false); }
        }}>{busy ? (busyLabel ?? "Working…") : "Confirm"}</button>
      <button className="btn sm ghost" disabled={busy}
        onClick={() => setArmed(false)}>Cancel</button>
    </span>
  );
}
