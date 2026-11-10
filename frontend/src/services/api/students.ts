/**
 * Students API Data Service
 * Aligned with backend /api/v1/students endpoints.
 */

import { apiClient } from "@/services/api/client";

export interface Student {
  usn: string;
  name: string;
  branch: string;
}

export interface StudentPage {
  items: Student[];
  total: number;
  limit: number;
  offset: number;
}

export interface StudentCreateParams {
  usn: string;
  name: string;
  branch: string;
}

export async function fetchStudents(params?: {
  limit?: number;
  offset?: number;
  branch?: string;
  search?: string;
}): Promise<StudentPage> {
  return apiClient.get<StudentPage>("/api/v1/students", params);
}

export async function getStudent(usn: string): Promise<Student> {
  return apiClient.get<Student>(`/api/v1/students/${encodeURIComponent(usn)}`);
}

export async function createStudent(data: StudentCreateParams): Promise<Student> {
  return apiClient.post<Student>("/api/v1/students", data);
}

