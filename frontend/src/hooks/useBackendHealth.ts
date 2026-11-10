"use client";

import { useCallback, useEffect, useState } from "react";
import { checkBackendHealth } from "@/services/api";
import type { HealthCheckResponse } from "@/types/api";

export interface BackendHealthState {
  data: HealthCheckResponse | null;
  isLoading: boolean;
  isOnline: boolean;
  error: string | null;
  lastChecked: Date | null;
  refetch: () => Promise<void>;
}

export function useBackendHealth(): BackendHealthState {
  const [data, setData] = useState<HealthCheckResponse | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [isOnline, setIsOnline] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [lastChecked, setLastChecked] = useState<Date | null>(null);

  const fetchHealth = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const response = await checkBackendHealth();
      setData(response);
      setIsOnline(true);
      setError(null);
    } catch (err) {
      setData(null);
      setIsOnline(false);
      setError(err instanceof Error ? err.message : "Backend unreachable");
    } finally {
      setIsLoading(false);
      setLastChecked(new Date());
    }
  }, []);

  useEffect(() => {
    let isCancelled = false;

    async function initialProbe() {
      try {
        const response = await checkBackendHealth();
        if (!isCancelled) {
          setData(response);
          setIsOnline(true);
          setError(null);
        }
      } catch (err) {
        if (!isCancelled) {
          setData(null);
          setIsOnline(false);
          setError(err instanceof Error ? err.message : "Backend unreachable");
        }
      } finally {
        if (!isCancelled) {
          setIsLoading(false);
          setLastChecked(new Date());
        }
      }
    }

    void initialProbe();

    return () => {
      isCancelled = true;
    };
  }, []);

  return {
    data,
    isLoading,
    isOnline,
    error,
    lastChecked,
    refetch: fetchHealth,
  };
}
