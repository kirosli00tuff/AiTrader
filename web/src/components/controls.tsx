import { useState } from "react";

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
