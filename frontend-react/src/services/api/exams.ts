/**
 * API service for RollCall AI Exam Hall & Form-B Control Module
 */

import { apiClient } from "./client";

export type ExamType = "THEORY_CIE" | "MID_TERM" | "LAB_CIE" | "LAB_EXTERNAL" | "THEORY_SEE";
export type RoomStatus = "SCHEDULED" | "OPEN" | "SUBMITTED" | "LATE_LOCKED";

export interface ExamCreatePayload {
  exam_id: string;
  name: string;
  exam_type: ExamType;
  semester?: number;
  department?: string;
  date: string; // YYYY-MM-DD
  start_time: string; // HH:MM:SS
  end_time: string; // HH:MM:SS
  cutoff_minutes?: number;
  subject_code: string;
  subject_name?: string;
  rooms?: string[];
}

export interface ExamItem {
  exam_id: string;
  name: string;
  exam_type: ExamType;
  semester?: number;
  department?: string;
  date: string;
  start_time: string;
  end_time: string;
  cutoff_minutes: number;
  subject_code: string;
  subject_name?: string;
  created_by?: string;
  created_at: string;
}

export interface RoomAssignmentItem {
  id: number;
  exam_id: string;
  room_no: string;
  display_room_no: string;
  is_masked: boolean;
  reveals_at?: string;
  exam_name?: string;
  subject_code?: string;
  subject_name?: string;
  date?: string;
  start_time?: string;
  end_time?: string;
  cutoff_minutes?: number;
  cutoff_at?: string;
  block_name?: string;
  capacity?: number;
  invigilator_id?: string;
  external_examiner_name?: string;
  external_examiner_college?: string;
  coordinator_id?: string;
  status: RoomStatus;
  submitted_at?: string;
  submitted_by?: string;
}

export interface ExamSeatingItem {
  id: number;
  exam_id: string;
  room_no: string;
  sl_no: number;
  usn: string;
  name: string;
  branch: string;
  subject_code: string;
  seat_no?: string;
  status: "PRESENT" | "ABSENT";
  marked_by?: string;
  marked_source?: "MANUAL" | "AI_SCAN";
  marked_at?: string;
}

export interface StudentMarkItem {
  usn: string;
  status: "PRESENT" | "ABSENT";
}

export interface BulkMarkPayload {
  marks: StudentMarkItem[];
  marked_source?: "MANUAL" | "AI_SCAN";
}

export interface AdminOverridePayload {
  reason: string;
  new_status?: "OPEN" | "SUBMITTED";
}

export interface RoomSummaryItem {
  room_no: string;
  block_name?: string;
  invigilator_id?: string;
  invigilator_name?: string;
  status: RoomStatus;
  submitted_at?: string;
  total_students: number;
  present_count: number;
  absent_count: number;
  attendance_percentage: number;
  absentees: Array<{
    sl_no: number;
    usn: string;
    name: string;
    branch: string;
  }>;
}

export interface BranchSummaryItem {
  branch: string;
  total_students: number;
  present_count: number;
  absent_count: number;
  attendance_percentage: number;
}

export interface ExamHeaderInfo {
  exam_id: string;
  subject_code: string;
  subject_name?: string;
  date: string;
  start_time: string;
  end_time: string;
  slot?: string;
  total_registered: number;
  total_present: number;
  total_absent: number;
  attendance_pct: number;
}

export interface StudentExamAttendanceRow {
  sl_no: number;
  usn: string;
  name: string;
  branch: string;
  exams_written: number;
  exams_absent: number;
  total_exams: number;
  attendance_pct: number;
  exam_status: Record<string, string>;
  missed_subjects: string[];
}

export interface BranchConsolidationReport {
  branch: string;
  branch_name?: string;
  total_students: number;
  total_exams: number;
  overall_attendance_pct: number;
  perfect_attendance_count: number;
  partial_attendance_count: number;
  exams: ExamHeaderInfo[];
  students: StudentExamAttendanceRow[];
}

