/**
 * Centralized Reusable API Client for RollCall AI
 */

import { API_BASE_URL } from "@/config/api";
import { ApiError, type ApiErrorDetail, type RequestOptions } from "@/types/api";

export interface ExtendedRequestOptions extends RequestOptions {
  _retried?: boolean;
}

export class ApiClient {
  private readonly baseUrl: string;
  private accessToken: string | null = null;
  private refreshPromise: Promise<string | null> | null = null;

  constructor(baseUrl: string = API_BASE_URL) {
    this.baseUrl = baseUrl.replace(/\/+$/, "");
  }

  /**
   * Set in-memory access token (never stored in localStorage/sessionStorage).
   */
  setAccessToken(token: string | null): void {
    this.accessToken = token;
  }

  /**
   * Retrieve current in-memory access token.
   */
  getAccessToken(): string | null {
    return this.accessToken;
  }

  /**
   * Resolve dynamic base URL to prevent cookie/CORS domain mismatches in browsers.
   */
  private getEffectiveBaseUrl(): string {
    if (typeof window !== "undefined" && !process.env.NEXT_PUBLIC_API_URL) {
      const host = window.location.hostname || "localhost";
      return `http://${host}:8000`;
    }
    return this.baseUrl;
  }

  /**
   * Single-flight token refresh using HttpOnly cookie credentials.
   */
  private async performRefresh(): Promise<string | null> {
    try {
      const cleanEndpoint = "/api/v1/auth/refresh";
      const url = `${this.getEffectiveBaseUrl()}${cleanEndpoint}`;
      const response = await fetch(url, {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          "Accept": "application/json",
          "X-Requested-With": "XMLHttpRequest",
        },
      });

      if (!response.ok) {
        if (response.status === 401 || response.status === 403) {
          this.setAccessToken(null);
        }
        return null;
      }

      const data = await response.json();
      if (data && typeof data.token === "string") {
        this.setAccessToken(data.token);
        return data.token;
      }
      return null;
    } catch {
      return null;
    } finally {
      this.refreshPromise = null;
    }
  }

  /**
   * Build full URL with query parameters.
   */
  private buildUrl(
    endpoint: string,
    params?: Record<string, string | number | boolean | undefined | null>
  ): string {
    const cleanEndpoint = endpoint.startsWith("/") ? endpoint : `/${endpoint}`;
    const url = new URL(`${this.getEffectiveBaseUrl()}${cleanEndpoint}`);

    if (params) {
      Object.entries(params).forEach(([key, value]) => {
        if (value !== undefined && value !== null && value !== "") {
          url.searchParams.append(key, String(value));
        }
      });
    }

    return url.toString();
  }

  /**
   * Execute an HTTP request with error handling, serialization, and single-flight refresh retry.
   */
  async request<T>(endpoint: string, options: ExtendedRequestOptions = {}): Promise<T> {
    const { token, params, headers: customHeaders, body, _retried, ...restOptions } = options;
    const url = this.buildUrl(endpoint, params);

    const headers = new Headers(customHeaders);

    // Prefer explicitly passed token, or fall back to in-memory access token
    const effectiveToken = token || this.accessToken;
    if (effectiveToken) {
      headers.set("Authorization", `Bearer ${effectiveToken.trim()}`);
    }

    // Include custom CSRF header on requests
    if (!headers.has("X-Requested-With")) {
      headers.set("X-Requested-With", "XMLHttpRequest");
    }

    // Set JSON headers unless sending FormData multipart
    const isFormData = typeof FormData !== "undefined" && body instanceof FormData;
    if (!isFormData && !headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
      headers.set("Accept", "application/json");
    }

    let serializedBody: BodyInit | null | undefined = body;
    if (body && !isFormData && typeof body === "object") {
      serializedBody = JSON.stringify(body);
    }

    let response: Response;
    try {
      response = await fetch(url, {
        credentials: "include",
        ...restOptions,
        headers,
        body: serializedBody,
      });
    } catch (networkError) {
      const msg =
        networkError instanceof Error
          ? networkError.message
          : "Network connection failure";
      throw new ApiError(
        `Unable to connect to backend server at ${this.baseUrl}: ${msg}`,
        0,
        { originalError: networkError }
      );
    }

    // Intercept 401 for automatic single-flight token renewal
    const isAuthEndpoint =
      endpoint.includes("/auth/login") ||
      endpoint.includes("/auth/refresh") ||
      endpoint.includes("/auth/logout");

    if (response.status === 401 && !_retried && !isAuthEndpoint) {
      if (!this.refreshPromise) {
        this.refreshPromise = this.performRefresh();
      }
      const newToken = await this.refreshPromise;
      if (newToken) {
        // Retry original request exactly once with new token
        return this.request<T>(endpoint, {
          ...options,
          token: newToken,
          _retried: true,
        });
      }
    }

    // Parse response body
    const contentType = response.headers.get("content-type") || "";
    let parsedData: unknown = null;

    if (contentType.includes("application/json")) {
      try {
        parsedData = await response.json();
      } catch {
        parsedData = null;
      }
    } else {
      parsedData = await response.text();
    }

    if (!response.ok) {
      let errorMessage = `HTTP ${response.status} ${response.statusText}`;

      if (parsedData && typeof parsedData === "object") {
        const errorDetail = parsedData as ApiErrorDetail;
        if (typeof errorDetail.detail === "string") {
          errorMessage = errorDetail.detail;
        } else if (Array.isArray(errorDetail.detail) && errorDetail.detail.length > 0) {
          errorMessage = errorDetail.detail.map((d) => d.msg || "").join("; ") || errorMessage;
        } else if (errorDetail.message) {
          errorMessage = errorDetail.message;
        }
      }

      throw new ApiError(errorMessage, response.status, parsedData);
    }

    return parsedData as T;
  }

  /**
   * Perform GET request.
   */
  async get<T>(
    endpoint: string,
    params?: Record<string, string | number | boolean | undefined | null>,
    options?: RequestOptions
  ): Promise<T> {
    return this.request<T>(endpoint, {
      ...options,
      method: "GET",
      params,
    });
  }

  /**
   * Perform POST request.
   */
  async post<T>(
    endpoint: string,
    body?: unknown,
    options?: RequestOptions
  ): Promise<T> {
    return this.request<T>(endpoint, {
      ...options,
      method: "POST",
      body: body as BodyInit,
    });
  }

  /**
   * Perform PUT request.
   */
  async put<T>(
    endpoint: string,
    body?: unknown,
    options?: RequestOptions
  ): Promise<T> {
    return this.request<T>(endpoint, {
      ...options,
      method: "PUT",
      body: body as BodyInit,
    });
  }

  /**
   * Perform DELETE request.
   */
  async delete<T>(
    endpoint: string,
    options?: RequestOptions
  ): Promise<T> {
    return this.request<T>(endpoint, {
      ...options,
      method: "DELETE",
    });
  }

  /**
   * Perform multipart/form-data upload.
   */
  async upload<T>(
    endpoint: string,
    formData: FormData,
    options?: RequestOptions
  ): Promise<T> {
    return this.request<T>(endpoint, {
      ...options,
      method: "POST",
      body: formData,
    });
  }
}

// Export singleton instance configured with default API_BASE_URL
export const apiClient = new ApiClient();
