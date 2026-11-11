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

// Isolated development mock data strictly segregated per Rule 7 & Rule 8
const DEV_MOCK_DEFAULTERS: DefaulterStudent[] = [
  {
    usn: "1MS21CS042",
    student_name: "Rahul Verma",
    branch: "CSE",
    attended_classes: 12,
    conducted_classes: 20,
    attendance_percentage: 60.0,
    classes_needed_to_recover: 12,
    subject_code: "DIST-SYS",
    semester: 5,
  },
  {
    usn: "1MS21CS088",
    student_name: "Pooja Hegde",
    branch: "CSE",
    attended_classes: 14,
    conducted_classes: 20,
    attendance_percentage: 70.0,
    classes_needed_to_recover: 4,
    subject_code: "DB-SYS",
    semester: 5,
  },
  {
    usn: "1MS21AI015",
    student_name: "Vikram Aditya",
    branch: "AIML",
    attended_classes: 10,
    conducted_classes: 18,
    attendance_percentage: 55.5,
    classes_needed_to_recover: 14,
    subject_code: "ML",
    semester: 5,
  },
  {
    usn: "1MS21CY027",
    student_name: "Sneha Kulkarni",
    branch: "CYBER",
    attended_classes: 11,
    conducted_classes: 16,
    attendance_percentage: 68.7,
    classes_needed_to_recover: 4,
    subject_code: "NET-SEC",
    semester: 6,
  },
  {
    usn: "1MS21EC009",
    student_name: "Karthik Raja",
    branch: "ECE",
    attended_classes: 9,
    conducted_classes: 18,
    attendance_percentage: 50.0,
    classes_needed_to_recover: 18,
    subject_code: "ES",
    semester: 5,
  },
];

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
    const data = await apiClient.get<DefaultersResponse>(
      "/api/v1/analytics/defaulters",
      Object.keys(params).length ? params : undefined
    );
    return data;
  } catch {
    try {
      const data = await apiClient.get<DefaultersResponse>(
        "/api/v1/reports/defaulters",
        Object.keys(params).length ? params : undefined
      );
      return data;
    } catch {
      let threshold = 75.0;
      try {
        const meta = await fetchMetaConfig();
        threshold = meta.defaulter_threshold_percent ?? 75.0;
      } catch {
        threshold = 75.0;
      }

      let items = [...DEV_MOCK_DEFAULTERS];
      if (filters?.branch && filters.branch !== "ALL") {
        items = items.filter((d) => d.branch.toUpperCase() === String(filters.branch).toUpperCase());
      }
      if (filters?.subject && filters.subject !== "ALL") {
        items = items.filter((d) => d.subject_code === filters.subject);
      }
      if (filters?.semester && filters.semester !== "ALL") {
        items = items.filter((d) => String(d.semester) === String(filters.semester));
      }

      return {
        threshold_percent: threshold,
        total_defaulters: items.length,
        items,
        is_mock_fallback: true,
        dependency_message:
          "Backend endpoint pending: GET /api/v1/analytics/defaulters (N10) is not implemented on the server. Showing isolated development preview.",
      };
    }
  }
}

export async function downloadDefaulterPdf(params?: {
  branch?: string;
  subject?: string;
}): Promise<Blob> {
  return apiClient.post<Blob>(
    "/api/v1/reports/export/pdf",
    {
      title: `Official Defaulter Notice (Below 75% Attendance)${params?.branch ? ` - ${params.branch}` : ""}`,
      include_branch_summary: true,
    },
    {
      responseType: "blob",
    }
  );
}
