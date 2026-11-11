import { apiClient } from "@/services/api/client";

export interface ToolCallLog {
  log_id: string;
  request_id: string;
  timestamp: string;
  tool_name: string;
  arguments: Record<string, unknown>;
  success: boolean;
  result_summary: string;
  duration_seconds: number;
  error_message?: string;
}

export interface ConfirmationRequest {
  needed: boolean;
  affected_rows: Array<Record<string, unknown>>;
  issues: string[];
  question: string;
}

export interface AgentResponse {
  request_id: string;
  message: string;
  success: boolean;
  needs_confirmation: boolean;
  confirmation_request?: ConfirmationRequest | null;
  data?: unknown;
  validation_result?: Record<string, unknown> | null;
  summary_report?: Record<string, unknown> | null;
  tool_calls: Array<Record<string, unknown>>;
}

export interface AgentStatus {
  status: string;
  gemini_configured: boolean;
  ollama_available: boolean;
  easyocr_available: boolean;
  confidence_threshold: number;
  available_tools: string[];
}

// ---------------------------------------------------------------------------
// N7: Two-step AI attendance editing (Proposal -> Explicit Confirmation)
// ---------------------------------------------------------------------------

export interface AttendanceEditProposalRequest {
  query?: string;
  session_id?: string;
  usn?: string;
  new_status?: string;
  reason?: string;
  request_id?: string;
}

export interface AttendanceEditProposalResponse {
  status: "proposed" | "clarification_required" | string;
  success: boolean;
  needs_confirmation: boolean;
  confirmation_id?: string | null;
  expires_at?: string | null;
  expires_in_seconds?: number | null;
  session?: {
    session_id?: string;
    date?: string;
    subject?: string;
    subject_code?: string;
    [key: string]: unknown;
  } | null;
  student?: {
    usn?: string;
    name?: string;
    branch?: string;
    [key: string]: unknown;
  } | null;
  current_status?: string | null;
  proposed_status?: string | null;
  confirmation_request?: ConfirmationRequest | null;
  clarification?: {
    question?: string;
    missing?: string[];
    questions?: string[];
    ambiguous?: boolean;
    [key: string]: unknown;
  } | null;
  message: string;
  request_id?: string | null;
  tool_calls?: Array<Record<string, unknown>>;
}

export interface AttendanceEditConfirmRequest {
  confirmation_id: string;
  reason?: string;
  request_id?: string;
}

export interface AttendanceEditConfirmResponse {
  success: boolean;
  status: string;
  confirmation_id: string;
  session_id?: string;
  usn?: string;
  old_status?: string;
  new_status?: string;
  audit_log_id?: number;
  message: string;
  request_id?: string;
}

/**
 * Step A of N7: Propose an attendance modification.
 * Calls POST /api/v1/agent/attendance/propose.
 * Resolves session, student, and status. Returns proposal with confirmation_id
 * or clarification_required if ambiguous.
 */
export async function proposeAttendanceEdit(
  payload: AttendanceEditProposalRequest
): Promise<AttendanceEditProposalResponse> {
  return apiClient.post<AttendanceEditProposalResponse>(
    "/api/v1/agent/attendance/propose",
    payload
  );
}

/**
 * Step B of N7: Explicitly confirm a proposed attendance modification.
 * Calls POST /api/v1/agent/attendance/confirm.
 *
 * CRITICAL SECURITY REQUIREMENT:
 * Sends ONLY confirmation_id (and optional reason/request_id).
 * Never send USN, session_id, new_status, actor, or role.
 */
export async function confirmAttendanceProposal(
  payload: AttendanceEditConfirmRequest
): Promise<AttendanceEditConfirmResponse> {
  const cleanPayload: AttendanceEditConfirmRequest = {
    confirmation_id: payload.confirmation_id,
  };
  if (payload.reason) cleanPayload.reason = payload.reason;
  if (payload.request_id) cleanPayload.request_id = payload.request_id;

  return apiClient.post<AttendanceEditConfirmResponse>(
    "/api/v1/agent/attendance/confirm",
    cleanPayload
  );
}

/**
 * Helper to classify whether a user prompt represents an attendance edit intent
 * (which routes to /agent/attendance/propose) versus a read-only question (which routes to /agent/chat).
 */
export function isAttendanceEditQuery(query: string): boolean {
  const text = query.trim().toLowerCase();
  if (!text) return false;

  // Purely read-only informational question patterns
  const isQuestion =
    /^(why\b|who\s+(was|is|were)\b|how\s+many\b|what\s+(is|was|are|were)\b|which\s+(session|student|class)s?\s+(have|has|are|is|were)\b|summarize\b|summary\b|overview\b|breakdown\b|report\b|list\s+(all\s+)?(students?|sessions?|defaulters?)\b|show\s+(all\s+)?(defaulters?|absentees?|statistics?|trends?|summary|overview)\b)/i.test(
      text
    );

  if (
    isQuestion &&
    !/\b(can\s+you|please|could\s+you)\s+(mark|change|set|update|modify|edit)\b/i.test(
      text
    )
  ) {
    return false;
  }

  // Attendance modification action keywords
  const actionKeywords =
    /\b(mark|change|update|set|modify|edit|switch|correct|turn|make|propose)\b/i;
  const statusKeywords = /\b(present|absent|pending|unreviewed)\b/i;
  const attendanceKeywords = /\b(attendance|status)\b/i;

  // 1. Action + Status (e.g. "mark absent", "change to present", "set 1MS21CS001 present")
  if (actionKeywords.test(text) && statusKeywords.test(text)) {
    return true;
  }

  // 2. Action + Attendance (e.g. "update attendance", "edit attendance for SESS-001", "change attendance")
  if (actionKeywords.test(text) && attendanceKeywords.test(text)) {
    return true;
  }

  // 3. Status assignment like "1MS21CS001 is present", "1MS21CS001 absent", "USN 1MS21CS001 to absent"
  if (
    statusKeywords.test(text) &&
    /\b\d{1,2}[a-z]{2}\d{2}[a-z]{2}\d{3}\b/i.test(text)
  ) {
    return true;
  }

  return false;
}

export async function askAgent(query: string, sessionId?: string): Promise<AgentResponse> {
  return apiClient.post<AgentResponse>("/api/v1/agent/chat", {
    query,
    session_id: sessionId || null,
  });
}

export async function fetchAgentStatus(): Promise<AgentStatus> {
  return apiClient.get<AgentStatus>("/api/v1/agent/status");
}

export async function processAttendanceFile(
  file: File,
  sessionId?: string,
  userConfirmation?: string
): Promise<AgentResponse> {
  const formData = new FormData();
  formData.append("file", file);
  if (sessionId) formData.append("session_id", sessionId);
  if (userConfirmation) formData.append("user_confirmation", userConfirmation);

  return apiClient.post<AgentResponse>("/api/v1/agent/process-file", formData, {
    headers: {
      "Content-Type": "multipart/form-data",
    },
  });
}

export async function confirmAgentRecords(data: {
  session_id: string;
  confirmed: boolean;
  records: Array<Record<string, unknown>>;
  request_id?: string;
}): Promise<AgentResponse> {
  return apiClient.post<AgentResponse>("/api/v1/agent/confirm", data);
}


