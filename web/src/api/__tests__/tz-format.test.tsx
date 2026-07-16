import { render, screen, act } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { clockTs, shortTs } from "../format";
import {
  DEFAULT_DISPLAY_TZ,
  getDisplayTimeZone,
  setDisplayTimeZone,
  useDisplayTimeZone,
} from "../tz";

// Reset to the default zone between tests so the module-level store never leaks.
function resetZone() {
  try {
    localStorage.removeItem("aitrader.displayTimeZone");
  } catch {
    // ignore
  }
  setDisplayTimeZone(DEFAULT_DISPLAY_TZ);
}
afterEach(resetZone);

describe("timestamp display formatting", () => {
  it("converts a UTC timestamp to Vancouver local time with a PDT label in summer", () => {
    // 2026-07-16T02:45:00Z == 2026-07-15 19:45 in Vancouver (PDT, UTC-7).
    const out = clockTs("2026-07-16T02:45:00Z", "America/Vancouver");
    expect(out).toContain("7:45");
    expect(out).toContain("PM");
    expect(out).toContain("PDT");
  });

  it("converts a UTC timestamp to Vancouver local time with a PST label in winter", () => {
    // 2026-01-16T03:45:00Z == 2026-01-15 19:45 in Vancouver (PST, UTC-8).
    const out = clockTs("2026-01-16T03:45:00Z", "America/Vancouver");
    expect(out).toContain("7:45");
    expect(out).toContain("PM");
    expect(out).toContain("PST");
  });

  it("defaults the display zone to America/Vancouver", () => {
    expect(getDisplayTimeZone()).toBe("America/Vancouver");
    // The default-zone formatter matches the explicit-Vancouver result.
    expect(clockTs("2026-07-16T02:45:00Z")).toBe(
      clockTs("2026-07-16T02:45:00Z", "America/Vancouver"),
    );
  });

  it("shortTs carries the date and the short zone label", () => {
    const out = shortTs("2026-07-16T02:45:00Z", "America/Vancouver");
    expect(out).toContain("Jul");
    expect(out).toContain("15");
    expect(out).toContain("PDT");
  });
});

// A minimal component that renders a UTC timestamp through the shared formatter and
// subscribes to the display zone, so a zone change re-renders it (like a page does).
function Clock({ ts }: { ts: string }) {
  useDisplayTimeZone();
  return <span>{clockTs(ts)}</span>;
}

describe("display-timezone selector", () => {
  it("renders the converted time and re-renders when the zone changes", () => {
    // 2026-07-16T02:45:00Z: 19:45 PDT in Vancouver, 02:45 in UTC.
    render(<Clock ts="2026-07-16T02:45:00Z" />);
    expect(screen.getByText(/7:45 PM PDT/)).toBeTruthy();
    act(() => setDisplayTimeZone("UTC"));
    expect(screen.getByText(/2:45 AM UTC/)).toBeTruthy();
    expect(getDisplayTimeZone()).toBe("UTC");
  });

  it("ignores an invalid zone and keeps the current one", () => {
    setDisplayTimeZone("Not/AZone");
    expect(getDisplayTimeZone()).toBe(DEFAULT_DISPLAY_TZ);
  });
});
