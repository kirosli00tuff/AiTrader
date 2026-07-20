import { useEffect, useRef, useState } from "react";
import { api, WS_BASE } from "./client";
import type { ActivityEvent } from "./types";

const BACKFILL_LIMIT = 400;
const MAX_KEPT = 3000; // bounded memory; groups keep their counts regardless

interface StreamFrame {
  events_delta?: ActivityEvent[];
  latest_event_id?: number;
}

export interface ActivityState {
  events: ActivityEvent[]; // ascending by id, deduplicated, never dropped
  connected: boolean;
}

// Live event feed: one REST backfill for history, then the WebSocket's
// events_delta appended each tick. Every event has a server-assigned id, so
// dedup is exact and a gap (missed frames while reconnecting) is repaired by
// fetching /activity?since_id= the last id we hold. Events are grouped by the
// views, never dropped here.
export function useActivity(): ActivityState {
  const [events, setEvents] = useState<ActivityEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const lastId = useRef(0);

  const append = (incoming: ActivityEvent[]) => {
    if (!incoming.length) return;
    setEvents((prev) => {
      const fresh = incoming.filter((e) => e.id > lastId.current);
      if (!fresh.length) return prev;
      lastId.current = fresh[fresh.length - 1].id;
      const next = [...prev, ...fresh];
      return next.length > MAX_KEPT ? next.slice(next.length - MAX_KEPT) : next;
    });
  };

  useEffect(() => {
    let stopped = false;
    let retry: ReturnType<typeof setTimeout> | null = null;
    let ws: WebSocket | null = null;

    api.activity(0, BACKFILL_LIMIT)
      .then((r) => { if (!stopped) append(r.events); })
      .catch(() => { /* backfill retries implicitly via gap repair */ });

    const connect = () => {
      if (stopped) return;
      ws = new WebSocket(`${WS_BASE}/stream`);
      ws.onopen = () => { setConnected(true); ws?.send("paper"); };
      ws.onmessage = (ev) => {
        try {
          const frame = JSON.parse(ev.data) as StreamFrame;
          const delta = frame.events_delta ?? [];
          // Gap repair: the frame continues from what the SERVER last sent
          // this connection. If our history ends earlier (a reconnect), pull
          // the missed span over REST so nothing is dropped.
          if (delta.length && lastId.current > 0 &&
              delta[0].id > lastId.current + 1) {
            api.activity(lastId.current, BACKFILL_LIMIT)
              .then((r) => append(r.events))
              .catch(() => { /* next frame retries */ });
          }
          append(delta);
        } catch { /* ignore malformed frame */ }
      };
      ws.onclose = () => {
        setConnected(false);
        if (!stopped) retry = setTimeout(connect, 2000);
      };
      ws.onerror = () => ws?.close();
    };
    connect();
    return () => {
      stopped = true;
      if (retry) clearTimeout(retry);
      ws?.close();
    };
  }, []);

  return { events, connected };
}
