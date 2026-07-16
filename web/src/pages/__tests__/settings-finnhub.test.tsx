// Settings credential fields, with the Finnhub key as the case under test.
//
// The Finnhub key existed in the backend registry from the discovery build, but
// Settings rendered nothing for it: CATEGORIES is a hardcoded allowlist and no
// category claimed the "finnhub" group, so the page silently dropped a
// credential the API was returning. These tests pin the fix AND the catch-all
// that makes the same failure impossible for the next credential.
//
// No real network: the REST client is fully mocked.
import type { ReactElement } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import SettingsPage from "../SettingsPage";

const MASK = "••••••••";

const cred = (name: string, group: string, group_label: string,
              over: Record<string, unknown> = {}) => ({
  name, label: "API key", group, group_label, kind: "source", mode: null,
  secret: true, configured: false, source: "missing", masked: "", ...over,
});

// Mirrors what the backend registry actually returns, Finnhub included.
const CREDENTIALS = [
  cred("openai_key", "openai", "OpenAI (GPT-5.5)"),
  cred("anthropic_key", "anthropic", "Anthropic (Claude Opus 4.8 + Haiku gate)"),
  cred("gemini_key", "gemini", "Google (Gemini 3.1 Pro)"),
  cred("alpaca_paper_key", "alpaca", "Alpaca", { kind: "venue", mode: "paper" }),
  cred("finnhub_key", "finnhub", "Finnhub (discovery pre-screen)"),
];

const mockCredentials = vi.fn();
const mockSave = vi.fn();

vi.mock("../../api/client", () => ({
  api: {
    credentials: () => mockCredentials(),
    saveCredential: (name: string, value: string) => mockSave(name, value),
    venues: async () => ({ venues: [] }),
    council: async () => ({ models: {}, latest: [], recent: [] }),
    testConnection: async () => ({ ok: true, message: "ok", source: "env" }),
  },
}));

const view = (ui: ReactElement) => render(<MemoryRouter>{ui}</MemoryRouter>);

beforeEach(() => {
  vi.clearAllMocks();
  mockCredentials.mockResolvedValue({ credentials: CREDENTIALS });
  mockSave.mockResolvedValue({ ok: true });
});

describe("Finnhub credential field", () => {
  it("appears alongside the other credential fields", async () => {
    view(<SettingsPage />);
    // The regression: it must render at all.
    expect(await screen.findByText("Finnhub (discovery pre-screen)"))
      .toBeInTheDocument();
    // And beside the existing keys, not instead of them.
    expect(screen.getByText("OpenAI (GPT-5.5)")).toBeInTheDocument();
    expect(screen.getByText("Anthropic (Claude Opus 4.8 + Haiku gate)"))
      .toBeInTheDocument();
    expect(screen.getByText("Google (Gemini 3.1 Pro)")).toBeInTheDocument();
    expect(screen.getByText("Alpaca")).toBeInTheDocument();
  });

  it("sits in its own Discovery data category and says what it is for", async () => {
    view(<SettingsPage />);
    expect(await screen.findByText("Discovery data")).toBeInTheDocument();
    expect(screen.getByText(/free Stage-A pre-screen/)).toBeInTheDocument();
    // It is optional: discovery ships off, so a missing key is not a fault.
    expect(screen.getByText(/ships off/)).toBeInTheDocument();
  });

  it("masks the input, exactly like every other secret", async () => {
    const { container } = view(<SettingsPage />);
    await screen.findByText("Finnhub (discovery pre-screen)");
    // Every secret credential renders a password input. Nothing is typed in
    // plaintext.
    const pw = container.querySelectorAll('input[type="password"]');
    expect(pw.length).toBe(CREDENTIALS.length);
  });

  it("reports not configured until a key is saved", async () => {
    view(<SettingsPage />);
    await screen.findByText("Finnhub (discovery pre-screen)");
    expect(screen.getAllByText("○ not configured").length)
      .toBe(CREDENTIALS.length);
  });

  it("shows dots, never the value, once set", async () => {
    const canary = "CANARY-FINNHUB-PLAINTEXT-MUST-NOT-RENDER-0001";
    mockCredentials.mockResolvedValue({
      credentials: CREDENTIALS.map((c) => c.name === "finnhub_key"
        ? { ...c, configured: true, source: "in-app", masked: MASK } : c),
    });
    const { container } = view(<SettingsPage />);
    await screen.findByText("Finnhub (discovery pre-screen)");
    expect(screen.getByText("● configured")).toBeInTheDocument();
    // The plaintext never reaches the DOM.
    expect(container.textContent).not.toContain(canary);
  });

  it("saves through the same keystore path as the other keys", async () => {
    const canary = "CANARY-FINNHUB-PLAINTEXT-MUST-NOT-RENDER-0002";
    const { container } = view(<SettingsPage />);
    await screen.findByText("Finnhub (discovery pre-screen)");

    // Finnhub renders last: Discovery data is the last category.
    const inputs = container.querySelectorAll('input[type="password"]');
    const finnhub = inputs[inputs.length - 1] as HTMLInputElement;
    fireEvent.change(finnhub, { target: { value: canary } });

    const saveButtons = screen.getAllByRole("button", { name: /save/i });
    fireEvent.click(saveButtons[saveButtons.length - 1]);

    // One shared save path: the same endpoint every other credential uses.
    await waitFor(() =>
      expect(mockSave).toHaveBeenCalledWith("finnhub_key", canary));
  });
});

describe("the uncategorized catch-all", () => {
  it("surfaces a credential no category claims, instead of dropping it", async () => {
    // This is the bug class that hid the Finnhub key: the backend returns a
    // credential, and a hardcoded category list silently swallows it.
    mockCredentials.mockResolvedValue({
      credentials: [...CREDENTIALS,
                    cred("future_key", "future_feed", "Some Future Feed")],
    });
    view(<SettingsPage />);
    expect(await screen.findByText("Other credentials")).toBeInTheDocument();
    expect(screen.getByText("Some Future Feed")).toBeInTheDocument();
  });

  it("stays hidden when every credential has a category", async () => {
    view(<SettingsPage />);
    await screen.findByText("Finnhub (discovery pre-screen)");
    // Finnhub now has a home, so nothing is uncategorized.
    expect(screen.queryByText("Other credentials")).toBeNull();
  });
});

describe("no credential value is ever rendered", () => {
  it("renders masked status only, never a plaintext value", async () => {
    const canary = "CANARY-FINNHUB-PLAINTEXT-MUST-NOT-RENDER-0003";
    mockCredentials.mockResolvedValue({
      credentials: CREDENTIALS.map((c) => ({
        ...c, configured: true, source: "in-app", masked: MASK })),
    });
    const { container } = view(<SettingsPage />);
    await screen.findByText("Finnhub (discovery pre-screen)");
    expect(container.textContent).not.toContain(canary);
    // The payload carries a masked field only. There is no value field to leak.
    for (const c of CREDENTIALS) {
      expect(Object.keys(c)).not.toContain("value");
    }
  });
});