export interface MultiExamConsolidationResponse {
  series_title: string;
  semester?: number;
  total_students_college: number;
  total_exams_series: number;
  branches: BranchConsolidationReport[];
}

export interface FormBScanResult {
  message: string;
  matched_count: number;
  extracted_rows: Array<{
    sl_no?: number;
    usn: string;
    name?: string;
    status: "PRESENT" | "ABSENT";
    confidence?: number;
    has_signature?: boolean;
    raw_status_text?: string;
  }>;
  tally?: {
    students_present?: number | string;
    students_absent?: number | string;
    invigilator_initials?: string;
  };
  detected_columns?: Array<{
    column_index?: number;
    date?: string;
    subject_code?: string;
    slot?: string;
  }>;
  target_column_matched?: {
    column_index?: number;
    subject_code?: string;
  };
}

/**
 * Demo mode: Form-B cutoffs are disabled server-side (cutoff_minutes = 0).
 * Any legacy LATE_LOCKED assignment is normalised to OPEN so the UI never
 * shows a lock that can no longer be produced.
 */
function normalizeRoom<T extends { status: RoomStatus; cutoff_at?: string }>(room: T): T {
  if (room.status !== "LATE_LOCKED") return room;
  return { ...room, status: "OPEN", cutoff_at: undefined };
}

