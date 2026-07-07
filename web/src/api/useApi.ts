import { useCallback, useEffect, useRef, useState } from "react";

export interface ApiState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  reload: () => void;
}

// Fetch on mount and re-fetch on a fixed poll interval. Cancels stale updates
// after unmount. Errors surface as a message; loading is only true on first load.
export function useApi<T>(
  fn: () => Promise<T>,
  pollMs = 0,
  deps: unknown[] = [],
): ApiState<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const alive = useRef(true);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const run = useCallback(fn, deps);

  const load = useCallback(async () => {
    try {
      const d = await run();
      if (alive.current) {
        setData(d);
        setError(null);
      }
    } catch (e) {
      if (alive.current) setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (alive.current) setLoading(false);
    }
  }, [run]);

  useEffect(() => {
    alive.current = true;
    load();
    if (pollMs > 0) {
      const id = setInterval(load, pollMs);
      return () => {
        alive.current = false;
        clearInterval(id);
      };
    }
    return () => {
      alive.current = false;
    };
  }, [load, pollMs]);

  return { data, loading, error, reload: load };
}
