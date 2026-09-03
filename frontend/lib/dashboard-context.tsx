"use client";

import { createContext, useContext, useEffect, useState } from "react";
import { getDashboardSnapshot } from "@/lib/api";
import type { DashboardSnapshot } from "@/lib/types";

interface DashboardContextValue {
  snapshot: DashboardSnapshot | null;
  loading: boolean;
  error: string | null;
  refresh: () => void;
}

const DashboardContext = createContext<DashboardContextValue>({
  snapshot: null,
  loading: true,
  error: null,
  refresh: () => undefined,
});

export function DashboardProvider({ children }: { children: React.ReactNode }) {
  const [snapshot, setSnapshot] = useState<DashboardSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    const ctrl = new AbortController();
    let ignore = false;
    setLoading(true);
    getDashboardSnapshot(ctrl.signal)
      .then((value) => {
        if (ignore) return;
        setSnapshot(value);
        setError(null);
      })
      .catch((err: unknown) => {
        if (ignore) return;
        setSnapshot(null);
        setError(err instanceof Error ? err.message : "Dashboard adapter unavailable.");
      })
      .finally(() => {
        if (!ignore) setLoading(false);
      });
    return () => {
      ignore = true;
      ctrl.abort();
    };
  }, [version]);

  return (
    <DashboardContext.Provider value={{ snapshot, loading, error, refresh: () => setVersion((v) => v + 1) }}>
      {children}
    </DashboardContext.Provider>
  );
}

export function useDashboard() {
  return useContext(DashboardContext);
}
