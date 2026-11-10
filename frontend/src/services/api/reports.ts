/**
 * Reports and Analytics API Data Service
 * Aligned with backend /api/v1/reports and /api/v1/analytics endpoints.
 */

import { apiClient } from "@/services/api/client";

export interface AnalyticsSummary {
  total_students: number;
  total_sessions: number;
  total_records: number;
  average_attendance_rate: number;
  branch_breakdown?: Record<string, { total_records: number; present: number; rate: number }>;
}

export async function fetchAnalyticsSummary(): Promise<AnalyticsSummary> {
  return apiClient.get<AnalyticsSummary>("/api/v1/analytics/summary");
}

export async function downloadExcelReport(params: {
  session_id?: string;
  date?: string;
  include_branch_summary?: boolean;
}): Promise<Blob> {
  const token = typeof window !== "undefined" ? localStorage.getItem("rollcall_access_token") : null;
  const baseUrl = typeof window !== "undefined" ? `http://${window.location.hostname}:8000` : "http://127.0.0.1:8000";

  const res = await fetch(`${baseUrl}/api/v1/reports/export/excel`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(params),
  });

  if (!res.ok) {
    const errorData = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(errorData.detail || `Excel export failed (${res.status})`);
  }

  return res.blob();
}

export async function downloadPdfReport(params: {
  session_id?: string;
  date?: string;
  include_charts?: boolean;
}): Promise<Blob> {
  const token = typeof window !== "undefined" ? localStorage.getItem("rollcall_access_token") : null;
  const baseUrl = typeof window !== "undefined" ? `http://${window.location.hostname}:8000` : "http://127.0.0.1:8000";

  const res = await fetch(`${baseUrl}/api/v1/reports/export/pdf`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(params),
  });

  if (!res.ok) {
    const errorData = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(errorData.detail || `PDF export failed (${res.status})`);
  }

  return res.blob();
}

