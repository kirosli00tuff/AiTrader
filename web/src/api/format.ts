// Shared display formatters. Money, percent, signed values, timestamps.
// Timestamps arrive from the backend as ISO-8601 UTC and are rendered in the
// operator's display timezone (default America/Vancouver) with a short zone label
// like "7:45 PM PDT". Storage stays UTC; this is display-only. The zone is read
// from the shared tz store so no component hardcodes it.
import { getDisplayTimeZone } from "./tz";

export function money(x: number | null | undefined): string {
  const v = Number(x ?? 0);
  const sign = v < 0 ? "-" : "";
  return `${sign}$${Math.abs(v).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

// SIGNED percent for a value that is ALREADY a percentage, e.g. a daily PnL of
// -1.5 rendering as "-1.50%". The sign is the point: a PnL reader needs the
// direction before the magnitude. Do not pass a fraction to this.
export function pct(x: number | null | undefined): string {
  const v = Number(x ?? 0);
  return `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`;
}

// A SHARE, given as a fraction in [0,1], rendered as a plain percent: 0.30 to
// "30%". Distinct from pct() on both counts, and both differences matter.
//
// The sleeve panel used pct() for its targets, which are fractions, so a 30
// percent satellite target rendered as "+0.30%" and its 35 percent hard cap as
// "+0.35%". An operator reading that saw a third of one percent: off by 100x,
// carrying a sign that means nothing on an allocation. A share is never
// negative, so it takes no sign, and it is scaled where a PnL percent is not.
export function sharePct(x: number | null | undefined, digits = 0): string {
  const v = Number(x ?? 0) * 100;
  return `${v.toFixed(digits)}%`;
}

export function num(x: number | null | undefined, digits = 4): string {
  if (x === null || x === undefined) return "—";
  return Number(x).toLocaleString("en-US", { maximumFractionDigits: digits });
}

export function signClass(x: number | null | undefined): string {
  const v = Number(x ?? 0);
  return v > 0 ? "pos" : v < 0 ? "neg" : "muted";
}

// Date + time with a short zone label, e.g. "Jul 15, 7:45 PM PDT". `tz` defaults
// to the operator's display timezone; tests pass an explicit zone.
export function shortTs(
  ts: string | null | undefined,
  tz: string = getDisplayTimeZone(),
): string {
  if (!ts) return "—";
  const d = new Date(ts.endsWith("Z") ? ts : `${ts}Z`);
  if (Number.isNaN(d.getTime())) return ts;
  return d.toLocaleString("en-US", {
    month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
    hour12: true, timeZone: tz, timeZoneName: "short",
  });
}

// Time only with a short zone label, e.g. "7:45 PM PDT". `tz` defaults to the
// operator's display timezone; tests pass an explicit zone.
export function clockTs(
  ts: string | null | undefined,
  tz: string = getDisplayTimeZone(),
): string {
  if (!ts) return "—";
  const d = new Date(ts.endsWith("Z") ? ts : `${ts}Z`);
  if (Number.isNaN(d.getTime())) return ts;
  return d.toLocaleTimeString("en-US", {
    hour: "numeric", minute: "2-digit", hour12: true,
    timeZone: tz, timeZoneName: "short",
  });
}
