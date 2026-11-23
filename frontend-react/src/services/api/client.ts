/**
 * Axios-based Centralized API Client for RollCall AI
 * Implements:
 * 1. In-memory access token storage (no localStorage/sessionStorage for access tokens)
 * 2. Automatic Bearer Authorization header injection
 * 3. withCredentials: true for HttpOnly refresh cookies
 * 4. Dynamic base URL resolution matching current browser host
 * 5. Single-flight 401 retry interceptor with token refresh rotation
 */

import axios, {
  type AxiosInstance,
  type AxiosRequestConfig,
  type AxiosResponse,
  type InternalAxiosRequestConfig,
} from "axios";

export interface ApiErrorDetail {
  code: string;
  message: string;
  details?: unknown;
}

export class ApiError extends Error {
  public readonly statusCode: number;
  public readonly code: string;
  public readonly details?: unknown;

  constructor(statusCode: number, code: string, message: string, details?: unknown) {
    super(message);
    this.name = "ApiError";
    this.statusCode = statusCode;
    this.code = code;
    this.details = details;
  }
}

export type RefreshHandler = () => Promise<string | null>;

/**
 * Extra per-request options understood by this client.
 *
 * - `skipCache`: always hit the network (health probes, explicit refresh).
 * - `cacheTtlMs`: override how long a GET response counts as fresh.
 */
export interface ApiRequestConfig extends AxiosRequestConfig {
  skipCache?: boolean;
  cacheTtlMs?: number;
}

interface CacheEntry {
  data: unknown;
  storedAt: number;
}

/** A GET response stays "fresh" for this long and is served without a request. */
const DEFAULT_CACHE_TTL_MS = 60_000;
/**
 * After the fresh window the cached copy is still returned immediately while a
 * background request refreshes it, so switching tabs never blocks on the
 * network. Beyond this age the request waits for the server again.
 */
const MAX_STALE_MS = 15 * 60_000;

function buildCacheKey(
  url: string,
  params?: Record<string, string | number | boolean | undefined | null>
): string {
  if (!params) return url;
  const parts = Object.entries(params)
    .filter(([, value]) => value !== undefined && value !== null)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([key, value]) => `${key}=${String(value)}`);
  return parts.length ? `${url}?${parts.join("&")}` : url;
}

export class ApiClient {
  private readonly axiosInstance: AxiosInstance;
  private accessToken: string | null = null;
  private refreshHandler: RefreshHandler | null = null;
  private readonly getCache = new Map<string, CacheEntry>();
  private readonly getInFlight = new Map<string, Promise<unknown>>();

  constructor() {
    this.axiosInstance = axios.create({
      baseURL: this.getEffectiveBaseUrl(),
      withCredentials: true, // Send HttpOnly refresh cookies
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
        "X-Requested-With": "XMLHttpRequest",
      },
    });

    // Request Interceptor: Attach in-memory token & update baseURL if needed
    this.axiosInstance.interceptors.request.use(
      (config: InternalAxiosRequestConfig) => {
        config.baseURL = this.getEffectiveBaseUrl();
        if (this.accessToken && !config.headers.Authorization) {
          config.headers.Authorization = `Bearer ${this.accessToken}`;
        }
        return config;
      },
      (error) => Promise.reject(error)
    );

