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

