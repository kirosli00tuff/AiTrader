// Display timezone for every timestamp the GUI renders. This is a display-only
// preference: storage, the engine, logs, and the events table all stay ISO-8601
// UTC. The value is an IANA zone name (not a fixed offset), so DST (PST vs PDT)
// switches automatically. Default America/Vancouver. Persisted in localStorage so
// it never reaches the backend, YAML, or the database (writes no operational
// value). Components read it through useDisplayTimeZone; the pure formatters in
// format.ts read getDisplayTimeZone() so timestamps are never hardcoded per zone.
import { useSyncExternalStore } from "react";

export const DEFAULT_DISPLAY_TZ = "America/Vancouver";
const STORAGE_KEY = "aitrader.displayTimeZone";

// Curated IANA options for the Settings selector. Each name carries its own DST
// rules, so the short label (PST/PDT, EST/EDT, ...) follows the date.
export const DISPLAY_TZ_OPTIONS: ReadonlyArray<{ zone: string; label: string }> = [
  { zone: "America/Vancouver", label: "Vancouver (Pacific)" },
  { zone: "America/Denver", label: "Denver (Mountain)" },
  { zone: "America/Chicago", label: "Chicago (Central)" },
  { zone: "America/New_York", label: "New York (Eastern)" },
  { zone: "UTC", label: "UTC" },
  { zone: "Europe/London", label: "London" },
  { zone: "Asia/Tokyo", label: "Tokyo" },
];

// True when the runtime accepts the zone name (guards a bad stored/selected value).
export function isValidTimeZone(zone: string): boolean {
  if (!zone) return false;
  try {
    new Intl.DateTimeFormat("en-US", { timeZone: zone });
    return true;
  } catch {
    return false;
  }
}

function readStored(): string {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    if (v && isValidTimeZone(v)) return v;
  } catch {
    // localStorage may be unavailable (private mode, SSR); fall back to default.
  }
  return DEFAULT_DISPLAY_TZ;
}

let current = readStored();
const listeners = new Set<() => void>();

export function getDisplayTimeZone(): string {
  return current;
}

// Set the display timezone and notify subscribers. An invalid zone is ignored so
// a bad selection can never break rendering. Persists to localStorage only.
export function setDisplayTimeZone(zone: string): void {
  if (!isValidTimeZone(zone) || zone === current) return;
  current = zone;
  try {
    localStorage.setItem(STORAGE_KEY, zone);
  } catch {
    // Non-fatal: the in-memory value still updates for this session.
  }
  for (const l of listeners) l();
}

function subscribe(cb: () => void): () => void {
  listeners.add(cb);
  return () => {
    listeners.delete(cb);
  };
}

// Subscribe a component to the display timezone so it re-renders when the operator
// changes it in Settings.
export function useDisplayTimeZone(): string {
  return useSyncExternalStore(subscribe, getDisplayTimeZone, getDisplayTimeZone);
}
