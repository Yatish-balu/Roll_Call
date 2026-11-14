import { apiClient } from "@/services/api/client";

export interface TeacherSubjectMapping {
  teacher_id: string;
  user_id?: string;
  subject_code: string;
  subject_name?: string;
  semester?: number | string;
  branch?: string;
  teacher_name?: string;
}

export interface TeacherSubjectsResponse {
  total: number;
  items: TeacherSubjectMapping[];
}

export interface SubjectMetadata {
  code: string;
  name: string;
  semester: number;
  branch: string;
}

export const KNOWN_SUBJECTS: Record<string, SubjectMetadata> = {
  "DIST-SYS": { code: "DIST-SYS", name: "Distributed Systems Architecture", semester: 5, branch: "CSE" },
  "DB-SYS": { code: "DB-SYS", name: "Database Management Systems", semester: 5, branch: "CSE" },
  "ML": { code: "ML", name: "Machine Learning & Pattern Recognition", semester: 5, branch: "AIML" },
  "CN": { code: "CN", name: "Computer Networks & Protocols", semester: 5, branch: "CSE" },
  "ALGO": { code: "ALGO", name: "Design & Analysis of Algorithms", semester: 4, branch: "CSE" },
  "NET-SEC": { code: "NET-SEC", name: "Network Security & Forensics", semester: 6, branch: "CYBER" },
  "CRYPT": { code: "CRYPT", name: "Applied Cryptography & Privacy", semester: 6, branch: "CYBER" },
  "FORENSICS": { code: "FORENSICS", name: "Digital Forensics & Incident Response", semester: 6, branch: "CYBER" },
  "NLP": { code: "NLP", name: "Natural Language Processing", semester: 6, branch: "AIML" },
  "DEEP-LEARN": { code: "DEEP-LEARN", name: "Deep Neural Networks", semester: 7, branch: "AIML" },
  "ES": { code: "ES", name: "Embedded Systems Architecture", semester: 5, branch: "ECE" },
  "VLSI": { code: "VLSI", name: "VLSI Design & Fabrication", semester: 6, branch: "ECE" },
  "SIG-SYS": { code: "SIG-SYS", name: "Signals & Linear Systems", semester: 4, branch: "ECE" },
  "CLOUD-COMP": { code: "CLOUD-COMP", name: "Cloud Infrastructure & DevOps", semester: 5, branch: "ISE" },
  "WEB-TECH": { code: "WEB-TECH", name: "Modern Web Technologies", semester: 4, branch: "ISE" },
};

export const AVAILABLE_FACULTY = [
  { id: "faculty_ml", name: "Prof. Arvind Sharma", department: "AIML / CSE" },
  { id: "faculty_db", name: "Dr. Kavita Menon", department: "CSE / Cyber" },
  { id: "faculty_os", name: "Prof. S. N. Murthy", department: "CSE / Systems" },
  { id: "faculty_cn", name: "Dr. Rajesh Raman", department: "Cyber / Networks" },
  { id: "faculty_math", name: "Dr. Meenakshi Rao", department: "Mathematics / ISE" },
];

export async function fetchTeacherSubjects(filters?: {
  user_id?: string;
  subject_code?: string;
}): Promise<TeacherSubjectsResponse> {
  const queryParams: Record<string, string | number | boolean | undefined | null> = {};
  if (filters?.user_id) queryParams.user_id = filters.user_id;
  if (filters?.subject_code) queryParams.subject_code = filters.subject_code;

  return apiClient.get<TeacherSubjectsResponse>(
    "/api/v1/admin/teacher-subjects",
    Object.keys(queryParams).length ? queryParams : undefined
  );
}

export async function assignTeacherSubject(data: {
  user_id: string;
  subject_code: string;
}): Promise<TeacherSubjectMapping> {
  return apiClient.post<TeacherSubjectMapping>(
    "/api/v1/admin/teacher-subjects",
    data
  );
}

export async function removeTeacherSubject(
  userId: string,
  subjectCode: string
): Promise<{ success: boolean; message: string }> {
  try {
    return await apiClient.delete<{ success: boolean; message: string }>(
      `/api/v1/admin/teacher-subjects?user_id=${encodeURIComponent(userId)}&subject_code=${encodeURIComponent(subjectCode)}`
    );
  } catch (err: unknown) {
    // If backend returns 405 Method Not Allowed or 404, we catch and return dependency notification
    const msg = err instanceof Error ? err.message : String(err);
    if (msg.includes("405") || msg.includes("Method Not Allowed") || msg.includes("404")) {
      return {
        success: false,
        message: "Backend endpoint pending: DELETE /api/v1/admin/teacher-subjects is not implemented on the server.",
      };
    }
    throw err;
  }
}

export interface MySubjectsResponse {
  user_id: string;
  role: string;
  subject_codes: string[];
}

export async function fetchMySubjects(): Promise<MySubjectsResponse> {
  return apiClient.get<MySubjectsResponse>("/api/v1/me/subjects");
}

export interface AdminTeacherItem {
  user_id: string;
  teacher_id: string;
  name: string;
  email: string;
  profile_email?: string;
  mobile?: string;
  branch?: string;
  designation?: string;
  experience_years?: number;
  qualifications?: string;
  specialization?: string;
  expertise?: string[];
  mastered_subjects?: string[];
  photo_url?: string;
  role: string;
  is_active: boolean;
  subject_codes: string[];
  session_count: number;
  created_at?: string;
}

export async function fetchAdminTeachers(): Promise<{ items: AdminTeacherItem[]; total: number }> {
  return apiClient.get<{ items: AdminTeacherItem[]; total: number }>("/api/v1/admin/teachers");
}

export async function updateTeacherName(userId: string, newName: string): Promise<{ success: boolean; name: string; message: string }> {
  return apiClient.patch<{ success: boolean; name: string; message: string }>(
    `/api/v1/admin/teachers/${encodeURIComponent(userId)}/name`,
    { name: newName }
  );
}

export interface PermissionRequestItem {
  request_id: string;
  user_id: string;
  teacher_name?: string;
  request_type: string;
  subject_code?: string | null;
  reason: string;
  status: "PENDING" | "APPROVED" | "REJECTED";
  created_at: string;
  reviewed_by?: string | null;
  reviewed_at?: string | null;
  admin_comment?: string | null;
}

export async function fetchPermissionRequests(statusFilter?: string): Promise<{ items: PermissionRequestItem[]; total: number }> {
  const params: Record<string, string> = {};
  if (statusFilter && statusFilter !== "ALL") params.status = statusFilter;
  return apiClient.get<{ items: PermissionRequestItem[]; total: number }>(
    "/api/v1/admin/permission-requests",
    params
  );
}

export async function submitPermissionRequest(data: {
  subject_code?: string;
  request_type?: string;
  reason: string;
}): Promise<PermissionRequestItem> {
  return apiClient.post<PermissionRequestItem>("/api/v1/admin/permission-requests", data);
}

export async function reviewPermissionRequest(
  requestId: string,
  decision: "APPROVE" | "REJECT",
  comment?: string
): Promise<{ success: boolean; request_id: string; status: string; message: string }> {
  return apiClient.post<{ success: boolean; request_id: string; status: string; message: string }>(
    `/api/v1/admin/permission-requests/${encodeURIComponent(requestId)}/review`,
    { decision, comment }
  );
}
