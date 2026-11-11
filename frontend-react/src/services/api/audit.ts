import { apiClient } from "@/services/api/client";

export interface AuditLogItem {
  id: string | number;
  timestamp: string;
  event_type: string;
  actor_id: string;
  session_id?: string | null;
  usn?: string | null;
  old_status?: string | null;
  new_status?: string | null;
  reason?: string | null;
}

export interface AuditLogPage {
  items: AuditLogItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface AuditLogQueryParams extends Record<string, string | number | boolean | undefined | null> {
  event_type?: string;
  actor?: string;
  start_date?: string;
  end_date?: string;
  limit?: number;
  offset?: number;
}

/**
 * Fetch the audit trail from the backend.
 *
 * The backend is the only audit authority: entries are written server-side by
 * the attendance write paths, and the frontend never fabricates, records or
 * infers audit events locally. If the backend is unreachable or refuses the
 * request, the error is surfaced to the caller instead of being masked by
 * placeholder data.
 */
export async function fetchAuditLogs(params?: AuditLogQueryParams): Promise<AuditLogPage> {
  return await apiClient.get<AuditLogPage>("/api/v1/admin/audit-logs", params);
}
