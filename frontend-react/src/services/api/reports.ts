import { apiClient } from "@/services/api/client";
import type { VerifiedSummaryReport } from "@/types/dashboard";

export async function fetchAnalyticsSummary(): Promise<VerifiedSummaryReport> {
  return apiClient.get<VerifiedSummaryReport>("/api/v1/analytics/overview");
}

export async function downloadExcelReport(params: {
  session_id?: string;
  date?: string;
  include_branch_summary?: boolean;
}): Promise<Blob> {
  return apiClient.post<Blob>("/api/v1/reports/export/excel", params, {
    responseType: "blob",
  });
}

export async function downloadPdfReport(params: {
  session_id?: string;
  date?: string;
  include_charts?: boolean;
}): Promise<Blob> {
  return apiClient.post<Blob>("/api/v1/reports/export/pdf", params, {
    responseType: "blob",
  });
}
