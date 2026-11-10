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

export class ApiClient {
  private readonly axiosInstance: AxiosInstance;
  private accessToken: string | null = null;
  private refreshHandler: RefreshHandler | null = null;

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
            : "HTTP_ERROR");
        const message =
          data?.detail ||
          data?.message ||
          (status === 403
            ? "Access Denied: You do not have permission to perform this action."
            : error.message || "An unexpected error occurred.");

        return Promise.reject(new ApiError(status, code, message, data));
      }
    );
  }

  public setRefreshHandler(handler: RefreshHandler): void {
    this.refreshHandler = handler;
  }

  public setAccessToken(token: string | null): void {
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

  public async get<T>(
    url: string,
    params?: Record<string, string | number | boolean | undefined | null>,
    config?: AxiosRequestConfig
  ): Promise<T> {
    const res = await this.axiosInstance.get<T>(url, { ...config, params });
    return res.data;
  }

  public async post<T>(url: string, data?: unknown, config?: AxiosRequestConfig): Promise<T> {
    const res = await this.axiosInstance.post<T>(url, data, config);
    return res.data;
  }

  public async put<T>(url: string, data?: unknown, config?: AxiosRequestConfig): Promise<T> {
    const res = await this.axiosInstance.put<T>(url, data, config);
    return res.data;
  }

  public async delete<T>(url: string, config?: AxiosRequestConfig): Promise<T> {
    const res = await this.axiosInstance.delete<T>(url, config);
    return res.data;
  }
}

export const apiClient = new ApiClient();

