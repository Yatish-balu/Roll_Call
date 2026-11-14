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
  is_delegated?: boolean;
  delegation?: {
    delegation_id: string;
    type: string;
    reason?: string;
    from_user_id: string;
    from_name: string;
    to_user_id: string;
    to_name: string;
    is_proxy_for_me: boolean;
  } | null;
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

export interface FacultyColleague {
  user_id: string;
  name: string;
  email: string;
  role: string;
  assigned_subjects: string[];
}

export interface ExtraSessionInput {
  subject_code: string;
  subject_name?: string;
  date: string;
  start_time: string;
  end_time: string;
  room_id: string;
  dept_id?: string;
  semester_number?: number;
  section_id?: string;
  batch_id?: string;
  class_type?: string;
}

export interface ExtraSessionResponse {
  session_id: string;
  date: string;
  subject: string;
  subject_code: string;
  start_time: string;
  end_time: string;
  room_id: string;
  class_type: string;
  students_enrolled: number;
  message: string;
}

export interface ClassDelegationInput {
  session_id: string;
  substitute_faculty_id: string;
  delegation_type?: "PROXY" | "EXCHANGE";
  exchange_session_id?: string;
  reason?: string;
}

export interface ClassDelegationItem {
  delegation_id: string;
  session_id: string;
  original_faculty_id: string;
  original_faculty_name?: string;
  substitute_faculty_id: string;
  substitute_faculty_name?: string;
  delegation_date: string;
  delegation_type: string;
  exchange_session_id?: string;
  reason?: string;
  status: string;
  subject_code?: string;
  subject_name?: string;
  start_time?: string;
  end_time?: string;
  room_id?: string;
  created_at: string;
  updated_at: string;
}

export interface ClassDelegationsReport {
  received: ClassDelegationItem[];
  given: ClassDelegationItem[];
}

export async function fetchFacultyColleagues(): Promise<FacultyColleague[]> {
  return apiClient.get<FacultyColleague[]>("/api/v1/sessions/colleagues");
}

export async function createExtraSession(
  payload: ExtraSessionInput
): Promise<ExtraSessionResponse> {
  return apiClient.post<ExtraSessionResponse>("/api/v1/sessions/extra", payload);
}

export async function createClassDelegation(
  payload: ClassDelegationInput
): Promise<ClassDelegationItem> {
  return apiClient.post<ClassDelegationItem>("/api/v1/sessions/delegations", payload);
}

export async function fetchMyClassDelegations(): Promise<ClassDelegationsReport> {
  return apiClient.get<ClassDelegationsReport>("/api/v1/sessions/delegations/my");
}

export async function cancelClassDelegation(
  delegationId: string
): Promise<{ message: string; delegation_id: string }> {
  return apiClient.delete<{ message: string; delegation_id: string }>(
    `/api/v1/sessions/delegations/${encodeURIComponent(delegationId)}`
  );
}
