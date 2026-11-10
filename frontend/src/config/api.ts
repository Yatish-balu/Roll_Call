/**
 * Centralized API Configuration for RollCall AI Frontend
 */

export function getApiBaseUrl(): string {
  if (process.env.NEXT_PUBLIC_API_URL) {
    return process.env.NEXT_PUBLIC_API_URL.replace(/\/+$/, "");
  }
  if (typeof window !== "undefined") {
    const host = window.location.hostname || "localhost";
    return `http://${host}:8000`;
  }
  return "http://127.0.0.1:8000";
}

export const API_BASE_URL = getApiBaseUrl();

export const APP_ENV = process.env.NEXT_PUBLIC_APP_ENV || "development";

export const API_ENDPOINTS = {
  HEALTH: "/health",
  ROOT: "/",
  STUDENTS: "/api/v1/students",
  ROOMS: "/api/v1/rooms",
  SESSIONS: "/api/v1/sessions",
  ATTENDANCE: "/api/v1/attendance",
  ANALYTICS: "/api/v1/analytics",
  REPORTS: "/api/v1/reports",
  AGENT: "/api/v1/agent",
} as const;

export const DEFAULT_TIMEOUT_MS = 15000;
