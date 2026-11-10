/**
 * Centralized Reusable API Client for RollCall AI
 */

import { API_BASE_URL } from "@/config/api";
import { ApiError, type ApiErrorDetail, type RequestOptions } from "@/types/api";

export class ApiClient {
  private readonly baseUrl: string;

  constructor(baseUrl: string = API_BASE_URL) {
    this.baseUrl = baseUrl.replace(/\/+$/, "");
  }

  /**
   * Build full URL with query parameters.
   */
  private buildUrl(
    endpoint: string,
    params?: Record<string, string | number | boolean | undefined | null>
  ): string {
    const cleanEndpoint = endpoint.startsWith("/") ? endpoint : `/${endpoint}`;
    const url = new URL(`${this.baseUrl}${cleanEndpoint}`);

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
   * Execute an HTTP request with error handling and serialization.
   */
  async request<T>(endpoint: string, options: RequestOptions = {}): Promise<T> {
    const { token, params, headers: customHeaders, body, ...restOptions } = options;
    const url = this.buildUrl(endpoint, params);

    const headers = new Headers(customHeaders);

    // Attach Authorization Bearer token if provided
    if (token) {
      headers.set("Authorization", `Bearer ${token.trim()}`);
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
