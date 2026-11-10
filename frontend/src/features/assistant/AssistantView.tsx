"use client";

import React, { useState, useRef, useEffect, useCallback } from "react";
import {
  askAgent,
  processAttendanceFile,
  confirmAgentRecords,
  fetchAgentStatus,
  type AgentResponse,
  type AgentStatus,
  type ConfirmationRequest,
} from "@/services/api/agent";
import { AnimatedAiMascot } from "@/features/dashboard/components/AnimatedAiMascot";

interface ChatMessage {
  id: string;
  sender: "user" | "assistant";
  text: string;
  timestamp: string;
  toolCalls?: Array<Record<string, unknown>>;
  records?: Array<Record<string, unknown>>;
  confirmation?: ConfirmationRequest | null;
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

export function AssistantView() {
  const [messages, setMessages] = useState<ChatMessage[]>(() => [
    {
      id: "welcome",
      sender: "assistant",
      text: "Hello! I am your RollCall AI attendance assistant. You can ask me natural language questions about student attendance, analyze sessions, or upload an attendance roster sheet or photo for automated verification.",
      timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
    },
  ]);

  const [inputQuery, setInputQuery] = useState("");
  const [isProcessing, setIsProcessing] = useState(false);
  const [agentStatus, setAgentStatus] = useState<AgentStatus | null>(null);

  // File Upload
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [activeSessionId] = useState("");

  // Confirmation Modal
  const [pendingConfirmation, setPendingConfirmation] = useState<{
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
      const res: AgentResponse = await askAgent(query, activeSessionId || undefined);

      const assistantMsg: ChatMessage = {
        id: nextMsgId("a"),
        sender: "assistant",
        text: res.message || "I've analyzed the attendance database for your query.",
        timestamp: getFormattedTime(),
        toolCalls: res.tool_calls,
        confirmation: res.confirmation_request,
      };

      setMessages((prev) => [...prev, assistantMsg]);

      if (res.needs_confirmation && res.confirmation_request) {
        setPendingConfirmation({
          request: res.confirmation_request,
          requestId: res.request_id,
          sessionId: activeSessionId || "DIST_20261024",
        });
      }
    } catch (err: unknown) {
      const errorMessage =
        err instanceof Error ? err.message : "Unable to reach RollCall AI assistant.";
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

    setIsUploading(true);
    const userMsg: ChatMessage = {
      id: nextMsgId("u"),
      sender: "user",
      text: `Uploaded file for attendance extraction: ${file.name}`,
      timestamp: getFormattedTime(),
    };
    setMessages((prev) => [...prev, userMsg]);

    try {
      const res = await processAttendanceFile(file, activeSessionId || undefined);
      const assistantMsg: ChatMessage = {
        id: nextMsgId("a"),
        sender: "assistant",
        text: res.message || "Processed attendance sheet.",
        timestamp: getFormattedTime(),
        toolCalls: res.tool_calls,
        confirmation: res.confirmation_request,
      };
      setMessages((prev) => [...prev, assistantMsg]);

      if (res.needs_confirmation && res.confirmation_request) {
        setPendingConfirmation({
          request: res.confirmation_request,
          requestId: res.request_id,
          sessionId: activeSessionId || "DIST_20261024",
        });
      }
    } catch (err: unknown) {
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
    } finally {
      setIsUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }, [activeSessionId]);

  const handleConfirmDecision = useCallback(async (confirmed: boolean) => {
    if (!pendingConfirmation) return;
    setIsProcessing(true);

    try {
      const res = await confirmAgentRecords({
        session_id: pendingConfirmation.sessionId,
        confirmed,
        records: pendingConfirmation.request.affected_rows,
        request_id: pendingConfirmation.requestId,
      });

      setPendingConfirmation(null);
      setMessages((prev) => [
        ...prev,
        {
          id: nextMsgId("a"),
          sender: "assistant",
          text: confirmed
            ? `Successfully committed ${pendingConfirmation.request.affected_rows.length} records to session database.`
            : "Review rejected. Records discarded from staging.",
          timestamp: getFormattedTime(),
          toolCalls: res.tool_calls,
        },
      ]);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Confirmation failed.";
      setMessages((prev) => [
        ...prev,
        {
          id: nextMsgId("err"),
          sender: "assistant",
          text: `Confirmation failed: ${msg}`,
          timestamp: getFormattedTime(),
          error: true,
        },
      ]);
    } finally {
      setIsProcessing(false);
    }
  }, [pendingConfirmation]);

  return (
    <div className="flex flex-col h-[calc(100vh-8.5rem)] space-y-4">
      {/* Top Header Card with Mascot & Capabilities */}
      <div className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl p-4 shadow-sm flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div className="flex items-center gap-4">
          <div className="w-20 h-20 shrink-0">
            <AnimatedAiMascot isThinking={isProcessing || isUploading} className="h-20" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-xl font-bold text-[#24251C]">RollCall AI Assistant</h1>
              <span className="px-2 py-0.5 rounded-md text-[10px] font-bold bg-[#6C5119]/15 text-[#6C5119] border border-[#6C5119]/30 uppercase">
                Dual-Source Agent
              </span>
            </div>
            <p className="text-xs text-[#77735F] mt-0.5">
              Natural language queries backed strictly by verified database records & OCR sheet ingestion.
            </p>
          </div>
        </div>

        {/* Status Indicators */}
        <div className="flex items-center gap-2 self-start md:self-center text-xs">
          <div className="px-3 py-1.5 bg-[#F2EDE0] border border-[#E4DDCA] rounded-xl flex items-center gap-2">
            <span
              className={`w-2 h-2 rounded-full ${
                agentStatus?.status === "ready" ? "bg-emerald-500" : "bg-amber-500"
              }`}
            />
            <span className="text-[#24251C] font-semibold">
              {agentStatus?.status === "ready" ? "Agent Online" : "Ready (Fallback Mode)"}
            </span>
          </div>

          <div className="px-3 py-1.5 bg-[#F2EDE0] border border-[#E4DDCA] rounded-xl text-[#77735F]">
            Threshold:{" "}
            <span className="font-mono font-bold text-[#3F451F]">
              {agentStatus?.confidence_threshold
                ? `${(agentStatus.confidence_threshold * 100).toFixed(0)}%`
                : "80%"}
            </span>
          </div>
        </div>
      </div>

      {/* Main Chat Workspace */}
      <div className="flex-1 bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl p-4 shadow-sm flex flex-col overflow-hidden">
        {/* Messages Stream */}
        <div className="flex-1 overflow-y-auto space-y-4 pr-2">
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
                      ? "bg-red-50 text-red-800 border border-red-200 rounded-bl-xs"
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
                </div>

                <span className="text-[10px] text-[#77735F] mt-1 px-1">{m.timestamp}</span>
              </div>
            );
          })}

          {isProcessing && (
            <div className="flex items-start gap-2">
              <div className="bg-[#F2EDE0] border border-[#E4DDCA] rounded-2xl rounded-bl-xs px-4 py-3 text-sm text-[#77735F] flex items-center gap-2">
                <div className="w-3.5 h-3.5 border-2 border-[#3F451F] border-t-transparent rounded-full animate-spin" />
                <span>RollCall AI is retrieving and reasoning across verified tables...</span>
              </div>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        {/* Quick Prompts Bar */}
        <div className="pt-3 pb-2 flex items-center gap-2 overflow-x-auto no-scrollbar border-t border-[#E4DDCA]">
          {QUICK_PROMPTS.map((prompt) => (
            <button
              key={prompt}
              onClick={() => handleSendMessage(prompt)}
              disabled={isProcessing}
              className="shrink-0 px-3 py-1.5 rounded-xl bg-[#F2EDE0] hover:bg-[#EAE4D4] text-xs font-medium text-[#3F451F] transition-colors border border-[#E4DDCA]"
            >
              {prompt}
            </button>
          ))}
        </div>

        {/* Input & Upload Bar */}
        <div className="pt-2 flex items-center gap-2">
          {/* Hidden File Input */}
          <input
            type="file"
            ref={fileInputRef}
            onChange={handleFileUpload}
            accept=".png,.jpg,.jpeg,.csv,.pdf"
            className="hidden"
          />

          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            disabled={isUploading || isProcessing}
            title="Upload attendance sheet image or CSV"
            className="p-3 rounded-xl bg-[#F2EDE0] hover:bg-[#EAE4D4] text-[#3F451F] transition-colors border border-[#E4DDCA] shrink-0 disabled:opacity-50"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
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
            placeholder="Ask anything about attendance or absentees..."
            disabled={isProcessing}
            className="flex-1 bg-[#F2EDE0] border border-[#E4DDCA] rounded-xl px-4 py-3 text-sm text-[#24251C] placeholder-[#77735F] focus:outline-none focus:border-[#3F451F] disabled:opacity-50"
          />

          <button
            type="button"
            onClick={() => void handleSendMessage()}
            disabled={!inputQuery.trim() || isProcessing}
            className="px-5 py-3 rounded-xl bg-[#3F451F] text-[#FBF8F0] font-semibold text-sm hover:bg-[#323719] transition-all shadow-sm shrink-0 disabled:opacity-40"
          >
            Send
          </button>
        </div>
      </div>

      {/* Human-In-The-Loop Confirmation Modal */}
      {pendingConfirmation && (
        <div className="fixed inset-0 z-50 bg-black/40 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl p-6 max-w-lg w-full shadow-2xl">
            <div className="flex items-center gap-3 mb-2">
              <span className="w-3 h-3 rounded-full bg-amber-500 animate-ping" />
              <h3 className="text-lg font-bold text-[#24251C]">Human Confirmation Required</h3>
            </div>
            <p className="text-xs text-[#77735F]">
              The AI model extracted attendance records below the 80% confidence threshold. Please verify before committing to database.
            </p>

            <div className="mt-4 p-3 bg-amber-50 border border-amber-200 rounded-xl text-xs text-amber-900">
              <p className="font-semibold mb-1">Clarifying Question:</p>
              <p>{pendingConfirmation.request.question}</p>
            </div>

            {pendingConfirmation.request.affected_rows && pendingConfirmation.request.affected_rows.length > 0 && (
              <div className="mt-3 max-h-40 overflow-y-auto bg-[#F2EDE0] border border-[#E4DDCA] rounded-xl p-2.5 text-xs font-mono">
                {pendingConfirmation.request.affected_rows.map((row, i) => (
                  <div key={i} className="py-1 border-b border-[#E4DDCA] last:border-b-0">
                    {JSON.stringify(row)}
                  </div>
                ))}
              </div>
            )}

            <div className="mt-6 flex items-center justify-end gap-3">
              <button
                type="button"
                onClick={() => handleConfirmDecision(false)}
                className="px-4 py-2 rounded-xl text-sm font-semibold text-red-700 bg-red-50 hover:bg-red-100 transition-colors"
              >
                Reject & Discard
              </button>
              <button
                type="button"
                onClick={() => handleConfirmDecision(true)}
                className="px-5 py-2 rounded-xl text-sm font-semibold bg-[#3F451F] text-[#FBF8F0] hover:bg-[#323719] transition-colors shadow-sm"
              >
                Approve & Commit
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
