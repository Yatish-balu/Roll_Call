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
  teacherMappings: Array<{ teacher_id: string; subject_code: string }> | null;
}

export async function fetchDashboardData(todayIsoDate: string): Promise<DashboardData> {
  const [sessionsRes, overallRes, todayRes, mappingsRes] = await Promise.allSettled([
    apiClient.get<VerifiedSessionPage>("/api/v1/sessions", { limit: 100 }),
    apiClient.get<VerifiedSummaryReport>("/api/v1/analytics/overview"),
    apiClient.get<VerifiedSummaryReport>(`/api/v1/analytics/date/${todayIsoDate}/summary`),
    apiClient.get<{ items: Array<{ teacher_id: string; subject_code: string }> }>("/api/v1/admin/teacher-subjects"),
  ]);

  return {
    sessions: sessionsRes.status === "fulfilled" ? sessionsRes.value : null,
    overallAnalytics: overallRes.status === "fulfilled" ? overallRes.value : null,
    todayAnalytics: todayRes.status === "fulfilled" ? todayRes.value : null,
    teacherMappings: mappingsRes.status === "fulfilled" ? mappingsRes.value?.items ?? [] : null,
  };
}

export async function sendAgentQuery(
  query: string,
  sessionId?: string
): Promise<VerifiedAgentResponse> {
  return apiClient.post<VerifiedAgentResponse>("/api/v1/agent/chat", {
    query,
    session_id: sessionId || undefined,
  });
}

export async function uploadAttendanceFile(
  file: File,
  sessionId?: string
): Promise<VerifiedAgentResponse> {
  const formData = new FormData();
  formData.append("file", file);
  if (sessionId) {
    formData.append("session_id", sessionId);
  }
  return apiClient.post<VerifiedAgentResponse>("/api/v1/agent/process-file", formData, {
    headers: {
      "Content-Type": "multipart/form-data",
    },
  });
}

