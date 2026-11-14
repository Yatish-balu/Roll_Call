"use client";

import React, { useState } from "react";
import { Link } from "react-router-dom";
import type { VerifiedSession } from "@/types/dashboard";

interface TodaysClassesProps {
  sessions: VerifiedSession[];
  allSessions?: VerifiedSession[];
  isLoading?: boolean;
}

export function TodaysClasses({ sessions, allSessions = [], isLoading }: TodaysClassesProps) {
  const [tab, setTab] = useState<"TODAY" | "RECENT">(() =>
    sessions.length > 0 ? "TODAY" : "RECENT"
  );

  const displayList = tab === "TODAY" ? sessions : allSessions.slice(0, 10);

  const formatDate = (isoStr?: string | null) => {
    if (!isoStr) return "Date TBD";
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
      {/* Header with Switcher Tabs */}
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

        <Link
          to="/sessions"
          className="text-xs font-bold text-[#6C5119] hover:underline flex items-center space-x-1"
        >
          <span>All Sessions</span>
          <span>→</span>
        </Link>
      </div>

      {/* Loading Skeleton */}
      {isLoading && (
        <div className="space-y-2 py-2">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-14 rounded-xl bg-[#EDE8D8]/50 animate-pulse" />
          ))}
        </div>
      )}

      {/* Empty State */}
      {!isLoading && displayList.length === 0 && (
        <div className="py-8 text-center space-y-1.5 border border-dashed border-[#E4DDCA] rounded-xl bg-[#F2EDE0]/30">
          <p className="text-xs font-bold text-[#24251C]">
            {tab === "TODAY" ? "No Classes Scheduled Today" : "No Sessions Recorded"}
          </p>
          <p className="text-[11px] text-[#77735F]">
            {tab === "TODAY"
              ? "Switch to Recent Sessions or schedule a new class."
              : "Register sessions via Timetable or the AI Assistant."}
          </p>
        </div>
      )}

      {/* Classes List: Scrollable container so page never expands */}
      {!isLoading && displayList.length > 0 && (
        <div className="space-y-2 max-h-[350px] overflow-y-auto pr-1">
          {displayList.map((sess) => {
            const code = sess.subject_code || sess.session_id;
            const subject = sess.subject;
            const dateStr = formatDate(sess.date);

            return (
              <div
                key={sess.session_id}
                className="relative flex items-center justify-between p-3 rounded-xl border bg-white border-[#E4DDCA] hover:border-[#6C5119]/50 transition-all shadow-2xs"
              >
                {/* Left: Code, Subject, Date */}
                <div className="min-w-0 pr-3">
                  <div className="flex items-center space-x-2">
                    <span className="font-extrabold text-xs text-[#24251C] tracking-tight truncate">
                      {code}
                    </span>
                    <span className="px-1.5 py-0.2 rounded text-[10px] font-bold bg-[#EDE8D8] text-[#6C5119]">
                      {dateStr}
                    </span>
                  </div>
                  <p className="text-xs text-[#77735F] truncate max-w-[220px] sm:max-w-[320px] mt-0.5">
                    {subject}
                  </p>
                </div>

                {/* Right: Take Attendance Button */}
                <Link
                  to={`/attendance?session=${encodeURIComponent(sess.session_id)}`}
                  className="inline-flex items-center space-x-1 px-3 py-1.5 rounded-lg text-xs font-bold bg-[#6C5119] hover:bg-[#594214] text-white shadow-2xs transition-colors shrink-0"
                >
                  <span>Attendance</span>
                  <span>→</span>
                </Link>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
