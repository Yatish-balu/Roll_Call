import { apiClient } from "@/services/api/client";

export interface SessionAllocation {
  allocation_id: string;
  session_id: string;
  date: string;
  subject?: string;
  subject_code?: string;
  teacher_id?: string;
  faculty_id?: string;
  room_id?: string;
  batch_id?: string;
  start_time: string;
  end_time: string;
  lifecycle_status?: string;
}

export interface SessionItem {
  session_id: string;
  date: string;
  subject?: string;
  subject_code?: string;
  teacher_id?: string;
  created_at?: string;
  allocations?: SessionAllocation[];
}

export interface SessionPage {
  items: SessionItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface SessionCreateParams {
  session_id: string;
  date: string;
  subject: string;
  subject_code?: string;
}

export interface AllocationPage {
  items: SessionAllocation[];
  total: number;
}

export type InitializationStatus =
  | "INITIALIZED"
  | "NO_CLASSES"
  | "PENDING"
  | "FAILED";

export interface InitializationState {
  date: string;
  status: InitializationStatus;
  scheduled_slots: number;
  initialized_sessions: number;
  pending_sessions: number;
  message: string;
}

export interface InitializationResult {
  date: string;
  status: InitializationStatus;
  scheduled_slots: number;
  created_sessions: Array<{
    session_id: string;
    subject_code?: string;
    subject?: string;
    start_time: string;
    end_time: string;
    room_id?: string;
    faculty_id?: string;
    batch_id?: string;
    attendance_rows?: number;
  }>;
  existing_sessions: Array<{
    session_id: string;
    subject_code?: string;
    start_time: string;
    end_time: string;
    room_id?: string;
  }>;
  skipped_slots: Array<{ entry_id: string; subject_code?: string; reason: string }>;
  attendance_rows_prepared: number;
  timetable_count: number;
  message: string;
}

export async function fetchSessions(params?: {
  limit?: number;
  offset?: number;
  date?: string;
  from_date?: string;
  to_date?: string;
}): Promise<SessionPage> {
  return apiClient.get<SessionPage>("/api/v1/sessions", params);
}

export async function getSession(sessionId: string): Promise<SessionItem> {
  return apiClient.get<SessionItem>(`/api/v1/sessions/${encodeURIComponent(sessionId)}`);
}

export async function createSession(data: SessionCreateParams): Promise<SessionItem> {
  return apiClient.post<SessionItem>("/api/v1/sessions", data);
}

/** Real class slots (room, batch, faculty, time) of the visible sessions. */
export async function fetchSessionAllocations(params?: {
  date?: string;
  from_date?: string;
  to_date?: string;
}): Promise<AllocationPage> {
  return apiClient.get<AllocationPage>("/api/v1/sessions/allocations", params);
}

/** Initialisation state of an academic day (read only, never writes). */
export async function fetchInitializationState(
  date?: string
): Promise<InitializationState> {
  return apiClient.get<InitializationState>("/api/v1/sessions/initialization/today", {
    date,
  });
}

/**
 * Ask the backend to prepare the sessions of the academic day from the
 * configured timetable. The operation is idempotent and runs server side.
 */
export async function initializeSessions(date?: string): Promise<InitializationResult> {
  return apiClient.post<InitializationResult>("/api/v1/sessions/initialize", null, {
    params: date ? { date } : undefined,
  });
}
