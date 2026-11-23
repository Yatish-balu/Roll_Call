/**
 * API service for RollCall AI Exam Hall & Form-B Control Module
 */

import { apiClient } from "./client";

export type ExamType = "THEORY_CIE" | "LAB_CIE" | "LAB_EXTERNAL" | "THEORY_SEE";
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
    return apiClient.get<RoomAssignmentItem[]>(`/api/v1/exams/${encodeURIComponent(examId)}/rooms`);
  },

  async getRoomAssignment(examId: string, roomNo: string): Promise<RoomAssignmentItem> {
    return apiClient.get<RoomAssignmentItem>(
      `/api/v1/exams/${encodeURIComponent(examId)}/rooms/${encodeURIComponent(roomNo)}`
    );
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
    return apiClient.post<RoomAssignmentItem>(
      `/api/v1/exams/${encodeURIComponent(examId)}/rooms/${encodeURIComponent(roomNo)}/assign`,
      payload
    );
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
    return apiClient.get<RoomAssignmentItem[]>("/api/v1/exams/my-rooms");
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
    return apiClient.get<RoomSummaryItem[]>(
      `/api/v1/exams/${encodeURIComponent(examId)}/summary/room-wise`
    );
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
};
