import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { fetchHealth, type HealthResponse } from "@/lib/api";
import { CapabilitiesContext, deriveCapabilities } from "@/lib/capabilities";

/**
 * Loads GET /health once at startup and again on demand (retry buttons).
 * The first request is the cheap one (last probe result) so the app renders
 * fast; a deep probe follows in the background to refresh reachability.
 */
export function CapabilitiesProvider({ children }: { children: ReactNode }) {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [unreachable, setUnreachable] = useState(false);
  const [checking, setChecking] = useState(false);

  const load = useCallback(async (deep: boolean) => {
    try {
      const h = await fetchHealth(deep);
      setHealth(h);
      setUnreachable(false);
    } catch {
      setUnreachable(true);
    }
  }, []);

  useEffect(() => {
    let alive = true;
    (async () => {
      await load(false);
      if (!alive) return;
      setLoading(false);
      await load(true);
    })();
    return () => {
      alive = false;
    };
  }, [load]);

  const refresh = useCallback(async () => {
    setChecking(true);
    await load(true);
    setChecking(false);
  }, [load]);

  const value = useMemo(
    () => ({
      health,
      loading,
      unreachable,
      checking,
      caps: deriveCapabilities(health),
      refresh,
    }),
    [health, loading, unreachable, checking, refresh],
  );

  return <CapabilitiesContext.Provider value={value}>{children}</CapabilitiesContext.Provider>;
}
