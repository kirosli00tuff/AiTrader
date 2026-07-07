// Shared display formatters. Money, percent, signed values, timestamps.
export function money(x: number | null | undefined): string {
  const v = Number(x ?? 0);
  const sign = v < 0 ? "-" : "";
  return `${sign}$${Math.abs(v).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

export function pct(x: number | null | undefined): string {
  const v = Number(x ?? 0);
  return `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`;
}

export function num(x: number | null | undefined, digits = 4): string {
  if (x === null || x === undefined) return "—";
  return Number(x).toLocaleString("en-US", { maximumFractionDigits: digits });
}

export function signClass(x: number | null | undefined): string {
  const v = Number(x ?? 0);
  return v > 0 ? "pos" : v < 0 ? "neg" : "muted";
}

export function shortTs(ts: string | null | undefined): string {
  if (!ts) return "—";
  const d = new Date(ts.endsWith("Z") ? ts : `${ts}Z`);
  if (Number.isNaN(d.getTime())) return ts;
  return d.toLocaleString("en-US", {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

export function clockTs(ts: string | null | undefined): string {
  if (!ts) return "—";
  const d = new Date(ts.endsWith("Z") ? ts : `${ts}Z`);
  if (Number.isNaN(d.getTime())) return ts;
  return d.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" });
}
