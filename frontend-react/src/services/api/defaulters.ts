import { apiClient } from "@/services/api/client";

export interface DefaulterStudent {
  usn: string;
  student_name: string;
  branch: string;
  attended_classes: number;
  conducted_classes: number;
  attendance_percentage: number;
  classes_needed_to_recover: number;
  subject_code?: string;
  semester?: number;
}

export interface DefaultersResponse {
  threshold_percent: number;
  total_defaulters: number;
  items: DefaulterStudent[];
  is_mock_fallback?: boolean;
  dependency_message?: string;
}

export interface MetaConfig {
  defaulter_threshold_percent: number;
  defaulter_required_percent: number;
  attendance_bands: {
    green_above_percent: number;
    yellow_from_percent: number;
    labels: Record<string, string>;
  };
  upload_limits: {
    image_max_bytes: number;
    csv_max_bytes: number;
  };
  subject_codes: string[];
}

export async function fetchMetaConfig(): Promise<MetaConfig> {
  return apiClient.get<MetaConfig>("/api/v1/meta/config");
}

export async function fetchDefaulters(filters?: {
  branch?: string;
  subject?: string;
  semester?: string | number;
}): Promise<DefaultersResponse> {
  const params: Record<string, string | number | boolean | undefined | null> = {};
  if (filters?.branch && filters.branch !== "ALL") params.branch = filters.branch;
  if (filters?.subject && filters.subject !== "ALL") params.subject = filters.subject;
  if (filters?.semester && filters.semester !== "ALL") params.semester = filters.semester;

  try {
    return await apiClient.get<DefaultersResponse>(
      "/api/v1/analytics/defaulters",
      Object.keys(params).length ? params : undefined
    );
  } catch (err: unknown) {
    // No invented records: the page reports the unavailable backend contract.
    let threshold = 75.0;
    try {
      const meta = await fetchMetaConfig();
      threshold = meta.defaulter_threshold_percent ?? 75.0;
    } catch {
      threshold = 75.0;
    }
    return {
      threshold_percent: threshold,
      total_defaulters: 0,
      items: [],
      is_mock_fallback: true,
      dependency_message:
        err instanceof Error
          ? `The defaulter registry is currently unavailable: ${err.message}`
          : "The defaulter registry is currently unavailable.",
    };
  }
}

export async function downloadDefaulterPdf(params?: {
  branch?: string;
  subject?: string;
}): Promise<Blob> {
  return apiClient.post<Blob>(
    "/api/v1/reports/export/pdf",
    {
      title: `Attendance Report - Defaulter Review${params?.branch ? ` - ${params.branch}` : ""}`,
      include_branch_summary: true,
    },
    {
      responseType: "blob",
    }
  );
}
