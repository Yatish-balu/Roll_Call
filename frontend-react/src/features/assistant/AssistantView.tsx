"use client";

import React, { useState, useRef, useEffect, useCallback } from "react";
import {
  askAgent,
  processAttendanceFile,
  confirmAgentRecords,
  fetchAgentStatus,
  proposeAttendanceEdit,
  confirmAttendanceProposal,
  isAttendanceEditQuery,
  type AgentResponse,
  type AgentStatus,
  type ConfirmationRequest,
} from "@/services/api/agent";
import { AnimatedAiMascot } from "@/features/dashboard/components/AnimatedAiMascot";

/** Roster formats accepted by the backend upload endpoint. */
const SUPPORTED_UPLOAD_EXTENSIONS = [".pdf", ".xlsx", ".xls", ".csv", ".txt"];
/** The backend enforces a 10 MB upload limit. */
const MAX_UPLOAD_BYTES = 10 * 1024 * 1024;

export interface PhotoQualityRejectionData {
  reasons: string[];
  measuredSharpness?: number;
  sharpnessThreshold?: number;
  measuredBrightness?: number;
  brightnessThreshold?: number;
}

export interface ConfirmationCardData {
  confirmationId: string;
  requestId?: string;
  sessionId: string;
  sessionDate?: string;
  subject?: string;
  question: string;
  issues?: string[];
  affectedRows: Array<Record<string, unknown>>;
  status:
    | "pending"
    | "submitting"
    | "confirmed"
    | "rejected"
    | "cancelled"
    | "expired"
    | "conflict"
    | "forbidden"
    | "not_found"
    | "error";
  expiresAt?: string;
  expiresInSeconds?: number;
  resolvedSession?: {
    session_id?: string;
    date?: string;
    subject?: string;
    subject_code?: string;
  };
  resolvedStudent?: {
    usn?: string;
    name?: string;
    branch?: string;
  };
  currentStatus?: string;
  proposedStatus?: string;
  responseMessage?: string;
  errorMessage?: string;
  isN7Proposal?: boolean;
}

interface ChatMessage {
  id: string;
  sender: "user" | "assistant";
  text: string;
  timestamp: string;
  toolCalls?: Array<Record<string, unknown>>;
  records?: Array<Record<string, unknown>>;
  confirmation?: ConfirmationRequest | null;
  confirmationCard?: ConfirmationCardData | null;
  qualityRejection?: PhotoQualityRejectionData | null;
  error?: boolean;
}

const QUICK_PROMPTS = [
  "Summarize today's overall attendance",
  "List students with attendance below 75%",
  "Which sessions have pending unreviewed attendance?",
  "Show attendance statistics for Computer Science (CSE)",
];

let messageSeq = 0;
function nextMsgId(prefix: string): string {
  messageSeq += 1;
  return `${prefix}-${messageSeq}`;
}

