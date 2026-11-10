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
): Promise<{ success: boolean; count: number }> {
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
  await apiClient.put(
    `/api/v1/attendance/sessions/${encodeURIComponent(sessionId)}`,
    payload
  );
  return { success: true, count: records.length };
}

export async function reconcileAttendance(
  sessionIdOrData:
    | string
    | { session_id: string; usn: string; new_status: AttendanceStatus; reason: string },
  payload?: { usn: string; resolved_status: AttendanceStatus; reason: string }
): Promise<{ success: boolean; audit_log_id?: string }> {
  let sessionId: string;
  let usn: string;
  let resolvedStatus: AttendanceStatus;
  let reason: string;

  if (typeof sessionIdOrData === "string" && payload) {
    sessionId = sessionIdOrData;
    usn = payload.usn;
    resolvedStatus = payload.resolved_status;
    reason = payload.reason;
  } else if (typeof sessionIdOrData === "object") {
    sessionId = sessionIdOrData.session_id;
    usn = sessionIdOrData.usn;
    resolvedStatus = sessionIdOrData.new_status;
    reason = sessionIdOrData.reason;
  } else {
    throw new Error("Invalid parameters to reconcileAttendance");
  }

  await apiClient.post(
    `/api/v1/attendance/sessions/${encodeURIComponent(sessionId)}/reconcile`,
    {
      resolutions: [
        {
          usn,
          resolved_status: resolvedStatus,
          reason,
          reconciled_by: "faculty",
          confidence: 1.0,
        },
      ],
    }
  );

  return { success: true };
}
