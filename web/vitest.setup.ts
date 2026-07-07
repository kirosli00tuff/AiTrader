import "@testing-library/jest-dom/vitest";

// jsdom has no WebSocket. Provide a no-op stub so components that open a
// stream in tests never touch the network. Page tests also mock the stream
// hook directly, so this is only a safety net.
class MockWebSocket {
  onopen: (() => void) | null = null;
  onmessage: ((ev: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  readyState = 1;
  constructor(public url: string) {}
  send(_data: string): void {}
  close(): void {}
}
// @ts-expect-error assign test stub
globalThis.WebSocket = MockWebSocket;
