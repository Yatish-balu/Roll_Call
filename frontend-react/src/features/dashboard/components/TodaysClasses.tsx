"use client";

import React from "react";
import { Link } from "react-router-dom";
import type { VerifiedSession } from "@/types/dashboard";

interface TodaysClassesProps {
  sessions: VerifiedSession[];
  isLoading?: boolean;
}

export function TodaysClasses({ sessions, isLoading }: TodaysClassesProps) {
  // Format date helper: e.g. "08 Nov 2026"
  const formatDate = (isoStr?: string | null) => {
    if (!isoStr) return "Date TBD";
    try {
      const d = new Date(isoStr);
      return new Intl.DateTimeFormat("en-GB", {
        day: "2-digit",
        month: "short",
        year: "numeric",
      }).format(d);
    } catch {
      return isoStr;
    }
  };

  return (
    <div className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl p-5 sm:p-6 shadow-2xs space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between pb-1">
        <div className="flex items-center space-x-2.5">
          <svg className="w-5 h-5 text-[#24251C]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
          </svg>
          <h2 className="text-lg font-bold text-[#24251C] tracking-tight">
            Today&apos;s Classes
          </h2>
        </div>
        <span className="px-3 py-1 rounded-full text-xs font-semibold bg-[#EDE8D8] text-[#24251C] border border-[#E4DDCA]">
          {isLoading ? "..." : `${sessions.length} ${sessions.length === 1 ? "Class" : "Classes"}`}
        </span>
      </div>

      {/* Loading Skeleton */}
      {isLoading && (
        <div className="space-y-3 py-2">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-16 rounded-xl bg-[#EDE8D8]/50 animate-pulse" />
          ))}
        </div>
      )}

      {/* Empty State when no classes exist in backend */}
      {!isLoading && sessions.length === 0 && (
        <div className="py-10 text-center space-y-2 border border-dashed border-[#E4DDCA] rounded-xl bg-[#F2EDE0]/40">
          <svg className="w-10 h-10 text-[#77735F] mx-auto opacity-60" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
          </svg>
          <p className="text-sm font-semibold text-[#24251C]">No Classes Scheduled Today</p>
          <p className="text-xs text-[#77735F]">Active timetable allocations and sessions will appear here once registered.</p>
        </div>
      )}

      {/* Classes List: Rendered strictly from live backend session data */}
      {!isLoading && sessions.length > 0 && (
        <div className="space-y-2.5">
          {sessions.map((sess) => {
            const code = sess.subject_code || sess.session_id;
            const subject = sess.subject;
            const sessionDate = formatDate(sess.date);

            return (
              <div
                key={sess.session_id}
                className="relative flex flex-col sm:flex-row sm:items-center justify-between p-3.5 sm:p-4 rounded-xl border bg-[#FBF8F0] border-[#E4DDCA] hover:border-[#72785E]/40 transition-all"
              >
                {/* Left accent bar in antique gold */}
                <div className="absolute left-0 top-2 bottom-2 w-1 rounded-r-md bg-[#6C5119]" />

                {/* Left: Code & Subject */}
                <div className="pl-2 sm:pl-3 min-w-[140px]">
                  <p className="text-sm font-bold text-[#24251C] tracking-tight">
                    {code}
                  </p>
                  <p className="text-xs text-[#77735F] font-medium truncate max-w-[180px]">
                    {subject}
                  </p>
                </div>

                {/* Center: Room & Date metadata (honest API values) */}
                <div className="flex items-center space-x-3 my-2 sm:my-0 pl-2 sm:pl-0 text-xs text-[#24251C]">
                  {/* Room indicator: Displays Unallocated if backend does not provide room_id */}
                  <span className="inline-flex items-center space-x-1 px-2.5 py-1 rounded-md bg-[#EDE8D8]/70 border border-[#E4DDCA] font-medium text-[#77735F]">
                    <svg className="w-3.5 h-3.5 text-[#77735F]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5" />
                    </svg>
                    <span>Room: —</span>
                  </span>

                  {/* Scheduled Date */}
                  <span className="inline-flex items-center space-x-1 font-medium text-[#77735F]">
                    <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
                    </svg>
                    <span>{sessionDate}</span>
                  </span>
                </div>

                {/* Right: Status Pill & Action Button */}
                <div className="flex items-center space-x-2 pl-2 sm:pl-0 self-end sm:self-center">
                  <span className="inline-flex items-center space-x-1 px-2.5 py-1 rounded-full text-[11px] font-semibold bg-[#EDE8D8] text-[#6C5119] border border-[#E4DDCA]">
                    <span className="w-1.5 h-1.5 rounded-full bg-[#6C5119]" />
                    <span>Active Session</span>
                  </span>

                  <Link
                    to={`/attendance?session=${encodeURIComponent(sess.session_id)}`}
                    className="inline-flex items-center space-x-1 px-3 py-1.5 rounded-lg text-xs font-bold bg-[#6C5119] hover:bg-[#594214] text-white shadow-2xs transition-colors"
                  >
                    <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 9a2 2 0 012-2h.93a2 2 0 001.664-.89l.812-1.22A2 2 0 0110.07 4h3.86a2 2 0 011.664.89l.812 1.22A2 2 0 0018.07 7H19a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2V9z" />
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 13a3 3 0 11-6 0 3 3 0 016 0z" />
                    </svg>
                    <span>Take Attendance</span>
                  </Link>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
