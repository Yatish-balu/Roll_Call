/**
 * React binding for the SWR-style API cache (services/api/cache.ts).
 *
 * `useResource(key, fetcher)` gives a view its data through the shared cache:
 *
 * - Tab switch remount renders the cached data instantly (no loading flash)
 *   and, if it is older than `staleTime`, revalidates in the background while
 *   the cached copy stays on screen.
 * - In-flight requests are deduplicated per key, so two components reading
 *   the same endpoint share one network call.
 * - Dependencies: the effect only depends on `key`, never on the (possibly
 *   recreated each render) fetcher, so there are no duplicate-fetch loops.
 *   Filter changes simply produce a new key.
 * - `refresh()` forces a revalidation (manual Refresh buttons); `invalidate`
 *   (from the cache module) is used after mutations to refresh only the
 *   affected keys.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import {
  DEFAULT_STALE_TIME_MS,
  getCached,
  revalidate,
  subscribeCache,
  type CacheEntry,
} from "@/services/api/cache";

export interface UseResourceResult<T> {
  /** Cached (or freshly fetched) data. `undefined` only before the first success. */
  data: T | undefined;
  /** True while there is no data yet and the first fetch is running. */
  isLoading: boolean;
  /** True while a background revalidation runs on top of visible data. */
  isRefreshing: boolean;
  /** Latest fetch error (cached data is kept on refetch failures). */
  error: unknown | null;
  /** Force a background revalidation (manual refresh buttons). */
  refresh: () => void;
}

export function useResource<T>(
  key: string | null,
  fetcher: () => Promise<T>,
  options: { staleTime?: number; enabled?: boolean } = {}
): UseResourceResult<T> {
  const staleTime = options.staleTime ?? DEFAULT_STALE_TIME_MS;
  const enabled = options.enabled ?? true;

  // The fetcher may be recreated every render (inline closures); keep it in a
  // ref so the mount/subscribe effect below can stay dependency-clean.
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  const [entry, setEntry] = useState<CacheEntry<T> | undefined>(() =>
    key && enabled ? (getCached<T>(key) ?? undefined) : undefined
  );

  // Re-render when the store changes for this key (revalidation finished,
  // another component refreshed the key, or a mutation invalidated it).
  useEffect(() => {
    if (!key || !enabled) {
      setEntry(undefined);
      return;
    }
    setEntry(getCached<T>(key) ?? undefined);
    const unsubscribe = subscribeCache(key, () => setEntry(getCached<T>(key) ?? undefined));
    return unsubscribe;
  }, [key, enabled]);

  // Data resolution: fetch when missing, revalidate in the background when
  // stale. Runs on mount, key change, and after invalidation marks the entry
  // stale (subscribeCache fires, this effect does not re-run, so the hook's
  // handler below also kicks a refetch for stale entries).
  useEffect(() => {
    if (!key || !enabled) return;
    const current = getCached<T>(key);
    if (!current || (current.data === undefined && !current.promise)) {
      void revalidate(key, fetcherRef.current, { staleTime });
    } else if (
      current.data !== undefined &&
      !current.promise &&
      Date.now() - current.fetchedAt > staleTime
    ) {
      void revalidate(key, fetcherRef.current, { staleTime });
    }
  }, [key, enabled, staleTime]);

  // Stale-marking (invalidation) happens while this component is already
  // mounted; the effect above will not re-run, so handle it here.
  useEffect(() => {
    if (!key || !enabled || !entry) return;
    if (
      entry.fetchedAt === 0 &&
      entry.data !== undefined &&
      !entry.promise
    ) {
      void revalidate(key, fetcherRef.current, { staleTime });
    }
  }, [key, enabled, staleTime, entry]);

  const refresh = useCallback(() => {
    if (key && enabled) {
      void revalidate(key, fetcherRef.current, { staleTime, force: true });
    }
  }, [key, enabled, staleTime]);

  const isLoading = !!key && enabled && entry !== undefined
    ? entry.data === undefined && !entry.error && entry.promise !== null
    : !!key && enabled;
  const isRefreshing = !!entry && entry.data !== undefined && entry.promise !== null;

  return {
    data: entry?.data,
    isLoading,
    isRefreshing,
    error: entry?.error ?? null,
    refresh,
  };
}
