/**
 * Faculty and Academic Subjects API Data Service
 */

import { apiClient } from "@/services/api/client";

export interface TeacherSubjectMapping {
  teacher_id: string;
  subject_code: string;
}

export interface TeacherSubjectsResponse {
  total: number;
  items: TeacherSubjectMapping[];
}

export async function fetchTeacherSubjects(): Promise<TeacherSubjectsResponse> {
  return apiClient.get<TeacherSubjectsResponse>("/api/v1/admin/teacher-subjects");
}

export async function assignTeacherSubject(data: {
  teacher_id: string;
  subject_code: string;
}): Promise<{ success: boolean; message: string }> {
  return apiClient.post<{ success: boolean; message: string }>(
    "/api/v1/admin/teacher-subjects",
    data
  );
}

export async function fetchMySubjects(): Promise<{ subjects: string[] }> {
  return apiClient.get<{ subjects: string[] }>("/api/v1/me/subjects");
}

