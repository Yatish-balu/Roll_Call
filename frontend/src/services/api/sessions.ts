/**
 * Academic Sessions API Data Service
 * Aligned with backend /api/v1/sessions endpoints.
 */

import { apiClient } from "@/services/api/client";

export interface SessionItem {
  session_id: string;
  date: string;
  subject: string;
  subject_code?: string | null;
  teacher_id?: string | null;
  created_at?: string | null;
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
  teacher_id?: string;
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

