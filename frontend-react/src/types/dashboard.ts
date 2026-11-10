/**
 * Verified Dashboard Data Models
 * Strictly aligned with FastAPI Pydantic v2 schemas.
 */

export interface VerifiedSession {
  session_id: string;
  date: string;
  subject: string;
  created_at?: string | null;
  teacher_id?: string | null;
  subject_code?: string | null;
}

export interface VerifiedSessionPage {
  items: VerifiedSession[];
  total: number;
  limit: number;
  offset: number;
}

export interface VerifiedOverallSummary {
  present: number;
  absent: number;
  pending: number;
  unreviewed: number;
  unresolved: number;
  confirmed: number;
  total: number;
  percentage: number;
  confirmed_percentage?: number;
  unresolved_by_status?: Record<string, number>;
}

export interface VerifiedSummaryReport {
  room_wise: Array<{
    room_id: string;
    present: number;
    absent: number;
    pending: number;
    unreviewed: number;
    total: number;
    percentage: number;
  }>;
  branch_wise: Array<{
    branch: string;
    present: number;
    absent: number;
    pending: number;
    unreviewed: number;
    total: number;
    percentage: number;
  }>;
  overall: VerifiedOverallSummary;
  session_id?: string | null;
  date?: string | null;
}

export interface VerifiedAgentResponse {
  request_id: string;
  message: string;
  success: boolean;
  needs_confirmation: boolean;
  confirmation_request?: {
    needed: boolean;
    affected_rows: Array<Record<string, unknown>>;
    issues: string[];
    question: string;
  } | null;
  data?: unknown;
  validation_result?: Record<string, unknown> | null;
  summary_report?: Record<string, unknown> | null;
  tool_calls: Array<Record<string, unknown>>;
}

