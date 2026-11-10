/**
 * Centralized Dashboard API Data Service
 * Strictly utilizes verified backend endpoints and handles loading/empty states cleanly.
 */

import { apiClient } from "@/services/api/client";
import type {
  VerifiedSessionPage,
  VerifiedSummaryReport,
  VerifiedAgentResponse,
} from "@/types/dashboard";

export interface DashboardData {
  sessions: VerifiedSessionPage | null;
  overallAnalytics: VerifiedSummaryReport | null;
  todayAnalytics: VerifiedSummaryReport | null;
}

/**
 * Fetch all verified data required for the main dashboard.
 */
export async function fetchDashboardData(todayIsoDate: string): Promise<DashboardData> {
  const [sessionsRes, overallRes, todayRes] = await Promise.allSettled([
    apiClient.get<VerifiedSessionPage>("/api/v1/sessions", { limit: 50 }),
    apiClient.get<VerifiedSummaryReport>("/api/v1/analytics/overview"),
    apiClient.get<VerifiedSummaryReport>(`/api/v1/analytics/date/${todayIsoDate}/summary`),
  ]);

  return {
    sessions: sessionsRes.status === "fulfilled" ? sessionsRes.value : null,
    overallAnalytics: overallRes.status === "fulfilled" ? overallRes.value : null,
    todayAnalytics: todayRes.status === "fulfilled" ? todayRes.value : null,
  };
}

/**
 * Send natural-language query to AI Assistant.
 */
export async function sendAgentQuery(
  query: string,
  sessionId?: string
): Promise<VerifiedAgentResponse> {
  return apiClient.post<VerifiedAgentResponse>("/api/v1/agent/chat", {
    query,
    session_id: sessionId || undefined,
  });
}

/**
 * Upload attendance sheet/photo for OCR and processing.
 */
export async function uploadAttendanceFile(
  file: File,
  sessionId?: string
): Promise<VerifiedAgentResponse> {
  const formData = new FormData();
  formData.append("file", file);
  if (sessionId) {
    formData.append("session_id", sessionId);
  }
  return apiClient.upload<VerifiedAgentResponse>("/api/v1/agent/process-file", formData);
}

