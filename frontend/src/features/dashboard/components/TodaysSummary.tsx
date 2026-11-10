"use client";

import React from "react";
import type { VerifiedOverallSummary } from "@/types/dashboard";

interface TodaysSummaryProps {
  summary?: VerifiedOverallSummary | null;
  isLoading?: boolean;
}

export function TodaysSummary({ summary, isLoading }: TodaysSummaryProps) {
  const hasData = summary !== null && summary !== undefined;
  const presentCount = hasData ? summary.present : "—";
  const absentCount = hasData ? summary.absent : "—";
  const pendingCount = hasData ? summary.pending : "—";
  const unreviewedCount = hasData ? summary.unreviewed : "—";

  return (
    <div className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl p-5 sm:p-6 shadow-2xs space-y-4">
      {/* Card Header */}
      <div className="flex items-center justify-between pb-1">
        <div className="flex items-center space-x-2.5">
          <svg
            className="w-5 h-5 text-[#24251C]"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"
            />
          </svg>
          <h2 className="text-lg font-bold text-[#24251C] tracking-tight">
            Today&apos;s Summary
          </h2>
        </div>
        <span className="text-xs font-semibold text-[#77735F]">
          {hasData ? `Total: ${summary.total}` : "Awaiting Data"}
        </span>
      </div>

      {/* 4 Attendance Status Cards: PRESENT, ABSENT, PENDING, UNREVIEWED */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5 sm:gap-3">
        {/* PRESENT */}
        <div className="bg-[#E8F5E9] border border-[#C8E6C9] rounded-xl p-3 flex flex-col items-center justify-center text-center space-y-1">
          <div className="w-7 h-7 rounded-full bg-[#C8E6C9]/60 flex items-center justify-center text-[#2E7D32]">
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.2} d="M5 13l4 4L19 7" />
            </svg>
          </div>
          <span className="text-[11px] font-bold text-[#2E7D32] uppercase tracking-wider">
            Present
          </span>
          <span className="text-xl sm:text-2xl font-black text-[#1B5E20]">
            {isLoading ? "..." : presentCount}
          </span>
        </div>

        {/* ABSENT */}
        <div className="bg-[#FFEBEE] border border-[#FFCDD2] rounded-xl p-3 flex flex-col items-center justify-center text-center space-y-1">
          <div className="w-7 h-7 rounded-full bg-[#FFCDD2]/60 flex items-center justify-center text-[#C62828]">
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </div>
          <span className="text-[11px] font-bold text-[#C62828] uppercase tracking-wider">
            Absent
          </span>
          <span className="text-xl sm:text-2xl font-black text-[#B71C1C]">
            {isLoading ? "..." : absentCount}
          </span>
        </div>

        {/* PENDING */}
        <div className="bg-[#FFF8E1] border border-[#FFE082] rounded-xl p-3 flex flex-col items-center justify-center text-center space-y-1">
          <div className="w-7 h-7 rounded-full bg-[#FFE082]/60 flex items-center justify-center text-[#F57F17]">
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </div>
          <span className="text-[11px] font-bold text-[#F57F17] uppercase tracking-wider">
            Pending
          </span>
          <span className="text-xl sm:text-2xl font-black text-[#E65100]">
            {isLoading ? "..." : pendingCount}
          </span>
        </div>

        {/* UNREVIEWED */}
        <div className="bg-[#EDE8D8] border border-[#DCD5BE] rounded-xl p-3 flex flex-col items-center justify-center text-center space-y-1">
          <div className="w-7 h-7 rounded-full bg-[#DCD5BE]/60 flex items-center justify-center text-[#72785E]">
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.2} d="M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093m0 3h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </div>
          <span className="text-[11px] font-bold text-[#72785E] uppercase tracking-wider">
            Unreviewed
          </span>
          <span className="text-xl sm:text-2xl font-black text-[#3F451F]">
            {isLoading ? "..." : unreviewedCount}
          </span>
        </div>
      </div>
    </div>
  );
}
