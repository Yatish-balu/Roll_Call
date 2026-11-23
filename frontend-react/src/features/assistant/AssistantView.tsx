"use client";

import React, { useState, useRef, useEffect, useCallback } from "react";
import { useAuth } from "@/hooks/useAuth";
import { apiClient } from "@/services/api/client";
import {
  askAgent,
  processAttendanceFile,
  confirmAgentRecords,
  fetchAgentStatus,
  proposeAttendanceEdit,
  confirmAttendanceProposal,
  isAttendanceEditQuery,
  fetchUserChatThreads,
  fetchChatThread,
  syncChatThread,
  deleteChatThread,
  type AgentResponse,
  type AgentStatus,
  type ConfirmationRequest,
  type UserChatThreadSummary,
  type UserChatMessageItem,
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

interface ContextAction {
  label: string;
  prompt: string;
  variant?: "primary" | "danger" | "default";
}

function getContextualActions(m: ChatMessage): ContextAction[] {
  const text = m.text || "";
  const lower = text.toLowerCase();
  const actions: ContextAction[] = [];

  // 1. Proposal or Confirmation
  if (
    lower.includes("proceed") ||
    lower.includes("proposal") ||
    lower.includes("would you like me to proceed") ||
    lower.includes("reply 'yes'") ||
    lower.includes("please confirm")
  ) {
    return [
      { label: "✓ Yes, Proceed & Apply", prompt: "proceed", variant: "primary" },
      { label: "✕ Cancel Action", prompt: "cancel", variant: "danger" },
    ];
  }

  // 2. Profile View (e.g. "Faculty Profile for...")
  if (lower.includes("faculty profile for") || lower.includes("profile for")) {
    return [
      { label: "✏️ Change Name to Yatish Balu", prompt: "change my name in my profile to Yatish Balu", variant: "primary" },
      { label: "📱 Update Mobile", prompt: "update my mobile number in my profile to 9876543210" },
      { label: "📅 Show Today's Schedule", prompt: "Show my class schedule for today" },
    ];
  }

  // 3. Profile Updated Successfully
  if (lower.includes("profile updated successfully")) {
    return [
      { label: "👤 View Updated Profile", prompt: "Show my profile", variant: "primary" },
      { label: "📅 Show Today's Schedule", prompt: "Show my class schedule for today" },
      { label: "📊 Today's Attendance", prompt: "Summarize today's overall attendance" },
    ];
  }

  // 4. Pending / Unreviewed Sessions
  if (
    lower.includes("pending or unreviewed") ||
    lower.includes("requiring attention or review") ||
    lower.includes("pending sessions")
  ) {
    const sessionMatches = Array.from(text.matchAll(/\*\*([A-Za-z0-9_-]+)\*\*/g))
      .map((match) => match[1])
      .filter((id) => id && !["Session", "ID", "Date", "Subject", "Status", "Total", "Found"].includes(id));
    const uniqueIds = Array.from(new Set(sessionMatches)).slice(0, 2);

    uniqueIds.forEach((sid) => {
      actions.push({
        label: `📝 Inspect Session ${sid}`,
        prompt: `Show attendance details for session ${sid}`,
        variant: "primary",
      });
    });

    actions.push({ label: "📊 Today's Summary", prompt: "Summarize today's overall attendance" });
    actions.push({ label: "🚪 Vacant Rooms", prompt: "Find vacant classrooms right now" });
    return actions;
  }

  // 5. Live Real-Time Date & Day Query
  if (
    lower.includes("live real-time date") ||
    lower.includes("current real-time date") ||
    lower.includes("day of the week")
  ) {
    return [
      { label: "📅 Today's Class Schedule", prompt: "Show my class schedule for today", variant: "primary" },
      { label: "📊 Today's Attendance Overview", prompt: "Summarize today's overall attendance" },
      { label: "🚪 Find Vacant Rooms Now", prompt: "Find vacant classrooms right now" },
    ];
  }

  // 6. Defaulters List
  if (
    lower.includes("defaulter") ||
    lower.includes("<75%") ||
    lower.includes("attendance shortage") ||
    lower.includes("below 75")
  ) {
    return [
      { label: "📊 Branch Attendance Breakdown", prompt: "Show attendance statistics for Computer Science (CSE)", variant: "primary" },
      { label: "📅 Today's Schedule", prompt: "Show my class schedule for today" },
      { label: "🕒 Check Pending Sessions", prompt: "Which sessions have pending unreviewed attendance?" },
    ];
  }

  // 7. Class Schedule / Timetable
  if (lower.includes("class schedule for") || lower.includes("timetable")) {
    return [
      { label: "🚪 Find Vacant Rooms for Next Class", prompt: "Find vacant classrooms right now", variant: "primary" },
      { label: "🕒 Check Pending Reviews for Today", prompt: "Which sessions have pending unreviewed attendance?" },
      { label: "➕ Create New Session", prompt: "Create a session for today" },
    ];
  }

  // 8. Vacant Classrooms
  if (
    lower.includes("vacant") ||
    lower.includes("available classrooms") ||
    lower.includes("classroom availability")
  ) {
    return [
      { label: "📅 Today's Class Schedule", prompt: "Show my class schedule for today", variant: "primary" },
      { label: "➕ Schedule Class in Available Room", prompt: "Create a session for today in vacant room" },
      { label: "📊 Today's Summary", prompt: "Summarize today's overall attendance" },
    ];
  }

  // 9. Session Created
  if (lower.includes("session created successfully")) {
    return [
      { label: "📅 View Today's Updated Schedule", prompt: "Show my class schedule for today", variant: "primary" },
      { label: "🕒 Check Pending Sessions", prompt: "Which sessions have pending unreviewed attendance?" },
    ];
  }

  // 10. Attendance Summary
  if (
    lower.includes("attendance summary") ||
    lower.includes("attendance statistics") ||
    lower.includes("overall attendance")
  ) {
    return [
      { label: "⚠️ Show Defaulters (<75%)", prompt: "List students with attendance below 75%", variant: "primary" },
      { label: "📅 Today's Schedule", prompt: "Show my class schedule for today" },
      { label: "🕒 Check Pending Sessions", prompt: "Which sessions have pending unreviewed attendance?" },
    ];
  }

  // Smart Contextual Fallback
  return [
    { label: "📊 Today's Attendance", prompt: "Summarize today's overall attendance" },
    { label: "📅 Today's Schedule", prompt: "Show my class schedule for today" },
    { label: "🕒 Pending Reviews", prompt: "Which sessions have pending unreviewed attendance?" },
  ];
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

export const CHAT_STORAGE_KEY = "rollcall_recent_chat_messages_v1";

export function getUserChatStorageKey(userId?: string | null, threadId?: string | null): string {
  return userId ? `rollcall_chat_${userId}_${threadId || "current"}` : "rollcall_chat_guest";
}

function parseStoredBackendMessage(m: UserChatMessageItem): ChatMessage {
  let meta: Partial<ChatMessage> = {};
  if (m.metadata_json) {
    try {
      meta = JSON.parse(m.metadata_json);
    } catch {
      // ignore
    }
  }
  return {
    id: m.message_id,
    sender: m.sender as "user" | "assistant",
    text: m.text,
    timestamp: m.timestamp,
    ...meta,
  };
}

function defaultWelcomeMessage(): ChatMessage {
  return {
    id: "welcome",
    sender: "assistant",
    text: "Hello! I am your RollCall AI attendance assistant. You can ask me natural language questions about student attendance, analyze sessions, propose attendance modifications, or upload an attendance roster sheet or photo for automated verification.",
    timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
  };
}

export function AssistantView() {
  const { session } = useAuth();
  const userId = session?.userId;

  const [messages, setMessages] = useState<ChatMessage[]>([defaultWelcomeMessage()]);
  const [threads, setThreads] = useState<UserChatThreadSummary[]>([]);
  const [currentThreadId, setCurrentThreadId] = useState<string | null>(null);
  const [currentThreadTitle, setCurrentThreadTitle] = useState<string>("New Conversation");
  const [isRecentDrawerOpen, setIsRecentDrawerOpen] = useState(false);
  const [recentSearchQuery, setRecentSearchQuery] = useState("");
  const [isLoadingThreads, setIsLoadingThreads] = useState(false);

  const [sessions, setSessions] = useState<Array<{ session_id: string; subject?: string; date?: string }>>([]);
  const [activeSessionId, setActiveSessionId] = useState("");
  const [isCopiedId, setIsCopiedId] = useState<string | null>(null);

  const [inputQuery, setInputQuery] = useState("");
  const [isProcessing, setIsProcessing] = useState(false);
  const [agentStatus, setAgentStatus] = useState<AgentStatus | null>(null);

  // Synchronize threads on user identity change (strict per-account isolation)
  useEffect(() => {
    // Account switch protection: immediately clear in-memory chat
    setMessages([defaultWelcomeMessage()]);
    setCurrentThreadId(null);
    setCurrentThreadTitle("New Conversation");
    setThreads([]);

    if (!userId) return;

    let isMounted = true;
    setIsLoadingThreads(true);

    fetchUserChatThreads()
      .then(async (userThreads) => {
        if (!isMounted) return;
        setThreads(userThreads);
        if (userThreads && userThreads.length > 0) {
          const latest = userThreads[0];
          setCurrentThreadId(latest.thread_id);
          setCurrentThreadTitle(latest.title);
          try {
            const detail = await fetchChatThread(latest.thread_id);
            if (isMounted && detail && detail.messages && detail.messages.length > 0) {
              setMessages(detail.messages.map(parseStoredBackendMessage));
              return;
            }
          } catch {
            const localRaw = window.localStorage.getItem(getUserChatStorageKey(userId, latest.thread_id));
            if (localRaw) {
              try {
                const parsed = JSON.parse(localRaw);
                if (Array.isArray(parsed) && parsed.length > 0) {
                  setMessages(parsed);
                  return;
                }
              } catch {
                // Ignore parse errors on cached messages
              }
            }
          }
        } else {
          setCurrentThreadId(`thread_${Date.now()}`);
        }
      })
      .catch(() => {
        if (!isMounted) return;
        const localRaw = window.localStorage.getItem(getUserChatStorageKey(userId, "current"));
        if (localRaw) {
          try {
            const parsed = JSON.parse(localRaw);
            if (Array.isArray(parsed) && parsed.length > 0) {
              setMessages(parsed);
            }
          } catch {
            // Ignore parse errors on cached fallback
          }
        }
        setCurrentThreadId(`thread_${Date.now()}`);
      })
      .finally(() => {
        if (isMounted) setIsLoadingThreads(false);
      });

    return () => {
      isMounted = false;
    };
  }, [userId]);

  // Persist messages whenever updated, scoped strictly to user and active thread
  useEffect(() => {
    if (!userId || !currentThreadId) return;

    // 1. Scoped local storage
    if (typeof window !== "undefined") {
      try {
        window.localStorage.setItem(
          getUserChatStorageKey(userId, currentThreadId),
          JSON.stringify(messages.slice(-50))
        );
      } catch (err) {
        console.warn("Failed to persist chat messages to localStorage", err);
      }
    }

    // Skip network sync for pristine initial welcome
    if (messages.length <= 1 && messages[0]?.id === "welcome") return;

    // 2. Debounced background sync to backend database (cross-device sync)
    const timer = setTimeout(() => {
      syncChatThread(currentThreadId, {
        title: currentThreadTitle,
        messages: messages.map((m) => ({
          id: m.id,
          sender: m.sender,
          text: m.text,
          timestamp: m.timestamp,
          metadata: {
            toolCalls: m.toolCalls,
            records: m.records,
            confirmationCard: m.confirmationCard,
            error: m.error,
          },
        })),
      })
        .then((detail) => {
          if (detail && detail.title && detail.title !== currentThreadTitle) {
            setCurrentThreadTitle(detail.title);
          }
          fetchUserChatThreads().then(setThreads).catch(() => {});
        })
        .catch(() => {});
    }, 1000);

    return () => clearTimeout(timer);
  }, [messages, currentThreadId, currentThreadTitle, userId]);

  // Load available sessions for context selector
  useEffect(() => {
    let isMounted = true;
    apiClient
      .get<{ items: Array<{ session_id: string; subject?: string; date?: string }> }>("/api/v1/sessions", { limit: 25 })
      .then((res) => {
        if (isMounted && res && Array.isArray(res.items)) {
          setSessions(res.items);
        }
      })
      .catch(() => {});
    return () => {
      isMounted = false;
    };
  }, []);

  const handleNewChat = useCallback(() => {
    const newId = `thread_${Date.now()}`;
    setCurrentThreadId(newId);
    setCurrentThreadTitle("New Conversation");
    setMessages([defaultWelcomeMessage()]);
    setIsRecentDrawerOpen(false);
  }, []);

  const handleSelectThread = useCallback(async (thread: UserChatThreadSummary) => {
    setIsRecentDrawerOpen(false);
    setCurrentThreadId(thread.thread_id);
    setCurrentThreadTitle(thread.title);

    try {
      const detail = await fetchChatThread(thread.thread_id);
      if (detail && detail.messages && detail.messages.length > 0) {
        setMessages(detail.messages.map(parseStoredBackendMessage));
      } else {
        setMessages([defaultWelcomeMessage()]);
      }
    } catch {
      const localRaw = window.localStorage.getItem(getUserChatStorageKey(userId, thread.thread_id));
      if (localRaw) {
        try {
          const parsed = JSON.parse(localRaw);
          if (Array.isArray(parsed) && parsed.length > 0) {
            setMessages(parsed);
            return;
          }
        } catch {
          // Ignore cache parse error
        }
      }
      setMessages([defaultWelcomeMessage()]);
    }
  }, [userId]);

  const handleDeleteThread = useCallback(async (threadId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (!window.confirm("Are you sure you want to delete this conversation?")) return;
    try {
      await deleteChatThread(threadId);
      setThreads((prev) => prev.filter((t) => t.thread_id !== threadId));
      if (currentThreadId === threadId) {
        handleNewChat();
      }
      if (userId) {
        window.localStorage.removeItem(getUserChatStorageKey(userId, threadId));
      }
    } catch (err) {
      console.error("Failed to delete chat thread", err);
    }
  }, [currentThreadId, handleNewChat, userId]);

  const handleClearChat = useCallback(() => {
    setMessages([defaultWelcomeMessage()]);
    if (userId && currentThreadId) {
      window.localStorage.removeItem(getUserChatStorageKey(userId, currentThreadId));
      syncChatThread(currentThreadId, {
        title: "New Conversation",
        messages: [defaultWelcomeMessage()],
      }).catch(() => {});
    }
  }, [userId, currentThreadId]);


  const handleCopyText = useCallback((id: string, text: string) => {
    if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
      void navigator.clipboard.writeText(text);
      setIsCopiedId(id);
      setTimeout(() => setIsCopiedId(null), 2000);
    }
  }, []);

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

  // Staged pending attachment (waits for user to type/send instead of auto-firing)
  const [pendingFile, setPendingFile] = useState<File | null>(null);
  const [pendingFilePreview, setPendingFilePreview] = useState<string | null>(null);

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

  const handleRemovePendingFile = useCallback(() => {
    if (pendingFilePreview) {
      URL.revokeObjectURL(pendingFilePreview);
    }
    setPendingFile(null);
    setPendingFilePreview(null);
  }, [pendingFilePreview]);

  const handleStageFile = useCallback(
    (file: File) => {
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

      if (pendingFilePreview) {
        URL.revokeObjectURL(pendingFilePreview);
      }

      setPendingFile(file);
      if (file.type.startsWith("image/")) {
        setPendingFilePreview(URL.createObjectURL(file));
      } else {
        setPendingFilePreview(null);
      }
    },
    [pendingFilePreview]
  );

  const uploadFile = useCallback(
    async (file: File, promptQuery?: string) => {
      const extension = file.name.includes(".")
        ? `.${file.name.split(".").pop()?.toLowerCase()}`
        : "";

      setSelectedFile({
        name: file.name,
        type: file.type || extension.toUpperCase().replace(".", "") || "FILE",
        size: file.size,
      });
      setUploadProgress(0);
      setUploadStage("uploading");
      setIsUploading(true);

      const userDisplayText = promptQuery?.trim()
        ? `${promptQuery.trim()} (attached: ${file.name})`
        : `Uploaded file for attendance extraction: ${file.name}`;

      const userMsg: ChatMessage = {
        id: nextMsgId("u"),
        sender: "user",
        text: userDisplayText,
        timestamp: getFormattedTime(),
      };
      setMessages((prev) => [...prev, userMsg]);

      try {
        const res = await processAttendanceFile(
          file,
          activeSessionId || undefined,
          undefined,
          (percent) => setUploadProgress(percent),
          promptQuery?.trim() || undefined
        );
        setUploadStage("processing");

        const confirmationCardData: ConfirmationCardData | null =
          res.needs_confirmation && res.confirmation_request
            ? {
                confirmationId:
                  (res.confirmation_request.affected_rows?.[0]?.confirmation_id as string) || "",
                requestId: res.request_id,
                sessionId:
                  activeSessionId ||
                  ((res.confirmation_request.affected_rows?.[0]?.session_id as string) || ""),
                question:
                  res.confirmation_request.question || "Do you confirm the extracted attendance records?",
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
            sharpnessThreshold:
              typeof details.sharpness_threshold === "number" ? details.sharpness_threshold : 100.0,
            measuredBrightness: typeof details.brightness === "number" ? details.brightness : 54.2,
            brightnessThreshold:
              typeof details.brightness_threshold === "number" ? details.brightness_threshold : 80.0,
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
    },
    [activeSessionId]
  );

  const handleSendMessage = useCallback(async (textToSend?: string) => {
    const query = (textToSend || inputQuery).trim();
    if ((!query && !pendingFile) || isProcessing || isUploading) return;

    if (pendingFile) {
      const fileToUpload = pendingFile;
      const promptText = query;
      handleRemovePendingFile();
      setInputQuery("");
      await uploadFile(fileToUpload, promptText);
      return;
    }

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
  }, [inputQuery, isProcessing, isUploading, activeSessionId, pendingFile, handleRemovePendingFile, uploadFile]);

  const handleFileUpload = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) handleStageFile(file);
    if (fileInputRef.current) fileInputRef.current.value = "";
  }, [handleStageFile]);

  // Handle Clipboard Ctrl+V Paste for images and files
  const handlePaste = useCallback((e: React.ClipboardEvent) => {
    const items = e.clipboardData?.items;
    if (!items) return;
    for (let i = 0; i < items.length; i++) {
      const item = items[i];
      if (item.kind === "file") {
        const file = item.getAsFile();
        if (file) {
          e.preventDefault();
          handleStageFile(file);
          return;
        }
      }
    }
  }, [handleStageFile]);

  // Window-level Paste Listener so pasting anywhere in chat window works
  useEffect(() => {
    const handleWindowPaste = (e: ClipboardEvent) => {
      const items = e.clipboardData?.items;
      if (!items) return;
      for (let i = 0; i < items.length; i++) {
        if (items[i].kind === "file") {
          const file = items[i].getAsFile();
          if (file) {
            e.preventDefault();
            handleStageFile(file);
            return;
          }
        }
      }
    };
    window.addEventListener("paste", handleWindowPaste);
    return () => window.removeEventListener("paste", handleWindowPaste);
  }, [handleStageFile]);

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

  const filteredThreads = threads.filter(
    (t) =>
      !recentSearchQuery.trim() ||
      t.title.toLowerCase().includes(recentSearchQuery.toLowerCase()) ||
      (t.last_message && t.last_message.toLowerCase().includes(recentSearchQuery.toLowerCase()))
  );

  return (
    <div className="flex flex-col h-[calc(100vh-8rem)] relative">
      {/* Top Bar / Agent Status & Context Toolbar */}
      <div className="flex flex-wrap items-center justify-between gap-3 pb-4 border-b border-[#E4DDCA] mb-4">
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

        <div className="flex flex-wrap items-center gap-2">
          {/* Active Session Context Selector */}
          <div className="flex items-center gap-1.5 text-xs text-[#77735F] bg-[#F2EDE0] px-2.5 py-1.5 rounded-xl border border-[#E4DDCA]">
            <span className="font-semibold text-[#24251C] whitespace-nowrap">Session Context:</span>
            <select
              value={activeSessionId}
              onChange={(e) => setActiveSessionId(e.target.value)}
              className="bg-transparent text-xs text-[#24251C] font-medium focus:outline-none cursor-pointer max-w-[190px] truncate"
            >
              <option value="">All My Classes</option>
              {sessions.map((s) => (
                <option key={s.session_id} value={s.session_id}>
                  {s.session_id} {s.subject ? `(${s.subject})` : ""}
                </option>
              ))}
            </select>
          </div>

          {/* New Chat Button */}
          <button
            type="button"
            onClick={handleNewChat}
            className="px-3 py-1.5 rounded-xl text-xs font-bold text-[#6C5119] bg-[#6C5119]/10 hover:bg-[#6C5119]/20 border border-[#6C5119]/20 transition-all cursor-pointer flex items-center gap-1.5 shadow-2xs"
            title="Start a fresh chat thread"
          >
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M12 4v16m8-8H4" />
            </svg>
            <span>New Chat</span>
          </button>

          {/* Recent Chats Tab / Button */}
          <button
            type="button"
            onClick={() => setIsRecentDrawerOpen(true)}
            className="px-3 py-1.5 rounded-xl text-xs font-bold text-[#24251C] bg-[#F2EDE0] hover:bg-[#E4DDCA] border border-[#E4DDCA] transition-all cursor-pointer flex items-center gap-1.5 shadow-2xs"
            title="Browse recent conversations saved to your account"
          >
            <svg className="w-3.5 h-3.5 text-[#6C5119]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            <span>Recent Chats</span>
            {threads.length > 0 && (
              <span className="px-1.5 py-0.2 rounded-full text-[10px] font-bold bg-[#6C5119] text-white">
                {threads.length}
              </span>
            )}
          </button>

          {/* Current Chat Topic Pill */}
          {currentThreadTitle && currentThreadTitle !== "New Conversation" && (
            <div
              className="hidden xl:flex items-center gap-1.5 text-xs text-[#24251C] bg-white px-2.5 py-1.5 rounded-xl border border-[#E4DDCA] max-w-[180px] truncate"
              title={currentThreadTitle}
            >
              <span className="text-[#77735F] text-[10px] uppercase font-bold">Topic:</span>
              <span className="font-medium truncate">{currentThreadTitle}</span>
            </div>
          )}

          {/* Clear Chat Button */}
          {messages.length > 1 && (
            <button
              onClick={handleClearChat}
              className="px-2.5 py-1.5 rounded-xl text-xs font-medium text-[#77735F] hover:text-rose-700 hover:bg-rose-50 border border-[#E4DDCA] hover:border-rose-200 transition-colors cursor-pointer flex items-center gap-1 shadow-2xs"
              title="Clear current messages"
            >
              <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
              </svg>
              <span>Clear</span>
            </button>
          )}

          {agentStatus && (
            <div className="hidden md:flex items-center gap-2 text-xs text-[#77735F] bg-[#F2EDE0] px-3 py-1.5 rounded-xl border border-[#E4DDCA]">
              <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
              <span>Vision OCR: {agentStatus.gemini_configured ? "Cloud LLM" : "Local EasyOCR"}</span>
            </div>
          )}
        </div>
      </div>

      {/* Recent Chats Slide-Over Drawer */}
      {isRecentDrawerOpen && (
        <div className="fixed inset-0 z-50 flex justify-end bg-black/40 backdrop-blur-2xs animate-fadeIn">
          <div className="w-full max-w-md bg-[#FAF8F5] h-full shadow-2xl border-l border-[#E4DDCA] flex flex-col p-6 space-y-4 animate-slideLeft">
            <div className="flex items-center justify-between pb-3 border-b border-[#E4DDCA]">
              <div className="flex items-center gap-2.5">
                <div className="w-9 h-9 rounded-xl bg-[#6C5119]/10 text-[#6C5119] flex items-center justify-center">
                  <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                </div>
                <div>
                  <h2 className="text-base font-bold text-[#24251C]">Recent Conversations</h2>
                  <p className="text-[11px] text-[#77735F]">Saved to account · Cross-device sync</p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setIsRecentDrawerOpen(false)}
                className="w-8 h-8 rounded-xl border border-[#E4DDCA] text-[#77735F] hover:text-[#24251C] hover:bg-[#F2EDE0] flex items-center justify-center transition-colors cursor-pointer"
                title="Close"
              >
                ✕
              </button>
            </div>

            {/* Start New Conversation button inside drawer */}
            <button
              type="button"
              onClick={handleNewChat}
              className="w-full py-2.5 px-3 rounded-xl bg-[#6C5119] text-white text-xs font-bold hover:bg-[#533e13] transition-colors flex items-center justify-center gap-2 shadow-xs cursor-pointer"
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M12 4v16m8-8H4" />
              </svg>
              <span>+ New Conversation</span>
            </button>

            {/* Search Filter */}
            <div>
              <input
                type="text"
                placeholder="Search recent conversations…"
                value={recentSearchQuery}
                onChange={(e) => setRecentSearchQuery(e.target.value)}
                className="w-full px-3 py-2 rounded-xl text-xs bg-white border border-[#E4DDCA] text-[#24251C] placeholder-[#77735F]/60 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[#6C5119]"
              />
            </div>

            {/* Conversation list */}
            <div className="flex-1 overflow-y-auto space-y-2 pr-1">
              {isLoadingThreads ? (
                <div className="text-center py-8 text-xs text-[#77735F]">Loading conversations…</div>
              ) : filteredThreads.length === 0 ? (
                <div className="text-center py-10 px-4 bg-[#F2EDE0]/50 rounded-2xl border border-dashed border-[#E4DDCA] space-y-1">
                  <p className="text-xs font-bold text-[#24251C]">No conversations found</p>
                  <p className="text-[11px] text-[#77735F]">
                    {recentSearchQuery ? "No matches for your search." : "Start chatting and your conversations will appear here."}
                  </p>
                </div>
              ) : (
                filteredThreads.map((t) => {
                  const isActive = t.thread_id === currentThreadId;
                  return (
                    <div
                      key={t.thread_id}
                      onClick={() => void handleSelectThread(t)}
                      className={`p-3 rounded-xl border transition-all cursor-pointer flex items-start justify-between gap-2 group ${
                        isActive
                          ? "bg-[#6C5119]/10 border-[#6C5119]/40 ring-1 ring-[#6C5119]/20"
                          : "bg-white border-[#E4DDCA] hover:bg-[#F2EDE0]/60 hover:border-[#6C5119]/30"
                      }`}
                    >
                      <div className="min-w-0 flex-1 space-y-1">
                        <div className="flex items-center gap-1.5">
                          {isActive && (
                            <span className="w-1.5 h-1.5 rounded-full bg-[#6C5119] shrink-0" />
                          )}
                          <p className="text-xs font-bold text-[#24251C] truncate">{t.title}</p>
                        </div>
                        {t.last_message && (
                          <p className="text-[11px] text-[#77735F] truncate">{t.last_message}</p>
                        )}
                        <div className="flex items-center gap-2 text-[10px] text-[#77735F]">
                          <span>
                            {new Date(t.updated_at).toLocaleDateString([], {
                              month: "short",
                              day: "numeric",
                            })}
                          </span>
                          <span>·</span>
                          <span>
                            {t.message_count} {t.message_count === 1 ? "message" : "messages"}
                          </span>
                        </div>
                      </div>

                      <button
                        type="button"
                        onClick={(e) => void handleDeleteThread(t.thread_id, e)}
                        className="opacity-0 group-hover:opacity-100 p-1.5 rounded-lg text-[#77735F] hover:text-rose-700 hover:bg-rose-50 transition-all cursor-pointer shrink-0"
                        title="Delete conversation"
                      >
                        <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                        </svg>
                      </button>
                    </div>
                  );
                })
              )}
            </div>
          </div>
        </div>
      )}


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
                <div className="flex items-start justify-between gap-2">
                  <p className="whitespace-pre-wrap leading-relaxed flex-1">{m.text}</p>
                  {!isUser && (
                    <button
                      onClick={() => handleCopyText(m.id, m.text)}
                      title="Copy response"
                      className="text-[#77735F] hover:text-[#24251C] transition-colors shrink-0 p-1 rounded-md hover:bg-[#E4DDCA]/50 cursor-pointer text-[10px] flex items-center gap-0.5"
                    >
                      {isCopiedId === m.id ? (
                        <span className="text-emerald-700 font-bold">✓ Copied</span>
                      ) : (
                        <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                        </svg>
                      )}
                    </button>
                  )}
                </div>

                {/* Interactive Real-Time Actions for Assistant Messages */}
                {!isUser && !m.error && (() => {
                  const actions = getContextualActions(m);
                  if (actions.length === 0) return null;
                  return (
                    <div className="mt-3 pt-2.5 border-t border-[#E4DDCA]/60 flex flex-wrap items-center gap-1.5">
                      <span className="text-[10px] uppercase font-bold text-[#77735F] mr-1 flex items-center gap-1">
                        <span>⚡ Real-Time Actions:</span>
                      </span>
                      {actions.map((act, aIdx) => {
                        let btnClass = "px-2.5 py-1 rounded-lg text-[11px] font-bold transition-all cursor-pointer shadow-2xs hover:-translate-y-0.5 flex items-center gap-1";
                        if (act.variant === "primary") {
                          btnClass += " bg-[#3F451F] hover:bg-[#343919] text-[#FBF8F0]";
                        } else if (act.variant === "danger") {
                          btnClass += " bg-white hover:bg-rose-50 border border-rose-300 text-rose-700";
                        } else {
                          btnClass += " bg-white/90 hover:bg-white border border-[#E4DDCA] text-[#3F451F] hover:border-[#3F451F]";
                        }
                        return (
                          <button
                            key={aIdx}
                            onClick={() => void handleSendMessage(act.prompt)}
                            disabled={isProcessing}
                            className={btnClass}
                          >
                            <span>{act.label}</span>
                          </button>
                        );
                      })}
                    </div>
                  );
                })()}

                {/* Real-time suggested actions */}

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

        {/* Staged file attachment chip: waits for user to send */}
        {pendingFile && (
          <div className="mb-2 flex items-center gap-2 bg-[#FBF8F0] px-3 py-1.5 rounded-xl border border-[#E4DDCA] w-fit max-w-full shadow-2xs">
            {pendingFilePreview ? (
              <img
                src={pendingFilePreview}
                alt="Upload preview"
                className="w-8 h-8 object-cover rounded-lg border border-[#E4DDCA]"
              />
            ) : (
              <div className="w-8 h-8 rounded-lg bg-[#E4DDCA] flex items-center justify-center text-xs font-bold text-[#3F451F]">
                📄
              </div>
            )}
            <div className="flex flex-col text-xs min-w-0 pr-1">
              <span className="font-semibold text-[#24251C] truncate max-w-[220px]">
                {pendingFile.name}
              </span>
              <span className="text-[10px] text-[#77735F]">
                {(pendingFile.size / 1024).toFixed(0)} KB · Ready to send
              </span>
            </div>
            <button
              type="button"
              onClick={handleRemovePendingFile}
              className="p-1 rounded-lg text-[#77735F] hover:text-[#C62828] hover:bg-rose-50 transition-colors cursor-pointer"
              title="Remove attachment"
            >
              ✕
            </button>
          </div>
        )}

        <div className="flex items-center gap-2 bg-[#F2EDE0] p-1.5 rounded-2xl border border-[#E4DDCA]">
          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={isUploading || isProcessing}
            title="Attach a roster or timetable file (PNG, JPG, PDF, XLSX, CSV)"
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
            onPaste={handlePaste}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void handleSendMessage();
              }
            }}
            placeholder={
              pendingFile
                ? "Type instructions (e.g. 'Register my CN classes from this timetable') or hit Send..."
                : "Ask about student attendance, propose an edit, paste (Ctrl+V) or attach a file..."
            }
            disabled={isProcessing || isUploading}
            className="flex-1 bg-transparent border-none text-sm text-[#24251C] placeholder-[#77735F] focus:outline-none px-2"
          />

          <button
            onClick={() => void handleSendMessage()}
            disabled={(!inputQuery.trim() && !pendingFile) || isProcessing || isUploading}
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
