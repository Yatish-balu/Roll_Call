import { apiClient } from "@/services/api/client";

export type AttendanceStatus = "PRESENT" | "ABSENT" | "PENDING" | "UNREVIEWED";

export interface AttendanceRecord {
  id?: number;
  session_id: string;
  usn: string;
  status: AttendanceStatus;
  source: string;
  confidence?: number;
  allocation_id?: number | null;
  recorded_at?: string;
  student_name?: string;
  branch?: string;
  room_id?: string;
}

export interface AttendanceSummary {
  session_id: string;
  total_enrolled: number;
  present_count: number;
  absent_count: number;
  pending_count: number;
  unreviewed_count: number;
  attendance_percentage: number;
}

export async function fetchSessionAttendance(sessionId: string): Promise<AttendanceRecord[]> {
  const res = await apiClient.get<AttendanceRecord[] | { items: AttendanceRecord[] }>(
    `/api/v1/attendance/sessions/${encodeURIComponent(sessionId)}`
  );
  if (Array.isArray(res)) {
    return res;
  }
  return res.items || [];
}

export async function recordStudentAttendance(
  sessionId: string,
  data: {
    usn: string;
    status: AttendanceStatus;
    room_id?: string;
    source?: string;
    confidence?: number;
    upsert?: boolean;
  }
): Promise<AttendanceRecord> {
  const upsert = data.upsert !== false;
  return apiClient.post<AttendanceRecord>(
    `/api/v1/attendance/sessions/${encodeURIComponent(sessionId)}/record?upsert=${upsert}`,
    {
      session_id: sessionId,
      usn: data.usn,
      status: data.status,
      room_id: data.room_id || "LH-101",
      source: data.source || "manual",
      confidence: data.confidence || 1.0,
    }
  );
}

export async function updateSessionAttendance(
  sessionId: string,
  records: Array<{ usn: string; status: AttendanceStatus; room_id?: string }>
): Promise<{ success: boolean; count: number; message?: string }> {
  const payload = {
    records: records.map((r) => ({
      session_id: sessionId,
      usn: r.usn,
      status: r.status,
      room_id: r.room_id || "LH-101",
      source: "manual",
      confidence: 1.0,
    })),
  };
  const res = await apiClient.put<{ replaced_count?: number; message?: string }>(
    `/api/v1/attendance/sessions/${encodeURIComponent(sessionId)}`,
    payload
  );
  return {
    success: true,
    count: res?.replaced_count ?? records.length,
    message: res?.message,
  };
}

export async function reconcileAttendance(
  sessionIdOrData:
    | string
    | { session_id: string; usn: string; new_status: AttendanceStatus },
  payload?: { usn: string; resolved_status: AttendanceStatus }
): Promise<{ success: boolean }> {
  let sessionId: string;
  let usn: string;
  let resolvedStatus: AttendanceStatus;

  if (typeof sessionIdOrData === "string" && payload) {
    sessionId = sessionIdOrData;
    usn = payload.usn;
    resolvedStatus = payload.resolved_status;
  } else if (typeof sessionIdOrData === "object") {
    sessionId = sessionIdOrData.session_id;
    usn = sessionIdOrData.usn;
    resolvedStatus = sessionIdOrData.new_status;
  } else {
    throw new Error("Invalid parameters to reconcileAttendance");
  }

  // No reason/override field is sent: the backend records the actor, role and
  // the previous -> new status itself (N5). The frontend never authors audit
  // entries.
  await apiClient.post(
    `/api/v1/attendance/sessions/${encodeURIComponent(sessionId)}/reconcile`,
    {
      resolutions: [
        {
          usn,
          resolved_status: resolvedStatus,
          reconciled_by: "faculty",
          confidence: 1.0,
        },
      ],
    }
  );

  return { success: true };
}

export interface AttendanceUnlockRequest {
  request_id: string;
  session_id: string;
  subject_code?: string | null;
  session_date?: string | null;
  teacher_id: string;
  teacher_name?: string | null;
  teacher_email?: string | null;
  reason: string;
  target_usns?: string | null;
  requested_change?: string | null;
  status: "PENDING" | "APPROVED" | "REJECTED";
  admin_notes?: string | null;
  reviewed_by?: string | null;
  reviewed_at?: string | null;
  created_at: string;
  expires_at?: string | null;
}

export async function createAttendanceUnlockRequest(data: {
  session_id: string;
  reason: string;
  target_usns?: string[];
  requested_change?: string;
}): Promise<AttendanceUnlockRequest> {
  return apiClient.post<AttendanceUnlockRequest>("/api/v1/attendance/unlock-requests", data);
}

export async function fetchAttendanceUnlockRequests(params?: {
  session_id?: string;
  status?: string;
}): Promise<AttendanceUnlockRequest[]> {
  return apiClient.get<AttendanceUnlockRequest[]>("/api/v1/attendance/unlock-requests", params);
}

export async function reviewAttendanceUnlockRequest(
  requestId: string,
  data: {
    decision: "APPROVED" | "REJECTED";
    admin_notes?: string;
    unlock_hours?: number;
  }
): Promise<AttendanceUnlockRequest> {
  return apiClient.post<AttendanceUnlockRequest>(
    `/api/v1/attendance/unlock-requests/${encodeURIComponent(requestId)}/review`,
    data
  );
}

