"use client";

import React, { useState, useRef } from "react";
import { Link } from "react-router-dom";
import { sendAgentQuery, uploadAttendanceFile } from "@/services/api/dashboard";
import type { VerifiedAgentResponse } from "@/types/dashboard";
import { AnimatedAiMascot } from "./AnimatedAiMascot";

export function AiAssistantCard() {
  const [query, setQuery] = useState("");
  const [isProcessing, setIsProcessing] = useState(false);
  const [lastResponse, setLastResponse] = useState<VerifiedAgentResponse | null>(null);
  const [statusNote, setStatusNote] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const chatInputRef = useRef<HTMLInputElement>(null);

  // Restore recent chat from persistent local storage
  const [recentChat, setRecentChat] = useState<{ query?: string; answer?: string } | null>(() => {
    if (typeof window === "undefined") return null;
    try {
      const raw = window.localStorage.getItem("rollcall_recent_chat_messages_v1");
      if (raw) {
        const msgs = JSON.parse(raw);
        if (Array.isArray(msgs) && msgs.length >= 2) {
          const lastUser = [...msgs].reverse().find((m: { sender: string; text?: string }) => m.sender === "user");
          const lastAssistant = [...msgs].reverse().find(
            (m: { sender: string; id?: string; text?: string }) => m.sender === "assistant" && m.id !== "welcome"
          );
          if (lastAssistant && lastAssistant.text) {
            return {
              query: lastUser?.text,
              answer: lastAssistant.text,
            };
          }
        }
      }
    } catch {
      // Ignore parse errors
    }
    return null;
  });

  const handleSend = async (e?: React.FormEvent, customQuery?: string) => {
    if (e) e.preventDefault();
    const queryText = (customQuery || query).trim();
    if (!queryText || isProcessing) return;

    setQuery("");
    setIsProcessing(true);
    setStatusNote(null);
    setErrorMessage(null);

    try {
      const resp = await sendAgentQuery(queryText);
      setLastResponse(resp);
      setRecentChat({ query: queryText, answer: resp.message });

      // Persist to shared conversation transcript
      if (typeof window !== "undefined") {
        try {
          const raw = window.localStorage.getItem("rollcall_recent_chat_messages_v1");
          const msgs = raw ? JSON.parse(raw) : [];
          const nowStr = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
          const updated = [
            ...msgs,
            { id: `u-${Date.now()}`, sender: "user", text: queryText, timestamp: nowStr },
            { id: `a-${Date.now() + 1}`, sender: "assistant", text: resp.message, timestamp: nowStr },
          ];
          window.localStorage.setItem("rollcall_recent_chat_messages_v1", JSON.stringify(updated.slice(-50)));
        } catch {
          // Ignore write errors
        }
      }
    } catch (err: unknown) {
      if (err instanceof Error) {
        setErrorMessage(`Backend Connection Error: ${err.message}. Verify that FastAPI backend is running.`);
      } else {
        setErrorMessage("AI Assistant is unreachable. Ensure the FastAPI service is active on port 8000.");
      }
    } finally {
      setIsProcessing(false);
    }
  };

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setIsProcessing(true);
    setStatusNote(`Scanning ${file.name}...`);
    setErrorMessage(null);

    try {
      const resp = await uploadAttendanceFile(file);
      setLastResponse(resp);
      // Only claim success when the backend actually succeeded; otherwise show
      // its reason (e.g. a photo with no readable rows).
      setStatusNote(
        resp.success
          ? `Processed ${file.name}.`
          : resp.message || `${file.name} could not be processed.`
      );
      if (typeof window !== "undefined") {
        window.dispatchEvent(
          new CustomEvent("rollcall-attendance-updated", {
            detail: { file: file.name, session_id: resp.session_id },
          })
        );
      }
    } catch (err: unknown) {
      if (err instanceof Error) {
        setErrorMessage(`Upload Error: ${err.message}. Backend attendance parser is unavailable.`);
      } else {
        setErrorMessage("Failed to upload attendance file. Verify backend connectivity.");
      }
    } finally {
      setIsProcessing(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  return (
    <div className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl p-5 sm:p-6 shadow-2xs space-y-4 flex flex-col justify-between transition-all">
      {/* Hidden File Input for Scan Attendance */}
      <input
        type="file"
        ref={fileInputRef}
        onChange={handleFileUpload}
        accept=".csv,.txt,.png,.jpg,.jpeg,.pdf"
        className="hidden"
      />

      {/* Card Header & Mascot Section */}
      <div className="space-y-3">
        <div className="flex items-start justify-between">
          <div>
            <div className="flex items-center space-x-1.5">
              <svg className="w-5 h-5 text-[#6C5119]" fill="currentColor" viewBox="0 0 24 24">
                <path d="M12 2l2.4 7.2h7.6l-6 4.8 2.4 7.2-6.4-4.8-6.4 4.8 2.4-7.2-6-4.8h7.6z" />
              </svg>
              <h2 className="text-lg font-bold text-[#24251C] tracking-tight">
                AI Assistant
              </h2>
            </div>
            <p className="text-xs text-[#77735F] font-medium mt-0.5">
              Your attendance assistant
            </p>
          </div>

          <span className="px-2.5 py-0.5 rounded-full text-[10px] font-bold bg-[#A77A13]/15 text-[#6C5119] border border-[#6C5119]/20 uppercase tracking-wide">
            Beta
          </span>
        </div>

        {/* Pure Code 3D Animated Vector Mascot */}
        <AnimatedAiMascot isThinking={isProcessing} />
      </div>

      {/* Backend Connection Error Banner */}
      {errorMessage && (
        <div className="p-3 rounded-xl bg-rose-50 border border-rose-200 text-rose-800 text-xs flex items-start space-x-2 animate-fadeIn">
          <svg className="w-4 h-4 text-rose-500 shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
          </svg>
          <div className="flex-1">
            <p className="font-semibold text-rose-900">Backend Unavailable</p>
            <p className="text-[11px] text-rose-700 mt-0.5">{errorMessage}</p>
          </div>
          <button
            onClick={() => setErrorMessage(null)}
            className="text-rose-400 hover:text-rose-700 text-xs font-bold"
          >
            ✕
          </button>
        </div>
      )}

      {/* Response Display Box (if agent has answered) */}
      {lastResponse ? (
        <div className="p-3.5 rounded-xl bg-[#EDE8D8]/70 border border-[#E4DDCA] text-xs text-[#24251C] space-y-2 shadow-2xs animate-fadeIn">
          <div className="flex items-center justify-between font-bold text-[11px] text-[#6C5119]">
            <span className="flex items-center space-x-1">
              <span>✦</span>
              <span>Assistant Insight</span>
            </span>
            <div className="flex items-center gap-2">
              <Link to="/assistant" className="text-[#6C5119] hover:underline font-semibold text-[10px]">
                Full Chat →
              </Link>
              <button
                onClick={() => setLastResponse(null)}
                className="text-[#77735F] hover:text-[#24251C] text-xs font-bold cursor-pointer"
              >
                ✕
              </button>
            </div>
          </div>
          <p className="leading-relaxed text-[#24251C] whitespace-pre-wrap">{lastResponse.message}</p>
        </div>
      ) : recentChat ? (
        <div className="p-3 rounded-xl bg-[#EDE8D8]/50 border border-[#E4DDCA] text-xs text-[#24251C] space-y-1.5 shadow-2xs">
          <div className="flex items-center justify-between font-bold text-[11px] text-[#6C5119]">
            <span className="flex items-center space-x-1">
              <span>💬</span>
              <span>Recent Conversation</span>
            </span>
            <Link to="/assistant" className="text-[#6C5119] hover:underline font-semibold text-[10px]">
              Open Assistant →
            </Link>
          </div>
          {recentChat.query && (
            <p className="text-[11px] font-medium text-[#77735F] italic truncate">
              "{recentChat.query}"
            </p>
          )}
          <p className="leading-relaxed text-[#24251C] line-clamp-2 text-[11px]">
            {recentChat.answer}
          </p>
        </div>
      ) : null}

      {/* Processing Status Note */}
      {statusNote && !errorMessage && (
        <p className="text-[11px] text-[#6C5119] font-medium italic flex items-center space-x-1.5">
          <span className="w-2 h-2 rounded-full bg-[#A77A13] animate-ping" />
          <span>{statusNote}</span>
        </p>
      )}

      {/* Quick Action Tiles */}
      <div className="space-y-2 pt-1">
        {/* Action 1: Scan Attendance */}
        <button
          onClick={() => fileInputRef.current?.click()}
          disabled={isProcessing}
          className="w-full flex items-center justify-between p-3 rounded-xl bg-white border border-[#E4DDCA] hover:border-[#6C5119]/50 hover:bg-[#F2EDE0]/60 hover:-translate-y-0.5 transition-all text-left shadow-2xs group cursor-pointer"
        >
          <div className="flex items-center space-x-3">
            <div className="w-8 h-8 rounded-lg bg-[#EDE8D8] text-[#6C5119] group-hover:bg-[#6C5119] group-hover:text-white transition-colors flex items-center justify-center shrink-0">
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 9a2 2 0 012-2h.93a2 2 0 001.664-.89l.812-1.22A2 2 0 0110.07 4h3.86a2 2 0 011.664.89l.812 1.22A2 2 0 0018.07 7H19a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2V9z" />
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 13a3 3 0 11-6 0 3 3 0 016 0z" />
              </svg>
            </div>
            <div>
              <p className="text-xs font-bold text-[#24251C] group-hover:text-[#6C5119] transition-colors">
                Scan Attendance
              </p>
              <p className="text-[10px] text-[#77735F] font-medium">
                From image or PDF sheet
              </p>
            </div>
          </div>
          <svg className="w-4 h-4 text-[#77735F] group-hover:translate-x-1 group-hover:text-[#6C5119] transition-all" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
          </svg>
        </button>

        {/* Action 2: Ask RollCall AI */}
        <button
          onClick={() => chatInputRef.current?.focus()}
          className="w-full flex items-center justify-between p-3 rounded-xl bg-white border border-[#E4DDCA] hover:border-[#6C5119]/50 hover:bg-[#F2EDE0]/60 hover:-translate-y-0.5 transition-all text-left shadow-2xs group cursor-pointer"
        >
          <div className="flex items-center space-x-3">
            <div className="w-8 h-8 rounded-lg bg-[#EDE8D8] text-[#6C5119] group-hover:bg-[#6C5119] group-hover:text-white transition-colors flex items-center justify-center shrink-0">
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
              </svg>
            </div>
            <div>
              <p className="text-xs font-bold text-[#24251C] group-hover:text-[#6C5119] transition-colors">
                Ask RollCall AI
              </p>
              <p className="text-[10px] text-[#77735F] font-medium">
                Get attendance insights, summaries & more
              </p>
            </div>
          </div>
          <svg className="w-4 h-4 text-[#77735F] group-hover:translate-x-1 group-hover:text-[#6C5119] transition-all" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
          </svg>
        </button>
      </div>

      {/* Interactive Quick Prompt Chips */}
      <div className="flex items-center gap-1.5 overflow-x-auto text-[11px] pt-1 no-scrollbar">
        <button
          type="button"
          disabled={isProcessing}
          onClick={() => void handleSend(undefined, "Summarize today's overall attendance")}
          className="px-2.5 py-1 rounded-lg bg-white border border-[#E4DDCA] text-[#3F451F] hover:bg-[#EDE8D8] hover:border-[#6C5119]/40 transition-all font-medium whitespace-nowrap cursor-pointer shadow-2xs"
        >
          📊 Summarize Today
        </button>
        <button
          type="button"
          disabled={isProcessing}
          onClick={() => void handleSend(undefined, "List students with attendance below 75%")}
          className="px-2.5 py-1 rounded-lg bg-white border border-[#E4DDCA] text-[#3F451F] hover:bg-[#EDE8D8] hover:border-[#6C5119]/40 transition-all font-medium whitespace-nowrap cursor-pointer shadow-2xs"
        >
          ⚠️ Defaulters
        </button>
        <button
          type="button"
          disabled={isProcessing}
          onClick={() => void handleSend(undefined, "Find vacant classrooms right now")}
          className="px-2.5 py-1 rounded-lg bg-white border border-[#E4DDCA] text-[#3F451F] hover:bg-[#EDE8D8] hover:border-[#6C5119]/40 transition-all font-medium whitespace-nowrap cursor-pointer shadow-2xs"
        >
          🚪 Vacant Rooms
        </button>
      </div>

      {/* Interactive Natural Language Chat Bar */}
      <form onSubmit={handleSend} className="pt-2">
        <div className="relative flex items-center">
          <input
            ref={chatInputRef}
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            disabled={isProcessing}
            placeholder="Ask anything about attendance..."
            className="w-full pl-3.5 pr-11 py-2.5 rounded-xl bg-white border border-[#E4DDCA] text-xs text-[#24251C] placeholder-[#77735F]/70 shadow-2xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#6C5119] transition-all disabled:opacity-50"
          />
          <button
            type="submit"
            disabled={isProcessing || !query.trim()}
            className={`absolute right-1.5 p-1.5 rounded-lg text-white shadow-2xs transition-all cursor-pointer ${
              query.trim()
                ? "bg-[#6C5119] hover:bg-[#594214] scale-100"
                : "bg-[#77735F]/40 cursor-not-allowed opacity-60"
            }`}
            aria-label="Send query"
          >
            {isProcessing ? (
              <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin block" />
            ) : (
              <svg className="w-4 h-4 rotate-45 -translate-y-0.5 translate-x-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
              </svg>
            )}
          </button>
        </div>
      </form>
    </div>
  );
}
