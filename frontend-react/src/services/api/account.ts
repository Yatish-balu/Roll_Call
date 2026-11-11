import { apiClient } from "@/services/api/client";

/**
 * Account, security and session endpoints of the RollCall AI backend.
 * Every call here maps to a real, existing server contract.
 */

export interface ActiveSession {
  session_id: string;
  created_at: string | null;
  absolute_expiry: string | null;
  revoked_at: string | null;
  user_agent: string | null;
  ip_address: string | null;
  remember_me: boolean;
}

export interface MfaStatus {
  user_id: string;
  mfa_enabled: boolean;
  mfa_available: boolean;
}

export interface MfaEnrollment {
  secret: string;
  recovery_codes: string[];
  message: string;
}

export async function changePassword(params: {
  old_password: string;
  new_password: string;
}): Promise<{ message?: string }> {
  return apiClient.post<{ message?: string }>("/api/v1/auth/password/change", params);
}

export async function fetchMfaStatus(): Promise<MfaStatus> {
  return apiClient.get<MfaStatus>("/api/v1/auth/mfa/status");
}

export async function enableMfa(params: {
  current_password: string;
  code?: string;
}): Promise<MfaEnrollment> {
  return apiClient.post<MfaEnrollment>("/api/v1/auth/mfa/enable", params);
}

export async function verifyMfa(code: string): Promise<{ message?: string }> {
  return apiClient.post<{ message?: string }>("/api/v1/auth/mfa/verify", { code });
}

export async function disableMfa(params: {
  current_password: string;
  code?: string;
}): Promise<{ message?: string }> {
  return apiClient.post<{ message?: string }>("/api/v1/auth/mfa/disable", params);
}

export async function fetchActiveSessions(): Promise<{ sessions: ActiveSession[] }> {
  return apiClient.get<{ sessions: ActiveSession[] }>("/api/v1/auth/sessions");
}

export async function revokeSession(sessionId: string): Promise<{ message?: string }> {
  return apiClient.post<{ message?: string }>(
    `/api/v1/auth/sessions/revoke/${encodeURIComponent(sessionId)}`
  );
}

export async function revokeAllOtherSessions(): Promise<{ message?: string }> {
  return apiClient.post<{ message?: string }>("/api/v1/auth/sessions/revoke-all");
}