export const examsApi = {
  // Admin Endpoints
  async listExams(params?: { date?: string; exam_type?: string }): Promise<ExamItem[]> {
    const query = new URLSearchParams();
    if (params?.date) query.append("date", params.date);
    if (params?.exam_type) query.append("exam_type", params.exam_type);
    const qs = query.toString();
    return apiClient.get<ExamItem[]>(`/api/v1/exams${qs ? `?${qs}` : ""}`);
  },

  async getExam(examId: string): Promise<ExamItem> {
    return apiClient.get<ExamItem>(`/api/v1/exams/${encodeURIComponent(examId)}`);
  },

  async createExam(payload: ExamCreatePayload): Promise<ExamItem> {
    return apiClient.post<ExamItem>("/api/v1/exams", payload);
  },

  async deleteExam(examId: string): Promise<{ message: string }> {
    return apiClient.delete<{ message: string }>(`/api/v1/exams/${encodeURIComponent(examId)}`);
  },

  async uploadSeatingCsv(
    examId: string,
    file: File
  ): Promise<{ message: string; exam_id: string; total_students: number; total_rooms: number }> {
    const formData = new FormData();
    formData.append("file", file);
    return apiClient.post(`/api/v1/exams/${encodeURIComponent(examId)}/seating/upload`, formData);
  },

  async listExamRooms(examId: string): Promise<RoomAssignmentItem[]> {
    const rooms = await apiClient.get<RoomAssignmentItem[]>(`/api/v1/exams/${encodeURIComponent(examId)}/rooms`);
    return rooms.map(normalizeRoom);
  },

  async getRoomAssignment(examId: string, roomNo: string): Promise<RoomAssignmentItem> {
    const room = await apiClient.get<RoomAssignmentItem>(
      `/api/v1/exams/${encodeURIComponent(examId)}/rooms/${encodeURIComponent(roomNo)}`
    );
    return normalizeRoom(room);
  },

  async assignRoomInvigilator(
    examId: string,
    roomNo: string,
    payload: {
      invigilator_id?: string;
      block_name?: string;
      capacity?: number;
      external_examiner_name?: string;
      external_examiner_college?: string;
      coordinator_id?: string;
    }
  ): Promise<RoomAssignmentItem> {
    const room = await apiClient.post<RoomAssignmentItem>(
      `/api/v1/exams/${encodeURIComponent(examId)}/rooms/${encodeURIComponent(roomNo)}/assign`,
      { room_no: roomNo, ...payload }
    );
    return normalizeRoom(room);
  },

  async getInvigilatorCandidates(examId: string): Promise<Array<{
    user_id: string;
    name: string;
    has_timetable_conflict: boolean;
    conflict_details?: string;
    is_already_assigned: boolean;
    assigned_room?: string;
    is_recommended: boolean;
    priority: number;
  }>> {
    return apiClient.get(`/api/v1/exams/${encodeURIComponent(examId)}/invigilator-candidates`);
  },

  async adminOverrideRoom(
    examId: string,
    roomNo: string,
    payload: AdminOverridePayload
  ): Promise<{ message: string; room_status: RoomStatus }> {
    return apiClient.post(
      `/api/v1/exams/${encodeURIComponent(examId)}/rooms/${encodeURIComponent(roomNo)}/admin-override`,
      payload
    );
  },

  // Invigilator Endpoints
  async getMyAssignedRooms(): Promise<RoomAssignmentItem[]> {
    const rooms = await apiClient.get<RoomAssignmentItem[]>("/api/v1/exams/my-rooms");
    return rooms.map(normalizeRoom);
  },

  async getRoomRoster(examId: string, roomNo: string): Promise<ExamSeatingItem[]> {
    return apiClient.get<ExamSeatingItem[]>(
      `/api/v1/exams/${encodeURIComponent(examId)}/rooms/${encodeURIComponent(roomNo)}/roster`
    );
  },

  async markRoomAttendance(
    examId: string,
    roomNo: string,
    payload: BulkMarkPayload
  ): Promise<{ message: string; room_status: RoomStatus }> {
    return apiClient.patch(
      `/api/v1/exams/${encodeURIComponent(examId)}/rooms/${encodeURIComponent(roomNo)}/mark`,
      payload
    );
  },

  async scanFormBPhoto(
    examId: string,
    roomNo: string,
    photoFile: File
  ): Promise<FormBScanResult> {
    const formData = new FormData();
    formData.append("file", photoFile);
    return apiClient.post(
      `/api/v1/exams/${encodeURIComponent(examId)}/rooms/${encodeURIComponent(roomNo)}/scan-photo`,
      formData
    );
  },

  async submitFormB(
    examId: string,
    roomNo: string
  ): Promise<{ message: string; submitted_at?: string; status?: RoomStatus }> {
    return apiClient.post(
      `/api/v1/exams/${encodeURIComponent(examId)}/rooms/${encodeURIComponent(roomNo)}/submit`
    );
  },

  // Summaries & PDF Exports
  async getRoomWiseSummary(examId: string): Promise<RoomSummaryItem[]> {
    const rooms = await apiClient.get<RoomSummaryItem[]>(
      `/api/v1/exams/${encodeURIComponent(examId)}/summary/room-wise`
    );
    return rooms.map((r) => ({ ...r, status: r.status === "LATE_LOCKED" ? "OPEN" : r.status }));
  },

  async getBranchWiseSummary(examId: string): Promise<BranchSummaryItem[]> {
    return apiClient.get<BranchSummaryItem[]>(
      `/api/v1/exams/${encodeURIComponent(examId)}/summary/branch-wise`
    );
  },

  async downloadSignSheetPdf(examId: string, roomNo: string): Promise<Blob> {
    const url = `/api/v1/exams/${encodeURIComponent(examId)}/rooms/${encodeURIComponent(roomNo)}/sign-sheet-pdf`;
    return apiClient.getBlob(url);
  },

  async downloadAbsenteesPdf(examId: string): Promise<Blob> {
    const url = `/api/v1/exams/${encodeURIComponent(examId)}/absentees-pdf`;
    return apiClient.getBlob(url);
  },

  async getBranchConsolidation(params?: {
    semester?: number;
    exam_type?: string;
    branch?: string;
  }): Promise<MultiExamConsolidationResponse> {
    const query = new URLSearchParams();
    if (params?.semester !== undefined) query.append("semester", String(params.semester));
    if (params?.exam_type) query.append("exam_type", params.exam_type);
    if (params?.branch) query.append("branch", params.branch);
    const qs = query.toString();
    return apiClient.get<MultiExamConsolidationResponse>(
      `/api/v1/exams/consolidation/branch-wise${qs ? `?${qs}` : ""}`
    );
  },
};
