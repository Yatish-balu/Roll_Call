import { apiClient } from "@/services/api/client";

export interface SessionAllocation {
  allocation_id: number;
  session_id: string;
  room_id: string;
  room_name?: string;
  start_time: string;
  end_time: string;
  batch?: string;
  teacher_id?: string;
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

export async function fetchSessions(params?: {
  limit?: number;
  offset?: number;
  date?: string;
}): Promise<SessionPage> {
  return apiClient.get<SessionPage>("/api/v1/sessions", params);
}

export async function getSession(sessionId: string): Promise<SessionItem> {
  return apiClient.get<SessionItem>(`/api/v1/sessions/${encodeURIComponent(sessionId)}`);
}

export async function createSession(data: SessionCreateParams): Promise<SessionItem> {
  return apiClient.post<SessionItem>("/api/v1/sessions", data);
}

