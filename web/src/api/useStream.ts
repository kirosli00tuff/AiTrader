import { useEffect, useRef, useState } from "react";
import { WS_BASE } from "./client";
import type { Mode, Snapshot } from "./types";

export interface StreamState {
  snapshot: Snapshot | null;
  connected: boolean;
}

// Subscribe to the backend /stream WebSocket for a given mode. Sends the mode
// once on open, then applies each pushed snapshot. Reconnects on close.
export function useStream(mode: Mode): StreamState {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    let stopped = false;
    let retry: ReturnType<typeof setTimeout> | null = null;

    const connect = () => {
      if (stopped) return;
      const ws = new WebSocket(`${WS_BASE}/stream`);
      wsRef.current = ws;
      ws.onopen = () => {
        setConnected(true);
        ws.send(mode);
      };
      ws.onmessage = (ev) => {
        try {
          setSnapshot(JSON.parse(ev.data) as Snapshot);
        } catch {
          /* ignore malformed frame */
        }
      };
      ws.onclose = () => {
        setConnected(false);
        if (!stopped) retry = setTimeout(connect, 2500);
      };
      ws.onerror = () => ws.close();
    };

    connect();
    return () => {
      stopped = true;
      if (retry) clearTimeout(retry);
      wsRef.current?.close();
    };
  }, [mode]);

  return { snapshot, connected };
}