    // Response Interceptor: Handle 401 auto-refresh with single-flight rotation via shared refresh handler
    this.axiosInstance.interceptors.response.use(
      (response: AxiosResponse) => response,
      async (error) => {
        const originalRequest = error.config as InternalAxiosRequestConfig & { _retry?: boolean };

        if (
          error.response &&
          error.response.status === 401 &&
          !originalRequest._retry &&
          !originalRequest.url?.includes("/auth/login") &&
          !originalRequest.url?.includes("/auth/refresh")
        ) {
          originalRequest._retry = true;

          try {
            if (this.refreshHandler) {
              const newToken = await this.refreshHandler();
              if (newToken) {
                originalRequest.headers.Authorization = `Bearer ${newToken}`;
                return this.axiosInstance(originalRequest);
              }
            }
          } catch {
            this.setAccessToken(null);
          }
        }

        const status = error.response?.status || 500;
        const data = error.response?.data;
        const code =
          data?.code ||
          (status === 401
            ? "UNAUTHORIZED"
            : status === 403
            ? "FORBIDDEN"
            : status === 429
            ? "RATE_LIMITED"
            : "HTTP_ERROR");
        const rawDetail = data?.detail || data?.message;
        let message: string;
        if (status === 429) {
          const retryHeader = error.response?.headers?.["retry-after"];
          const waitStr = retryHeader
            ? ` Please wait ${retryHeader}s before retrying.`
            : " Please wait a few seconds and try again.";
          message = typeof rawDetail === "string" && rawDetail.trim()
            ? `${rawDetail}.${waitStr}`
            : `Rate limit reached.${waitStr}`;
        } else if (typeof rawDetail === "object" && rawDetail !== null) {
          const anyDetail = rawDetail as Record<string, unknown>;
          message = (anyDetail.message as string) ||
            ((anyDetail.error as Record<string, unknown>)?.message as string) ||
            (Array.isArray(rawDetail) ? rawDetail.map((m: Record<string, unknown>) => (m.msg as string) || JSON.stringify(m)).join("; ") : JSON.stringify(rawDetail));
        } else if (typeof rawDetail === "string" && rawDetail.trim()) {
          message = rawDetail;
        } else {
          message = status === 403
            ? "Access Denied: You do not have permission to perform this action."
            : error.message || "An unexpected error occurred.";
        }

        return Promise.reject(new ApiError(status, code, message, data));
      }
    );
  }

  public setRefreshHandler(handler: RefreshHandler): void {
    this.refreshHandler = handler;
  }

  public setAccessToken(token: string | null): void {
    if (this.accessToken !== token) {
      // Never serve another account's cached responses after a login/logout.
      this.getCache.clear();
      this.getInFlight.clear();
    }
    this.accessToken = token;
  }

  public getAccessToken(): string | null {
    return this.accessToken;
  }

  public getEffectiveBaseUrl(): string {
    if (typeof window !== "undefined") {
      return "";
    }
    return "http://127.0.0.1:8000";
  }

  /**
   * Cached GET with in-flight de-duplication and stale-while-revalidate.
   *
   * Views are mounted/unmounted whenever the user switches tabs, and each
   * mount used to re-issue every request (dashboard alone fires four). Serving
   * the previous response instantly keeps tab navigation snappy; mutations
   * clear the cache so edits are never masked by stale data.
   */
  public async get<T>(
    url: string,
    params?: Record<string, string | number | boolean | undefined | null>,
    config?: ApiRequestConfig
  ): Promise<T> {
    if (config?.skipCache) {
      return this.requestGet<T>(url, params, config);
    }

    const key = buildCacheKey(url, params);
    const ttl = config?.cacheTtlMs ?? DEFAULT_CACHE_TTL_MS;
    const cached = this.getCache.get(key);
    const age = cached ? Date.now() - cached.storedAt : Number.POSITIVE_INFINITY;

    if (cached && age <= ttl) {
      return cached.data as T;
    }

    if (cached && age <= MAX_STALE_MS) {
      // Return immediately and refresh in the background for the next mount.
      void this.requestGet<T>(url, params, config).catch(() => {
        // Keep the cached copy when revalidation fails.
      });
      return cached.data as T;
    }

    return this.requestGet<T>(url, params, config);
  }

  /** Fetch a GET, de-duplicating concurrent identical requests, and cache it. */
  private requestGet<T>(
    url: string,
    params?: Record<string, string | number | boolean | undefined | null>,
    config?: ApiRequestConfig
  ): Promise<T> {
    const key = buildCacheKey(url, params);
    const pending = this.getInFlight.get(key);
    if (pending) {
      return pending as Promise<T>;
    }

    const request = this.axiosInstance
      .get<T>(url, { ...config, params })
      .then((res) => {
        this.getCache.set(key, { data: res.data, storedAt: Date.now() });
        return res.data;
      })
      .finally(() => {
        this.getInFlight.delete(key);
      });

    this.getInFlight.set(key, request);
    return request;
  }

  /**
   * Drop cached GET responses. Call after a mutation or when the server state
   * is known to have changed (e.g. a websocket/custom-event notification).
   */
  public invalidateCache(urlPrefix?: string): void {
    if (!urlPrefix) {
      this.getCache.clear();
      return;
    }
    for (const key of this.getCache.keys()) {
      if (key.startsWith(urlPrefix)) {
        this.getCache.delete(key);
      }
    }
  }

  /**
   * Download a binary response (PDF export, attachment) through the same
   * interceptor chain as every other call: the in-memory access token is
   * attached and a 401 triggers the single-flight refresh/retry. Raw `fetch`
   * cannot do that, which is why downloads must not read any token storage.
   */
  public async getBlob(url: string, config?: AxiosRequestConfig): Promise<Blob> {
    const res = await this.axiosInstance.get<Blob>(url, { ...config, responseType: "blob" });
    return res.data;
  }

  public async post<T>(url: string, data?: unknown, config?: AxiosRequestConfig): Promise<T> {
    let finalConfig = config;

    // Multipart uploads must not carry the instance default
    // "Content-Type: application/json". Removing the header lets the browser
    // generate the correct multipart/form-data header *including the boundary*,
    // which is what the FastAPI endpoint expects.
    if (typeof FormData !== "undefined" && data instanceof FormData) {
      const headers = { ...(config?.headers ?? {}) } as Record<string, unknown>;
      delete headers["Content-Type"];
      delete headers["content-type"];
      headers["Content-Type"] = undefined;
      finalConfig = { ...config, headers: headers as AxiosRequestConfig["headers"] };
    }

    const res = await this.axiosInstance.post<T>(url, data, finalConfig);
    this.invalidateCache();
    return res.data;
  }

  public async put<T>(url: string, data?: unknown, config?: AxiosRequestConfig): Promise<T> {
    const res = await this.axiosInstance.put<T>(url, data, config);
    this.invalidateCache();
    return res.data;
  }

  public async patch<T>(url: string, data?: unknown, config?: AxiosRequestConfig): Promise<T> {
    const res = await this.axiosInstance.patch<T>(url, data, config);
    this.invalidateCache();
    return res.data;
  }

  public async delete<T>(url: string, config?: AxiosRequestConfig): Promise<T> {
    const res = await this.axiosInstance.delete<T>(url, config);
    this.invalidateCache();
    return res.data;
  }
}

export const apiClient = new ApiClient();

/**
 * Server-side changes announced through cross-view events must not be masked by
 * an older cached GET. Dropping the cache lets the listeners that already react
 * to these events fetch the new state instead of replaying the previous one.
 */
if (typeof window !== "undefined") {
  const SYNC_EVENTS = [
    "rollcall:attendance-changed",
    "rollcall:sessions-changed",
    "rollcall-attendance-updated",
    "rollcall-delegations-updated",
    "rollcall-unlock-request-updated",
  ];
  const invalidate = () => apiClient.invalidateCache();
  SYNC_EVENTS.forEach((eventName) => window.addEventListener(eventName, invalidate));
}