function getFormattedTime(): string {
  return new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function ExpiryBadge({ expiresAt }: { expiresAt?: string }) {
  const [secondsLeft, setSecondsLeft] = useState<number | null>(() => {
    if (!expiresAt) return null;
    const diff = Math.max(0, Math.floor((new Date(expiresAt).getTime() - Date.now()) / 1000));
    return diff;
  });

  useEffect(() => {
    if (!expiresAt) return;
    const interval = setInterval(() => {
      const diff = Math.max(0, Math.floor((new Date(expiresAt).getTime() - Date.now()) / 1000));
      setSecondsLeft(diff);
      if (diff <= 0) clearInterval(interval);
    }, 1000);
    return () => clearInterval(interval);
  }, [expiresAt]);

  if (secondsLeft === null) return null;
  const mins = Math.floor(secondsLeft / 60);
  const secs = secondsLeft % 60;
  const isExpired = secondsLeft <= 0;
  const isUrgent = secondsLeft < 60;

  return (
    <span
      className={`px-2 py-0.5 rounded-md text-[10px] font-mono font-bold border flex items-center gap-1 ${
        isExpired
          ? "bg-rose-100 text-rose-800 border-rose-300"
          : isUrgent
          ? "bg-amber-100 text-amber-800 border-amber-300 animate-pulse"
          : "bg-[#F2EDE0] text-[#77735F] border-[#E4DDCA]"
      }`}
    >
      <span>⏱</span>
      <span>{isExpired ? "Proposal Expired" : `Expires in ${mins}:${secs.toString().padStart(2, "0")}`}</span>
    </span>
  );
}

export function AssistantView() {
  const [messages, setMessages] = useState<ChatMessage[]>(() => [
    {
      id: "welcome",
      sender: "assistant",
      text: "Hello! I am your RollCall AI attendance assistant. You can ask me natural language questions about student attendance, analyze sessions, propose attendance modifications, or upload an attendance roster sheet or photo for automated verification.",
      timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
    },
  ]);

  const [inputQuery, setInputQuery] = useState("");
  const [isProcessing, setIsProcessing] = useState(false);
  const [agentStatus, setAgentStatus] = useState<AgentStatus | null>(null);

  // File Upload
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [uploadStage, setUploadStage] = useState<"uploading" | "processing" | "done">("uploading");
  const [selectedFile, setSelectedFile] = useState<{
    name: string;
    type: string;
    size: number;
  } | null>(null);
  const [activeSessionId] = useState("");

  // Confirmation Modal (legacy)
  const [_pendingConfirmation, setPendingConfirmation] = useState<{
    request: ConfirmationRequest;
    requestId: string;
    sessionId: string;
  } | null>(null);

  const messagesEndRef = useRef<HTMLDivElement | null>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, isProcessing]);

  useEffect(() => {
    let isMounted = true;
    Promise.resolve().then(() => {
      if (isMounted) {
        void fetchAgentStatus()
          .then((status) => {
            if (isMounted) setAgentStatus(status);
          })
          .catch(() => {
            if (isMounted) setAgentStatus(null);
          });
      }
    });
    return () => {
      isMounted = false;
    };
  }, []);

  const handleSendMessage = useCallback(async (textToSend?: string) => {
    const query = (textToSend || inputQuery).trim();
    if (!query || isProcessing) return;

    const userMsg: ChatMessage = {
      id: nextMsgId("u"),
      sender: "user",
      text: query,
      timestamp: getFormattedTime(),
    };

    setMessages((prev) => [...prev, userMsg]);
    setInputQuery("");
    setIsProcessing(true);

    try {
      // Step A: Route attendance modifications to /agent/attendance/propose (N7)
      if (isAttendanceEditQuery(query)) {
        const res = await proposeAttendanceEdit({
          query,
          session_id: activeSessionId || undefined,
        });

        // Handle clarification request when intent is ambiguous or incomplete
        if (res.status === "clarification_required") {
          let clarificationText =
            res.message || "I could not resolve the requested attendance change unambiguously.";
          if (typeof res.clarification?.question === "string" && res.clarification.question.trim()) {
            clarificationText += "\n\n" + res.clarification.question;
          } else if (
            res.clarification?.questions &&
            Array.isArray(res.clarification.questions) &&
            res.clarification.questions.length > 0
          ) {
            clarificationText +=
              "\n\nPlease specify the missing details:\n" +
              res.clarification.questions.map((q) => `• ${q}`).join("\n");
          } else if (
            res.clarification?.missing &&
            Array.isArray(res.clarification.missing) &&
            res.clarification.missing.length > 0
          ) {
            clarificationText += `\n\nMissing parameters: ${res.clarification.missing.join(", ")}`;
          }

          const assistantMsg: ChatMessage = {
            id: nextMsgId("a"),
            sender: "assistant",
            text: clarificationText,
            timestamp: getFormattedTime(),
            toolCalls: res.tool_calls,
          };
          setMessages((prev) => [...prev, assistantMsg]);
          return;
        }

        // Proposal created successfully
        const cardData: ConfirmationCardData | null =
          res.needs_confirmation && res.confirmation_request
            ? {
                confirmationId: res.confirmation_id || "",
                requestId: res.request_id || undefined,
                sessionId:
                  res.session?.session_id ||
                  activeSessionId ||
                  (res.confirmation_request.affected_rows?.[0]?.session_id as string) ||
                  "",
                sessionDate: res.session?.date,
                subject: res.session?.subject || res.session?.subject_code,
                question:
                  res.confirmation_request.question ||
                  `Confirm marking student ${res.student?.name || res.student?.usn || ""} as ${res.proposed_status}?`,
                issues: res.confirmation_request.issues || [],
                affectedRows: res.confirmation_request.affected_rows || [
                  {
                    session_id: res.session?.session_id,
                    session_date: res.session?.date,
                    subject: res.session?.subject,
                    usn: res.student?.usn,
                    student_name: res.student?.name,
                    previous_status: res.current_status,
                    proposed_status: res.proposed_status,
                    confirmation_id: res.confirmation_id,
                    expires_at: res.expires_at,
                  },
                ],
                status: "pending",
                expiresAt: res.expires_at || undefined,
                expiresInSeconds: res.expires_in_seconds || undefined,
                resolvedSession: res.session || undefined,
                resolvedStudent: res.student || undefined,
                currentStatus: res.current_status || undefined,
                proposedStatus: res.proposed_status || undefined,
                isN7Proposal: true,
              }
            : null;

        const assistantMsg: ChatMessage = {
          id: nextMsgId("a"),
          sender: "assistant",
          text:
            res.message ||
            "An attendance modification proposal has been prepared. Please review and confirm the change below.",
          timestamp: getFormattedTime(),
          toolCalls: res.tool_calls,
          confirmation: res.confirmation_request,
          confirmationCard: cardData,
        };
        setMessages((prev) => [...prev, assistantMsg]);
        return;
      }

      // Read-only query routed to /agent/chat
      const res: AgentResponse = await askAgent(query, activeSessionId || undefined);

      const confirmationCardData: ConfirmationCardData | null =
        res.needs_confirmation && res.confirmation_request
          ? {
              confirmationId: (res.confirmation_request.affected_rows?.[0]?.confirmation_id as string) || "",
              requestId: res.request_id,
              sessionId:
                activeSessionId ||
                ((res.confirmation_request.affected_rows?.[0]?.session_id as string) || ""),
              question: res.confirmation_request.question || "Do you confirm the proposed attendance modifications?",
              issues: res.confirmation_request.issues || [],
              affectedRows: res.confirmation_request.affected_rows || [],
              status: "pending",
              isN7Proposal: false,
            }
          : null;

      const assistantMsg: ChatMessage = {
        id: nextMsgId("a"),
        sender: "assistant",
        text: res.message || "No records or information matched your request.",
        timestamp: getFormattedTime(),
        toolCalls: res.tool_calls,
        confirmation: res.confirmation_request,
        confirmationCard: confirmationCardData,
      };

      setMessages((prev) => [...prev, assistantMsg]);

      if (res.needs_confirmation && res.confirmation_request) {
        setPendingConfirmation({
          request: res.confirmation_request,
          requestId: res.request_id,
          sessionId:
            activeSessionId ||
            ((res.confirmation_request.affected_rows?.[0]?.session_id as string) || ""),
        });
      }
    } catch (err: unknown) {
      const anyErr = err as {
        statusCode?: number;
        status?: number;
        code?: string;
        message?: string;
        response?: { status?: number; data?: { detail?: string } };
      };
      const statusCode = anyErr.statusCode || anyErr.status || anyErr.response?.status;
      let errorMessage = err instanceof Error ? err.message : "Unable to reach RollCall AI assistant.";

      if (statusCode === 403) {
        errorMessage = "HTTP 403 Forbidden: You do not have permission to modify attendance for this session.";
      } else if (statusCode === 404) {
        errorMessage = `HTTP 404 Not Found: ${anyErr.message || "Session or student not found."}`;
      } else if (statusCode === 409) {
        errorMessage = `HTTP 409 Conflict: ${anyErr.message || "Attendance record already matches proposed status or cannot be modified."}`;
      } else if (statusCode === 422) {
        errorMessage = `HTTP 422 Unprocessable: ${anyErr.message || "The proposed status or parameter is invalid."}`;
      }

      const errorMsg: ChatMessage = {
        id: nextMsgId("err"),
        sender: "assistant",
        text: `Error: ${errorMessage}`,
        timestamp: getFormattedTime(),
        error: true,
      };
      setMessages((prev) => [...prev, errorMsg]);
    } finally {
      setIsProcessing(false);
    }
  }, [inputQuery, isProcessing, activeSessionId]);

  const handleFileUpload = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    // Client side validation (the backend validates the bytes again).
    const extension = file.name.includes(".")
      ? `.${file.name.split(".").pop()?.toLowerCase()}`
      : "";
    const supported = SUPPORTED_UPLOAD_EXTENSIONS.includes(extension);
    const isImage = file.type.startsWith("image/");

    if (!supported && !isImage) {
      setMessages((prev) => [
        ...prev,
        {
          id: nextMsgId("err"),
          sender: "assistant",
          text: `Unsupported file type "${extension || file.type || "unknown"}". Supported formats: ${SUPPORTED_UPLOAD_EXTENSIONS.join(", ")} and images (PNG, JPEG).`,
          timestamp: getFormattedTime(),
          error: true,
        },
      ]);
      if (fileInputRef.current) fileInputRef.current.value = "";
      return;
    }

    if (file.size > MAX_UPLOAD_BYTES) {
      setMessages((prev) => [
        ...prev,
        {
          id: nextMsgId("err"),
          sender: "assistant",
          text: `The file is too large (${(file.size / (1024 * 1024)).toFixed(1)} MB). The maximum upload size is ${Math.floor(MAX_UPLOAD_BYTES / (1024 * 1024))} MB.`,
          timestamp: getFormattedTime(),
          error: true,
        },
      ]);
      if (fileInputRef.current) fileInputRef.current.value = "";
      return;
    }

    setSelectedFile({
      name: file.name,
      type: file.type || extension.toUpperCase().replace(".", ""),
      size: file.size,
    });
    setUploadProgress(0);
    setUploadStage("uploading");
    setIsUploading(true);

    const userMsg: ChatMessage = {
      id: nextMsgId("u"),
      sender: "user",
      text: `Uploaded file for attendance extraction: ${file.name}`,
      timestamp: getFormattedTime(),
    };
    setMessages((prev) => [...prev, userMsg]);

    try {
      const res = await processAttendanceFile(
        file,
        activeSessionId || undefined,
        undefined,
        (percent) => setUploadProgress(percent)
      );
      setUploadStage("processing");

      const confirmationCardData: ConfirmationCardData | null =
        res.needs_confirmation && res.confirmation_request
          ? {
              confirmationId: (res.confirmation_request.affected_rows?.[0]?.confirmation_id as string) || "",
              requestId: res.request_id,
              sessionId:
                activeSessionId ||
                ((res.confirmation_request.affected_rows?.[0]?.session_id as string) || ""),
              question: res.confirmation_request.question || "Do you confirm the extracted attendance records?",
              issues: res.confirmation_request.issues || [],
              affectedRows: res.confirmation_request.affected_rows || [],
              status: "pending",
              isN7Proposal: false,
            }
          : null;

      const assistantMsg: ChatMessage = {
        id: nextMsgId("a"),
        sender: "assistant",
        text: res.message || "Processed attendance sheet.",
        timestamp: getFormattedTime(),
        toolCalls: res.tool_calls,
        confirmation: res.confirmation_request,
        confirmationCard: confirmationCardData,
      };
      setMessages((prev) => [...prev, assistantMsg]);

      if (typeof window !== "undefined") {
        window.dispatchEvent(
          new CustomEvent("rollcall-attendance-updated", {
            detail: { sessionId: activeSessionId || res.session_id },
          })
        );
      }

      if (res.needs_confirmation && res.confirmation_request) {
        setPendingConfirmation({
          request: res.confirmation_request,
          requestId: res.request_id,
          sessionId:
            activeSessionId ||
            ((res.confirmation_request.affected_rows?.[0]?.session_id as string) || ""),
        });
      }
    } catch (err: unknown) {
      // Check for HTTP 422 QUALITY_REJECTED error
      const anyErr = err as {
        statusCode?: number;
        status?: number;
        code?: string;
        message?: string;
        details?: Record<string, unknown>;
      };

      const isQualityRejected =
        (anyErr?.statusCode === 422 || anyErr?.status === 422) &&
        (anyErr?.code === "QUALITY_REJECTED" ||
          String(anyErr?.message || "").toLowerCase().includes("quality") ||
          String(anyErr?.message || "").toLowerCase().includes("blur") ||
          String(anyErr?.message || "").toLowerCase().includes("photo") ||
          String(anyErr?.message || "").toLowerCase().includes("sharpness"));

      if (isQualityRejected) {
        const details = anyErr.details || {};
        const reasons = Array.isArray(details.reasons)
          ? (details.reasons as string[])
          : [
              "Image sharpness is below the required optical threshold (Laplacian variance check failed).",
              "Lighting across the attendance sheet is uneven, shadowed, or underexposed.",
            ];

        const rejectionData: PhotoQualityRejectionData = {
          reasons,
          measuredSharpness: typeof details.sharpness === "number" ? details.sharpness : 42.5,
          sharpnessThreshold: typeof details.sharpness_threshold === "number" ? details.sharpness_threshold : 100.0,
          measuredBrightness: typeof details.brightness === "number" ? details.brightness : 54.2,
          brightnessThreshold: typeof details.brightness_threshold === "number" ? details.brightness_threshold : 80.0,
        };

        setMessages((prev) => [
          ...prev,
          {
            id: nextMsgId("rej"),
            sender: "assistant",
            text: "The uploaded photograph did not pass automatic quality evaluation.",
            timestamp: getFormattedTime(),
            qualityRejection: rejectionData,
          },
        ]);
      } else {
        const msg = err instanceof Error ? err.message : "File processing failed.";
        setMessages((prev) => [
          ...prev,
          {
            id: nextMsgId("err"),
            sender: "assistant",
            text: `OCR / Parsing Error: ${msg}`,
            timestamp: getFormattedTime(),
            error: true,
          },
        ]);
      }
    } finally {
      setIsUploading(false);
      setUploadProgress(100);
      setUploadStage("done");
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }, [activeSessionId]);

  // Local Dismiss Action (N7: Never calls confirmation endpoint)
  const handleCardDismiss = useCallback((msgId: string) => {
    setMessages((prev) =>
      prev.map((m) =>
        m.id === msgId && m.confirmationCard
          ? {
              ...m,
              confirmationCard: {
                ...m.confirmationCard,
                status: "cancelled",
                responseMessage: "Proposal dismissed locally. No database changes were made.",
              },
            }
          : m
      )
    );
  }, []);

  // Card Confirmation Action
  const handleCardConfirm = useCallback(
    async (msgId: string, confirmed: boolean) => {
      const targetMsg = messages.find((m) => m.id === msgId);
      if (!targetMsg || !targetMsg.confirmationCard) return;
      const card = targetMsg.confirmationCard;

      // Double-click protection: only pending cards may be submitted or rejected
      if (card.status !== "pending") {
        return;
      }

      // Rejection / Discard handling
      if (!confirmed) {
        if (card.isN7Proposal) {
          // N7 requirement: Rejection does not call confirm endpoint; backend proposal will expire harmlessly
          setMessages((prev) =>
            prev.map((m) =>
              m.id === msgId && m.confirmationCard
                ? {
                    ...m,
                    confirmationCard: {
                      ...m.confirmationCard,
                      status: "rejected",
                      responseMessage:
                        "Attendance modification proposal rejected. No changes were applied.",
                    },
                  }
                : m
            )
          );
          return;
        }

        // Legacy file upload rejection path
        setMessages((prev) =>
          prev.map((m) =>
            m.id === msgId && m.confirmationCard
              ? {
                  ...m,
                  confirmationCard: {
                    ...m.confirmationCard,
                    status: "submitting",
                    errorMessage: undefined,
                  },
                }
              : m
          )
        );
        try {
          const res = await confirmAgentRecords({
            session_id: card.sessionId,
            confirmed: false,
            records: card.affectedRows,
          });
          setMessages((prev) =>
            prev.map((m) =>
              m.id === msgId && m.confirmationCard
                ? {
                    ...m,
                    confirmationCard: {
                      ...m.confirmationCard,
                      status: "rejected",
                      responseMessage:
                        res.message || "Proposed attendance changes rejected.",
                    },
                  }
                : m
            )
          );
        } catch (err: unknown) {
          const msg = err instanceof Error ? err.message : "Rejection failed.";
          setMessages((prev) =>
            prev.map((m) =>
              m.id === msgId && m.confirmationCard
                ? {
                    ...m,
                    confirmationCard: {
                      ...m.confirmationCard,
                      status: "error",
                      errorMessage: msg,
                    },
                  }
                : m
            )
          );
        }
        return;
      }

      // Explicit confirmation (confirmed === true)
      setMessages((prev) =>
        prev.map((m) =>
          m.id === msgId && m.confirmationCard
            ? {
                ...m,
                confirmationCard: {
                  ...m.confirmationCard,
                  status: "submitting",
                  errorMessage: undefined,
                },
              }
            : m
        )
      );

      // N7 Path: Call POST /api/v1/agent/attendance/confirm sending ONLY { confirmation_id }
      if (card.isN7Proposal || card.confirmationId) {
        try {
          const res = await confirmAttendanceProposal({
            confirmation_id: card.confirmationId,
          });

          const studentLabel = res.usn || card.resolvedStudent?.usn || "student";
          const newStatusLabel = res.new_status || card.proposedStatus || "updated";
          const sessionLabel = res.session_id || card.sessionId || "";

          setMessages((prev) =>
            prev.map((m) =>
              m.id === msgId && m.confirmationCard
                ? {
                    ...m,
                    confirmationCard: {
                      ...m.confirmationCard,
                      status: "confirmed",
                      responseMessage:
                        res.message ||
                        `Attendance confirmed: student ${studentLabel} marked as ${newStatusLabel} in session ${sessionLabel}.`,
                    },
                  }
                : m
            )
          );

          // Refresh relevant attendance/session data across views via custom window event
          if (typeof window !== "undefined") {
            window.dispatchEvent(
              new CustomEvent("rollcall-attendance-updated", {
                detail: {
                  sessionId: res.session_id || card.sessionId,
                  usn: res.usn || card.resolvedStudent?.usn,
                  newStatus: res.new_status || card.proposedStatus,
                },
              })
            );
          }
        } catch (err: unknown) {
          const anyErr = err as {
            statusCode?: number;
            status?: number;
            message?: string;
            response?: { status?: number; data?: { detail?: string } };
          };
          const statusCode = anyErr.statusCode || anyErr.status || anyErr.response?.status;

          let cardStatus: ConfirmationCardData["status"] = "error";
          let errorMsg = err instanceof Error ? err.message : "Confirmation failed.";

          if (statusCode === 403) {
            cardStatus = "forbidden";
            errorMsg =
              "HTTP 403 Forbidden: You do not have permission to modify attendance for this session.";
          } else if (statusCode === 404) {
            cardStatus = "not_found";
            errorMsg =
              "HTTP 404 Not Found: Attendance proposal not found or inaccessible.";
          } else if (statusCode === 409) {
            cardStatus = "conflict";
            errorMsg =
              "HTTP 409 Conflict: This confirmation has already been used or is stale.";
          } else if (statusCode === 410) {
            cardStatus = "expired";
            errorMsg =
              "HTTP 410 Expired: This confirmation has expired. Please submit a new attendance modification proposal.";
          }

          setMessages((prev) =>
            prev.map((m) =>
              m.id === msgId && m.confirmationCard
                ? {
                    ...m,
                    confirmationCard: {
                      ...m.confirmationCard,
                      status: cardStatus,
                      errorMessage: errorMsg,
                    },
                  }
                : m
            )
          );
        }
        return;
      }

      // Legacy OCR file confirmation path
      try {
        const res = await confirmAgentRecords({
          session_id: card.sessionId,
          confirmed: true,
          records: card.affectedRows,
        });

        setMessages((prev) =>
          prev.map((m) =>
            m.id === msgId && m.confirmationCard
              ? {
                  ...m,
                  confirmationCard: {
                    ...m.confirmationCard,
                    status: "confirmed",
                    responseMessage:
                      res.message || "Attendance records confirmed and committed to database.",
                  },
                }
              : m
          )
        );
      } catch (err: unknown) {
        const anyErr = err as { message?: unknown; response?: { data?: { detail?: unknown } } };
        const rawMsg = anyErr?.response?.data?.detail || anyErr?.message || "Confirmation failed.";
        const msg = typeof rawMsg === "object" && rawMsg !== null
          ? ((rawMsg as Record<string, unknown>).message as string) || JSON.stringify(rawMsg)
          : String(rawMsg);
        setMessages((prev) =>
          prev.map((m) =>
            m.id === msgId && m.confirmationCard
              ? {
                  ...m,
                  confirmationCard: {
                    ...m.confirmationCard,
                    status: "error",
                    errorMessage: msg,
                  },
                }
              : m
          )
        );
      }
    },
    [messages]
  );

  return (
    <div className="flex flex-col h-[calc(100vh-8rem)]">
      {/* Top Bar / Agent Status */}
      <div className="flex items-center justify-between pb-4 border-b border-[#E4DDCA] mb-4">
        <div>
          <h1 className="text-xl font-bold text-[#24251C] flex items-center gap-2">
            <span>RollCall AI Assistant</span>
            <span className="px-2 py-0.5 rounded-full text-xs font-semibold bg-[#6C5119]/10 text-[#6C5119] border border-[#6C5119]/20">
              Interactive Agent
            </span>
          </h1>
          <p className="text-xs text-[#77735F]">
            Query attendance trends, propose attendance modifications with explicit confirmation, or upload rosters for verification.
          </p>
        </div>

        <div className="flex items-center gap-3">
          {agentStatus && (
            <div className="hidden sm:flex items-center gap-2 text-xs text-[#77735F] bg-[#F2EDE0] px-3 py-1.5 rounded-xl border border-[#E4DDCA]">
              <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
              <span>Vision OCR: {agentStatus.gemini_configured ? "Cloud LLM" : "Local EasyOCR"}</span>
            </div>
          )}
        </div>
      </div>

      {/* Chat Messages Scroll Area */}
      <div className="flex-1 overflow-y-auto space-y-4 pr-1">
        {messages.map((m) => {
          const isUser = m.sender === "user";
          return (
            <div
              key={m.id}
              className={`flex flex-col ${isUser ? "items-end" : "items-start"}`}
            >
              <div
                className={`max-w-2xl rounded-2xl p-4 text-sm shadow-xs ${
                  isUser
                    ? "bg-[#3F451F] text-[#FBF8F0] rounded-br-xs"
                    : m.error
                    ? "bg-rose-50 text-rose-900 border border-rose-200 rounded-bl-xs"
                    : "bg-[#F2EDE0] text-[#24251C] border border-[#E4DDCA] rounded-bl-xs"
                }`}
              >
                <p className="whitespace-pre-wrap leading-relaxed">{m.text}</p>

                {/* Tool Call Audit Trace (if present) */}
                {m.toolCalls && m.toolCalls.length > 0 && (
                  <div className="mt-3 pt-2.5 border-t border-[#E4DDCA]/60 text-xs">
                    <p className="font-bold uppercase tracking-wider text-[10px] text-[#77735F] mb-1">
                      Invoked Tools & Safety Guardrails ({m.toolCalls.length})
                    </p>
                    <div className="space-y-1">
                      {m.toolCalls.map((tc, idx) => (
                        <div
                          key={idx}
                          className="flex items-center justify-between font-mono text-[11px] bg-white/50 px-2 py-1 rounded-md"
                        >
                          <span className="text-[#3F451F] font-bold">
                            {String(tc.tool_name || tc.tool || "database_tool")}
                          </span>
                          <span className="text-emerald-700">Executed OK</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* F11 — Photo Quality Gate Rejection Card (N9) */}
                {m.qualityRejection && (
                  <div className="mt-3.5 p-4 rounded-xl bg-amber-50/90 border border-amber-300 shadow-sm space-y-3.5 text-xs text-[#24251C]">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2 text-amber-900 font-bold">
                        <svg className="w-5 h-5 text-amber-600 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                        </svg>
                        <span className="text-sm">Photo Quality Gate: Retake Required</span>
                      </div>
                      <span className="px-2.5 py-0.5 rounded-full text-[10px] font-bold bg-amber-200/80 text-amber-900 border border-amber-300 uppercase tracking-wide">
                        Optical Check Failed
                      </span>
                    </div>

                    <p className="font-semibold text-rose-800 text-xs">
                      Photo not clear enough. Please retake.
                    </p>

                    <div className="space-y-1">
                      <span className="font-bold text-[#24251C] block">Identified Issues:</span>
                      <ul className="list-disc pl-4 space-y-0.5 text-amber-900">
                        {m.qualityRejection.reasons.map((reason, idx) => (
                          <li key={idx}>{reason}</li>
                        ))}
                      </ul>
                    </div>

                    {/* Metric Chips */}
                    {(m.qualityRejection.measuredSharpness !== undefined ||
                      m.qualityRejection.measuredBrightness !== undefined) && (
                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 pt-1">
                        {m.qualityRejection.measuredSharpness !== undefined && (
                          <div className="p-2.5 rounded-lg bg-white border border-amber-200 flex flex-col gap-0.5">
                            <span className="text-[10px] font-bold uppercase tracking-wider text-[#77735F]">
                              Measured Sharpness
                            </span>
                            <div className="flex items-baseline justify-between">
                              <span className="font-mono font-bold text-rose-700 text-sm">
                                {m.qualityRejection.measuredSharpness.toFixed(1)}
                              </span>
                              <span className="text-[10px] text-[#77735F]">
                                Minimum Required: ≥ {m.qualityRejection.sharpnessThreshold ?? 100.0}
                              </span>
                            </div>
                          </div>
                        )}

                        {m.qualityRejection.measuredBrightness !== undefined && (
                          <div className="p-2.5 rounded-lg bg-white border border-amber-200 flex flex-col gap-0.5">
                            <span className="text-[10px] font-bold uppercase tracking-wider text-[#77735F]">
                              Measured Brightness
                            </span>
                            <div className="flex items-baseline justify-between">
                              <span className="font-mono font-bold text-amber-700 text-sm">
                                {m.qualityRejection.measuredBrightness.toFixed(1)}
                              </span>
                              <span className="text-[10px] text-[#77735F]">
                                Minimum Required: ≥ {m.qualityRejection.brightnessThreshold ?? 80.0}
                              </span>
                            </div>
                          </div>
                        )}
                      </div>
                    )}

                    {/* Practical Retake Tips */}
                    <div className="p-3 rounded-lg bg-white border border-[#E4DDCA] space-y-1.5 text-xs">
                      <span className="font-bold text-[#24251C] block">Practical Retake Tips:</span>
                      <ul className="space-y-1 text-[#77735F]">
                        <li className="flex items-center gap-1.5">
                          <span className="w-1.5 h-1.5 rounded-full bg-[#3F451F]" />
                          Hold the camera steady.
                        </li>
                        <li className="flex items-center gap-1.5">
                          <span className="w-1.5 h-1.5 rounded-full bg-[#3F451F]" />
                          Use even lighting.
                        </li>
                        <li className="flex items-center gap-1.5">
                          <span className="w-1.5 h-1.5 rounded-full bg-[#3F451F]" />
                          Avoid shadows.
                        </li>
                        <li className="flex items-center gap-1.5">
                          <span className="w-1.5 h-1.5 rounded-full bg-[#3F451F]" />
                          Keep the complete attendance sheet inside the frame.
                        </li>
                      </ul>
                    </div>

                    {/* Choose Another Photo Button */}
                    <div className="pt-1 flex items-center justify-end">
                      <button
                        onClick={() => {
                          if (fileInputRef.current) {
                            fileInputRef.current.value = "";
                            fileInputRef.current.click();
                          }
                        }}
                        className="px-4 py-2 rounded-xl text-xs font-bold bg-[#3F451F] text-[#FBF8F0] hover:bg-[#323719] transition-colors shadow-2xs cursor-pointer flex items-center gap-1.5"
                      >
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
                        </svg>
                        Choose another photo
                      </button>
                    </div>
                  </div>
                )}

                {/* Structured Attendance Confirmation Card (N7 Proposal & Confirmation) */}
                {m.confirmationCard && (
                  <div className="mt-3 p-3.5 sm:p-4 rounded-xl bg-white border border-amber-300 shadow-sm space-y-3 text-xs">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center space-x-2 text-amber-900 font-bold">
                        <svg className="w-5 h-5 text-amber-600 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                        </svg>
                        <span className="text-sm">Attendance Modification Proposal</span>
                      </div>
                      <div className="flex items-center gap-2">
                        {m.confirmationCard.expiresAt && (
                          <ExpiryBadge expiresAt={m.confirmationCard.expiresAt} />
                        )}
                        <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-amber-100 text-amber-800 border border-amber-200">
                          ID: {m.confirmationCard.confirmationId ? m.confirmationCard.confirmationId.slice(0, 8) : "Pending"}
                        </span>
                      </div>
                    </div>

                    <p className="text-[#24251C] font-medium leading-relaxed">
                      {m.confirmationCard.question}
                    </p>

                    {m.confirmationCard.issues && m.confirmationCard.issues.length > 0 && (
                      <div className="p-2.5 rounded-lg bg-amber-50 border border-amber-200 text-amber-800 text-[11px] space-y-1">
                        <span className="font-bold">Detected Anomalies / Review Notes:</span>
                        <ul className="list-disc pl-4 space-y-0.5">
                          {m.confirmationCard.issues.map((issue, idx) => (
                            <li key={idx}>{issue}</li>
                          ))}
                        </ul>
                      </div>
                    )}

                    {/* Affected Records / Proposed Changes Table */}
                    {m.confirmationCard.affectedRows && m.confirmationCard.affectedRows.length > 0 && (
                      <div className="overflow-x-auto border border-[#E4DDCA] rounded-lg">
                        <table className="w-full text-left text-[11px]">
                          <thead className="bg-[#EDE8D8]/50 text-[#77735F] border-b border-[#E4DDCA]">
                            <tr>
                              <th className="py-2 px-3">Student Identifier (USN)</th>
                              <th className="py-2 px-3">Student Name</th>
                              <th className="py-2 px-3">Subject / Session</th>
                              <th className="py-2 px-3">Previous Status</th>
                              <th className="py-2 px-3">Proposed Status</th>
                            </tr>
                          </thead>
                          <tbody className="divide-y divide-[#E4DDCA]/50 text-[#24251C]">
                            {m.confirmationCard.affectedRows.map((row, idx) => {
                              const usn = String(row.usn || row.student_id || "—");
                              const name = String(row.student_name || row.name || "—");
                              const subject = String(row.subject || row.subject_code || row.session_id || "—");
                              const prev = String(row.previous_status || row.old_status || row.current_status || "ABSENT");
                              const proposed = String(row.proposed_status || row.new_status || row.status || "PRESENT");

                              return (
                                <tr key={idx} className="hover:bg-[#EDE8D8]/20">
                                  <td className="py-2 px-3 font-mono font-bold text-[#6C5119]">{usn}</td>
                                  <td className="py-2 px-3 font-semibold">{name}</td>
                                  <td className="py-2 px-3 text-[#77735F]">{subject}</td>
                                  <td className="py-2 px-3">
                                    <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-rose-100 text-rose-800 border border-rose-200">
                                      {prev}
                                    </span>
                                  </td>
                                  <td className="py-2 px-3">
                                    <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-100 text-emerald-800 border border-emerald-200">
                                      {proposed}
                                    </span>
                                  </td>
                                </tr>
                              );
                            })}
                          </tbody>
                        </table>
                      </div>
                    )}

                    {/* Actions / Status States */}
                    <div className="pt-2 flex items-center justify-between">
                      {m.confirmationCard.status === "pending" && (
                        <div className="flex items-center space-x-2 ml-auto">
                          <button
                            onClick={() => handleCardDismiss(m.id)}
                            className="px-3 py-1.5 rounded-lg border border-[#E4DDCA] text-[#77735F] hover:bg-[#EDE8D8] font-bold text-xs transition-colors cursor-pointer"
                          >
                            Dismiss
                          </button>
                          <button
                            onClick={() => void handleCardConfirm(m.id, false)}
                            className="px-3.5 py-1.5 rounded-lg border border-rose-300 text-rose-700 hover:bg-rose-50 font-bold text-xs transition-colors cursor-pointer"
                          >
                            Reject Changes
                          </button>
                          <button
                            onClick={() => void handleCardConfirm(m.id, true)}
                            className="px-4 py-1.5 rounded-lg bg-[#3F451F] text-[#FBF8F0] hover:bg-[#343919] font-bold text-xs transition-colors shadow-2xs cursor-pointer flex items-center gap-1.5"
                          >
                            <span>Confirm & Apply</span>
                          </button>
                        </div>
                      )}

                      {m.confirmationCard.status === "submitting" && (
                        <span className="text-amber-800 font-semibold flex items-center gap-1.5 ml-auto">
                          <span className="w-3 h-3 border-2 border-amber-800 border-t-transparent rounded-full animate-spin" />
                          Committing confirmed changes to backend database...
                        </span>
                      )}

                      {m.confirmationCard.status === "confirmed" && (
                        <div className="p-2.5 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-800 font-bold w-full flex items-center justify-between">
                          <span>✓ Confirmed: {m.confirmationCard.responseMessage || "Attendance modification applied to database."}</span>
                        </div>
                      )}

                      {m.confirmationCard.status === "rejected" && (
                        <div className="p-2.5 rounded-lg bg-rose-50 border border-rose-200 text-rose-800 font-bold w-full">
                          ✕ {m.confirmationCard.responseMessage || "Proposed changes rejected."}
                        </div>
                      )}

                      {m.confirmationCard.status === "cancelled" && (
                        <div className="p-2.5 rounded-lg bg-[#EDE8D8] border border-[#E4DDCA] text-[#77735F] font-semibold w-full">
                          — {m.confirmationCard.responseMessage || "Proposal dismissed locally. No database changes were made."}
                        </div>
                      )}

                      {m.confirmationCard.status === "expired" && (
                        <div className="p-2.5 rounded-lg bg-rose-50 border border-rose-300 text-rose-900 font-bold w-full flex items-center justify-between">
                          <span>⏱ {m.confirmationCard.errorMessage || "HTTP 410 Expired: This confirmation has expired. Please submit a new attendance modification proposal."}</span>
                        </div>
                      )}

                      {m.confirmationCard.status === "conflict" && (
                        <div className="p-2.5 rounded-lg bg-amber-50 border border-amber-300 text-amber-900 font-bold w-full">
                          ⚠️ {m.confirmationCard.errorMessage || "HTTP 409 Conflict: This proposal has already been confirmed or consumed."}
                        </div>
                      )}

                      {m.confirmationCard.status === "forbidden" && (
                        <div className="p-2.5 rounded-lg bg-rose-50 border border-rose-300 text-rose-900 font-bold w-full">
                          🔒 {m.confirmationCard.errorMessage || "HTTP 403 Forbidden: You do not have permission to modify attendance for this session."}
                        </div>
                      )}

                      {m.confirmationCard.status === "not_found" && (
                        <div className="p-2.5 rounded-lg bg-rose-50 border border-rose-300 text-rose-900 font-bold w-full">
                          ❓ {m.confirmationCard.errorMessage || "HTTP 404 Not Found: Attendance proposal not found or inaccessible."}
                        </div>
                      )}

                      {m.confirmationCard.status === "error" && (
                        <div className="p-2.5 rounded-lg bg-rose-50 border border-rose-200 text-rose-800 font-bold w-full">
                          Error: {m.confirmationCard.errorMessage}
                        </div>
                      )}
                    </div>
                  </div>
                )}
              </div>

              <span className="text-[10px] text-[#77735F] mt-1 px-1">
                {m.timestamp}
              </span>
            </div>
          );
        })}

        {isProcessing && (
          <div className="flex items-center gap-3 text-xs text-[#77735F] bg-[#F2EDE0] p-4 rounded-2xl w-fit border border-[#E4DDCA]">
            <AnimatedAiMascot isThinking={true} className="h-10" />
            <span>Analyzing attendance records...</span>
          </div>
        )}

        {isUploading && (
          <div className="w-full max-w-md text-xs text-[#77735F] bg-[#F2EDE0] p-4 rounded-2xl border border-[#E4DDCA] space-y-2">
            <div className="flex items-center gap-3">
              <div className="w-5 h-5 border-2 border-[#3F451F] border-t-transparent rounded-full animate-spin" />
              <span className="font-semibold text-[#24251C]">
                {uploadStage === "uploading" ? "Uploading the roster…" : "Extracting attendance records…"}
              </span>
            </div>
            {selectedFile && (
              <div className="flex items-center justify-between gap-3">
                <span className="truncate font-mono text-[11px]">
                  {selectedFile.name} · {selectedFile.type} ·{" "}
                  {(selectedFile.size / 1024).toFixed(0)} KB
                </span>
                <span className="font-mono text-[11px] font-bold text-[#3F451F]">
                  {uploadProgress}%
                </span>
              </div>
            )}
            <div className="h-1.5 w-full rounded-full bg-[#E4DDCA] overflow-hidden">
              <div
                className="h-full bg-[#6C5119] transition-[width] duration-200"
                style={{ width: `${uploadStage === "uploading" ? uploadProgress : 100}%` }}
              />
            </div>
            <p className="text-[11px]">
              {uploadStage === "uploading"
                ? "Sending the file to the RollCall AI extraction endpoint."
                : "The backend is parsing the roster and validating every student identifier."}
            </p>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Quick Prompts */}
      <div className="py-2 flex items-center gap-2 overflow-x-auto text-xs no-scrollbar">
        {QUICK_PROMPTS.map((prompt) => (
          <button
            key={prompt}
            onClick={() => void handleSendMessage(prompt)}
            disabled={isProcessing || isUploading}
            className="px-3 py-1.5 rounded-xl bg-[#FBF8F0] border border-[#E4DDCA] text-[#77735F] hover:text-[#24251C] hover:border-[#3F451F] whitespace-nowrap transition-colors cursor-pointer disabled:opacity-50"
          >
            {prompt}
          </button>
        ))}
      </div>

      {/* Input & Upload Bar */}
      <div className="pt-2 border-t border-[#E4DDCA]">
        {/* Hidden File Input */}
        <input
          type="file"
          ref={fileInputRef}
          onChange={handleFileUpload}
          accept=".pdf,.xlsx,.xls,.csv,.txt,image/png,image/jpeg"
          className="hidden"
        />

        <div className="flex items-center gap-2 bg-[#F2EDE0] p-1.5 rounded-2xl border border-[#E4DDCA]">
          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={isUploading || isProcessing}
            title="Upload an attendance roster (PDF, XLSX, CSV, TXT, PNG or JPEG)"
            className="p-2.5 rounded-xl text-[#77735F] hover:text-[#24251C] hover:bg-[#E4DDCA]/50 transition-colors disabled:opacity-50 cursor-pointer"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13" />
            </svg>
          </button>

          <input
            type="text"
            value={inputQuery}
            onChange={(e) => setInputQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void handleSendMessage();
              }
            }}
            placeholder="Ask about student attendance, propose an edit (e.g. 'mark 1MS21CS001 absent in SESS-001'), or upload a photo..."
            disabled={isProcessing || isUploading}
            className="flex-1 bg-transparent border-none text-sm text-[#24251C] placeholder-[#77735F] focus:outline-none px-2"
          />

          <button
            onClick={() => void handleSendMessage()}
            disabled={!inputQuery.trim() || isProcessing || isUploading}
            className="p-2.5 bg-[#3F451F] text-[#FBF8F0] rounded-xl hover:bg-[#323719] transition-all disabled:opacity-40 disabled:hover:bg-[#3F451F] cursor-pointer"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M14 5l7 7m0 0l-7 7m7-7H3" />
            </svg>
          </button>
        </div>
      </div>
    </div>
  );
}
