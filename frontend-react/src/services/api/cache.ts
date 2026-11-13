/**
 * Lightweight stale-while-revalidate (SWR) data cache for API reads.
 *
 * Purpose: switching between tabs (routes) unmounts and remounts views; every
 * view used to re-run its GET requests on mount, so each tab switch repeated
 * identical network calls. This module provides a shared, module-level cache
 * keyed by "endpoint + serialized params" so that:
 *
 *   1. A tab mount immediately renders cached data (no loading flash), and
 *   2. Stale entries (> staleTime, default 60 s) are revalidated in the
 *      background while the cached data stays on screen.
 *
 * In-flight requests are deduplicated per key. Mutations call `invalidate`
 * with endpoint prefixes so only the affected keys are refreshed - never
 * every dataset at once. `clearApiCache()` drops everything (logout / user
 * switch) so cached data can never leak across accounts.
 *
 * This is intentionally dependency-free (React Query/SWR are not installed)
 * and small: ~150 lines, no timers, no persistence.
 */

export const DEFAULT_STALE_TIME_MS = 60_000;

export interface CacheEntry<T = unknown> {
  /** Latest successfully fetched data (undefined until the first success). */
  data: T | undefined;
  /** Latest fetch error, cleared on the next successful fetch. */
  error: unknown | null;
  /** Epoch ms of the last successful fetch; 0 = invalidated (needs refetch). */
  fetchedAt: number;
  /** In-flight revalidation promise (deduplicates concurrent callers). */
  promise: Promise<void> | null;
}

type Listener = () => void;

const store = new Map<string, CacheEntry>();
const listeners = new Map<string, Set<Listener>>();
const anyListener = new Set<Listener>();

function notify(key: string): void {
  const set = listeners.get(key);
  if (set) {
    for (const fn of set) {
      try {
        fn();
      } catch {
        // A listener error must never break the fetch pipeline.
      }
    }
  }
  for (const fn of anyListener) {
    try {
      fn();
    } catch {
      // ignore
    }
  }
}

/**
 * Build a stable cache key from an endpoint URL and its query params.
 * Param order does not matter; undefined/null params are dropped.
 */
export function resolveCacheKey(
  url: string,
  params?: Record<string, string | number | boolean | undefined | null>
): string {
  if (!params) return url;
  const parts = Object.keys(params)
    .filter((k) => params[k] !== undefined && params[k] !== null)
    .sort()
    .map((k) => `${k}=${String(params[k])}`);
  return parts.length ? `${url}?${parts.join("&")}` : url;
}

export function getCached<T = unknown>(key: string): CacheEntry<T> | undefined {
  return store.get(key) as CacheEntry<T> | undefined;
}

export function isStale(entry: CacheEntry, staleTime: number): boolean {
  return Date.now() - entry.fetchedAt > staleTime;
}

/**
 * Revalidate one key. Behaviour:
 * - No entry yet (or only a previous error, no data): fetch now (loading).
 * - Fresh data: no-op.
 * - Stale data: background refetch; cached data stays visible meanwhile.
 * - `force` skips the staleness check (manual refresh button).
 * Concurrent revalidations of the same key are deduplicated.
 */
export function revalidate<T>(
  key: string,
  fetcher: () => Promise<T>,
  options: { staleTime?: number; force?: boolean } = {}
): Promise<T | undefined> {
  const staleTime = options.staleTime ?? DEFAULT_STALE_TIME_MS;
  const entry = store.get(key) as CacheEntry<T> | undefined;

  if (
    !options.force &&
    entry &&
    entry.data !== undefined &&
    !isStale(entry, staleTime) &&
    !entry.promise
  ) {
    return Promise.resolve(entry.data);
  }
  if (entry?.promise) {
    return entry.promise.then(() => (store.get(key) as CacheEntry<T> | undefined)?.data);
  }

  const run = async () => {
    try {
      const data = await fetcher();
      store.set(key, {
        data,
        error: null,
        fetchedAt: Date.now(),
        promise: null,
      });
    } catch (err) {
      const current = store.get(key) as CacheEntry<T> | undefined;
      // Keep previously cached data on refetch failures (SWR behaviour);
      // only record the error so the UI can surface it.
      store.set(key, {
        data: current?.data,
        error: err,
        fetchedAt: current?.data !== undefined ? current.fetchedAt : 0,
        promise: null,
      });
    }
    notify(key);
  };

  const promise = run();
  store.set(key, {
    data: entry?.data,
    error: entry?.error ?? null,
    fetchedAt: entry?.fetchedAt ?? 0,
    promise,
  });

  return promise.then(() => (store.get(key) as CacheEntry<T> | undefined)?.data);
}

/**
 * Locally patch cached data without a network round-trip (optimistic
 * updates). Accepts the new value directly or an updater function.
 */
export function mutateCache<T>(key: string, value: T | ((prev: T | undefined) => T)): void {
  const current = store.get(key) as CacheEntry<T> | undefined;
  const next =
    typeof value === "function" ? (value as (prev: T | undefined) => T)(current?.data) : value;
  store.set(key, {
    data: next,
    error: null,
    fetchedAt: Date.now(),
    promise: current?.promise ?? null,
  });
  notify(key);
}

/**
 * Mark matching keys as stale and let the subscribed hooks refetch them in
 * the background (cached data stays on screen until fresh data arrives).
 * Matchers are key prefixes: `invalidate("sessions")` refreshes every
 * `/api/v1/sessions...` key. Pass several prefixes for multi-dataset
 * mutations, or a predicate for exact control.
 */
export function invalidate(
  matchers: string | string[] | ((key: string) => boolean)
): void {
  const predicate: (key: string) => boolean =
    typeof matchers === "function"
      ? matchers
      : (key: string) => {
          const list = Array.isArray(matchers) ? matchers : [matchers];
          return list.some((prefix) => key.startsWith(prefix));
        };

  const keys = [...store.keys()].filter(predicate);
  for (const key of keys) {
    const entry = store.get(key)!;
    if (entry.promise) continue; // already refetching
    store.set(key, { ...entry, fetchedAt: 0 });
    notify(key);
  }
}

/** Subscribe to changes of one key (or every key when key is null). */
export function subscribeCache(key: string | null, fn: Listener): () => void {
  if (key === null) {
    anyListener.add(fn);
    return () => anyListener.delete(fn);
  }
  let set = listeners.get(key);
  if (!set) {
    set = new Set();
    listeners.set(key, set);
  }
  set.add(fn);
  return () => {
    set!.delete(fn);
    if (set!.size === 0) listeners.delete(key);
  };
}

/** Drop the whole cache (logout / user switch). */
export function clearApiCache(): void {
  store.clear();
  for (const key of [...listeners.keys()]) notify(key);
}
