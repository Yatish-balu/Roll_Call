/**
 * Attendance API Data Service
 * Strictly supports the canonical 4 attendance states:
 * PRESENT, ABSENT, PENDING, UNREVIEWED.
 */

import { apiClient } from "@/services/api/client";

export type AttendanceStatus = "PRESENT" | "ABSENT" | "PENDING" | "UNREVIEWED";

export interface AttendanceRecord {
  session_id: string;
  usn: string;
  room_id: string;
  status: AttendanceStatus;
  source?: string;
  confidence?: number;
  session_date?: string;
  subject?: string;
  student_name?: string;
  branch?: string;
  room_name?: string;
}

export interface RecordAttendanceParams {
  usn: string;
  room_id: string;
  status: AttendanceStatus;
  source?: string;
  confidence?: number;
}

export interface ReconcileParams {
  usn: string;
  resolved_status: AttendanceStatus;
  reason?: string;
  reconciled_by?: string;
}

export async function fetchSessionAttendance(sessionId: string): Promise<AttendanceRecord[]> {
  return apiClient.get<AttendanceRecord[]>(`/api/v1/attendance/sessions/${encodeURIComponent(sessionId)}`);
}

export async function recordStudentAttendance(
  sessionId: string,
  data: RecordAttendanceParams
): Promise<AttendanceRecord> {
  return apiClient.post<AttendanceRecord>(
    `/api/v1/attendance/sessions/${encodeURIComponent(sessionId)}/record`,
    data
  );
}

export async function updateSessionAttendance(
  sessionId: string,
  records: Array<{ usn: string; room_id?: string; status: AttendanceStatus }>
): Promise<AttendanceRecord[]> {
  return apiClient.put<AttendanceRecord[]>(
    `/api/v1/attendance/sessions/${encodeURIComponent(sessionId)}`,
    { records }
  );
}

export async function reconcileAttendance(
  sessionId: string,
  data: ReconcileParams
): Promise<{ success: boolean; message: string; record: AttendanceRecord }> {
  return apiClient.post<{ success: boolean; message: string; record: AttendanceRecord }>(
    `/api/v1/attendance/sessions/${encodeURIComponent(sessionId)}/reconcile`,
    data
  );
}

