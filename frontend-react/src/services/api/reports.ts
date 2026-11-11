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

// ---------------------------------------------------------------------------
// Student roster PDF (branch + semester filters are applied by the backend)
// ---------------------------------------------------------------------------

export interface StudentRosterFilters {
  branches: string[];
  departments: Array<{ dept_id: string; name: string }>;
  semesters: number[];
  configured_semesters: number[];
}

export async function fetchStudentRosterFilters(): Promise<StudentRosterFilters> {
  return apiClient.get<StudentRosterFilters>("/api/v1/reports/students/filters");
}

export interface StudentRosterExportResponse extends Blob {
  studentCount?: number;
  appliedFilters?: string;
}

export async function downloadStudentRosterPdf(params: {
  branch?: string;
  semester?: number;
  title?: string;
}): Promise<Blob> {
  return apiClient.post<Blob>("/api/v1/reports/students/pdf", params, {
    responseType: "blob",
  });
}
