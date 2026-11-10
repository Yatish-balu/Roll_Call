/**
 * API Type Definitions for RollCall AI
 */

export interface HealthCheckResponse {
  status: string;
  environment: string;
  version: string;
}

export interface ApiErrorDetail {
  error?: string;
  status_code?: number;
  detail?: string | Array<{ loc?: string[]; msg?: string; type?: string }>;
  message?: string;
}

export class ApiError extends Error {
  public readonly statusCode: number;
  public readonly data?: unknown;

  constructor(message: string, statusCode: number, data?: unknown) {
    super(message);
    this.name = "ApiError";
    this.statusCode = statusCode;
    this.data = data;
    Object.setPrototypeOf(this, ApiError.prototype);
  }
}

export interface RequestOptions extends RequestInit {
  token?: string | null;
  params?: Record<string, string | number | boolean | undefined | null>;
}
