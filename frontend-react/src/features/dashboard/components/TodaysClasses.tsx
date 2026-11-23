"use client";

import React, { useState } from "react";
import { Link } from "react-router-dom";
import type { VerifiedSession } from "@/types/dashboard";
import { ExtraClassModal } from "@/features/sessions/components/ExtraClassModal";
import { DelegateClassModal } from "@/features/sessions/components/DelegateClassModal";

interface TodaysClassesProps {
  sessions: VerifiedSession[];
  allSessions?: VerifiedSession[];
  isLoading?: boolean;
}

export function TodaysClasses({ sessions, allSessions = [], isLoading }: TodaysClassesProps) {
  const [tab, setTab] = useState<"TODAY" | "RECENT">(() =>
    sessions.length > 0 ? "TODAY" : "RECENT"
  );

  const [isExtraModalOpen, setIsExtraModalOpen] = useState(false);
  const [delegatingSession, setDelegatingSession] = useState<VerifiedSession | null>(null);

  const displayList = tab === "TODAY" ? sessions : allSessions.slice(0, 10);

  const formatDate = (isoStr?: string | null) => {
    if (!isoStr) return "Today";
    try {
      const d = new Date(isoStr);
      return new Intl.DateTimeFormat("en-GB", {
        day: "2-digit",
        month: "short",
      }).format(d);
    } catch {
      return isoStr;
    }
  };

  return (
    <div className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl p-4 sm:p-5 shadow-2xs space-y-3.5">
      {/* Header with Switcher Tabs & Quick Actions */}
      <div className="flex items-center justify-between pb-1 flex-wrap gap-2">
        <div className="flex items-center space-x-2">
          <button
            onClick={() => setTab("TODAY")}
            className={`px-3 py-1.5 rounded-xl text-xs font-bold transition-all cursor-pointer ${
              tab === "TODAY"
                ? "bg-[#3F451F] text-[#FBF8F0] shadow-2xs"
                : "text-[#77735F] hover:bg-[#EDE8D8]/50"
            }`}
          >
            Today&apos;s Schedule ({sessions.length})
          </button>
          <button
            onClick={() => setTab("RECENT")}
            className={`px-3 py-1.5 rounded-xl text-xs font-bold transition-all cursor-pointer ${
              tab === "RECENT"
                ? "bg-[#3F451F] text-[#FBF8F0] shadow-2xs"
                : "text-[#77735F] hover:bg-[#EDE8D8]/50"
            }`}
          >
            Recent Sessions ({allSessions.length})
          </button>
        </div>

        <div className="flex items-center space-x-2">
          <button
            type="button"
            onClick={() => setIsExtraModalOpen(true)}
            className="px-2.5 py-1.5 rounded-xl bg-[#6C5119] hover:bg-[#594214] text-white text-xs font-bold transition-colors cursor-pointer flex items-center space-x-1 shadow-2xs"
            title="Schedule an extra, remedial or emergency class slot"
          >
            <span>➕</span>
            <span>Extra Class</span>
          </button>

          <Link
            to="/sessions"
            className="text-xs font-bold text-[#6C5119] hover:underline flex items-center space-x-1"
          >
            <span>All Sessions</span>
            <span>→</span>
          </Link>
        </div>
      </div>

      {/* Loading Skeleton */}
      {isLoading && (
        <div className="space-y-2 py-2">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-16 rounded-xl bg-[#EDE8D8]/50 animate-pulse" />
          ))}
        </div>
      )}

      {/* Empty State */}
      {!isLoading && displayList.length === 0 && (
        <div className="py-8 text-center space-y-2 border border-dashed border-[#E4DDCA] rounded-xl bg-[#F2EDE0]/30 px-4">
          <p className="text-xs font-bold text-[#24251C]">
            {tab === "TODAY" ? "No Classes Scheduled Today" : "No Sessions Recorded"}
          </p>
          <p className="text-[11px] text-[#77735F] max-w-sm mx-auto">
            {tab === "TODAY"
              ? "All classes from your timetable auto-populate here. Taking an emergency class?"
              : "Register sessions via Timetable or the Extra Class button."}
          </p>
          {tab === "TODAY" && (
            <button
              onClick={() => setIsExtraModalOpen(true)}
              type="button"
              className="mt-1 px-3 py-1.5 rounded-xl bg-[#6C5119] text-white text-xs font-bold hover:bg-[#594214] transition-colors cursor-pointer"
            >
              ➕ Schedule Extra Class
            </button>
          )}
        </div>
      )}

      {/* Classes List */}
      {!isLoading && displayList.length > 0 && (
        <div className="space-y-2.5 max-h-[380px] overflow-y-auto pr-1">
          {displayList.map((sess) => {
            const code = sess.subject_code || sess.session_id;
            const subject = sess.subject;
            const dateStr = formatDate(sess.date);
            const isProxy = sess.is_delegated && sess.delegation?.is_proxy_for_me;
            const isDelegatedAway = sess.is_delegated && !sess.delegation?.is_proxy_for_me;

            return (
              <div
                key={sess.session_id}
                className={`relative flex items-center justify-between p-3.5 rounded-xl border transition-all shadow-2xs ${
                  isProxy
                    ? "bg-amber-50/60 border-amber-300 hover:border-amber-400"
                    : isDelegatedAway
                    ? "bg-slate-50 border-slate-300 opacity-80"
                    : "bg-white border-[#E4DDCA] hover:border-[#6C5119]/50"
                }`}
              >
                {/* Left: Code, Subject, Date & Delegation Tag */}
                <div className="min-w-0 pr-3">
                  <div className="flex items-center space-x-2 flex-wrap gap-y-1">
                    <span className="font-extrabold text-xs text-[#24251C] tracking-tight">
                      {code}
                    </span>
                    <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-[#EDE8D8] text-[#6C5119]">
                      {dateStr}
                    </span>

                    {/* Delegation Badges */}
                    {isProxy && (
                      <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-amber-200 text-amber-900 border border-amber-300 flex items-center space-x-1">
                        <span>🤝</span>
                        <span>Proxy (from {sess.delegation?.from_name})</span>
                      </span>
                    )}

                    {isDelegatedAway && (
                      <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-slate-200 text-slate-700 border border-slate-300 flex items-center space-x-1">
                        <span>Delegated to {sess.delegation?.to_name}</span>
                      </span>
                    )}
                  </div>

                  <p className="text-xs text-[#77735F] truncate max-w-[240px] sm:max-w-[360px] mt-1">
                    {subject}
                  </p>
                </div>

                {/* Right: Actions */}
                <div className="flex items-center space-x-1.5 shrink-0">
                  {/* Delegate / Handover button */}
                  {!isDelegatedAway && (
                    <button
                      type="button"
                      onClick={() => setDelegatingSession(sess)}
                      className="px-2.5 py-1.5 rounded-lg text-xs font-bold text-[#77735F] bg-[#EDE8D8]/60 hover:bg-[#EDE8D8] transition-colors cursor-pointer hidden sm:inline-flex items-center space-x-1"
                      title="Delegate this class to a colleague"
                    >
                      <span>🤝</span>
                      <span>Delegate</span>
                    </button>
                  )}

                  {/* Take Attendance Button */}
                  <Link
                    to={`/attendance?session=${encodeURIComponent(sess.session_id)}`}
                    className="inline-flex items-center space-x-1.5 px-3 py-1.5 rounded-lg text-xs font-bold bg-[#3F451F] hover:bg-[#2F3417] text-white shadow-2xs transition-colors shrink-0 cursor-pointer"
                  >
                    <span>🟢</span>
                    <span>Attendance</span>
                    <span>→</span>
                  </Link>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Extra Class Modal */}
      <ExtraClassModal
        isOpen={isExtraModalOpen}
        onClose={() => setIsExtraModalOpen(false)}
        onSuccess={() => {
          window.dispatchEvent(new CustomEvent("rollcall-attendance-updated"));
        }}
      />

      {/* Class Delegation Modal */}
      {delegatingSession && (
        <DelegateClassModal
          isOpen={Boolean(delegatingSession)}
          onClose={() => setDelegatingSession(null)}
          onSuccess={() => {
            window.dispatchEvent(new CustomEvent("rollcall-attendance-updated"));
          }}
          sessionId={delegatingSession.session_id}
          subjectCode={delegatingSession.subject_code || undefined}
          subjectName={delegatingSession.subject}
          classDate={delegatingSession.date}
        />
      )}
    </div>
  );
}
