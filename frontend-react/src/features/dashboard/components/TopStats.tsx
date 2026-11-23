"use client";

import React from "react";
import type { VerifiedSummaryReport, VerifiedSessionPage } from "@/types/dashboard";

interface TopStatsProps {
  sessions: VerifiedSessionPage | null;
  overallReport: VerifiedSummaryReport | null;
  todayReport: VerifiedSummaryReport | null;
  isLoading?: boolean;
}

export function TopStats({ sessions, overallReport, todayReport, isLoading }: TopStatsProps) {
  const overallPercentage = overallReport?.overall?.percentage ?? null;
  const todayTotal = todayReport?.overall?.total ?? 0;
  const todayPercentage = todayTotal > 0 ? todayReport?.overall?.percentage ?? null : null;
  const effectiveRate = todayPercentage !== null ? todayPercentage : overallPercentage;

  const totalPresent = todayReport?.overall?.present ?? overallReport?.overall?.present ?? 0;
  const totalAbsent = todayReport?.overall?.absent ?? overallReport?.overall?.absent ?? 0;
  const sessionsCount = sessions?.total ?? sessions?.items?.length ?? 0;

  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4">
      {/* 1. Attendance Rate */}
      <div className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl p-4 shadow-2xs flex items-center justify-between">
        <div>
          <span className="text-[11px] font-bold text-[#77735F] uppercase tracking-wider block">
            Attendance Rate
          </span>
          <p className="text-xl sm:text-2xl font-black text-[#24251C] mt-0.5">
            {isLoading ? "..." : effectiveRate !== null ? `${effectiveRate.toFixed(1)}%` : "—"}
          </p>
          <span className="text-[10px] text-[#77735F] font-semibold">
            {todayPercentage !== null ? "Today's Live Metric" : "Institutional Aggregate"}
          </span>
        </div>
        <div className="w-10 h-10 rounded-xl bg-[#EDE8D8] text-[#6C5119] flex items-center justify-center shrink-0 border border-[#E4DDCA]">
          <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
          </svg>
        </div>
      </div>

      {/* 2. Total Present */}
      <div className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl p-4 shadow-2xs flex items-center justify-between">
        <div>
          <span className="text-[11px] font-bold text-emerald-800 uppercase tracking-wider block">
            Total Present
          </span>
          <p className="text-xl sm:text-2xl font-black text-emerald-700 mt-0.5">
            {isLoading ? "..." : totalPresent}
          </p>
          <span className="text-[10px] text-[#77735F] font-semibold">
            Verified Marks
          </span>
        </div>
        <div className="w-10 h-10 rounded-xl bg-emerald-100 text-emerald-800 flex items-center justify-center shrink-0 border border-emerald-300">
          <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" />
          </svg>
        </div>
      </div>

      {/* 3. Total Absent */}
      <div className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl p-4 shadow-2xs flex items-center justify-between">
        <div>
          <span className="text-[11px] font-bold text-rose-800 uppercase tracking-wider block">
            Total Absent
          </span>
          <p className="text-xl sm:text-2xl font-black text-rose-700 mt-0.5">
            {isLoading ? "..." : totalAbsent}
          </p>
          <span className="text-[10px] text-[#77735F] font-semibold">
            Confirmed Absentees
          </span>
        </div>
        <div className="w-10 h-10 rounded-xl bg-rose-100 text-rose-800 flex items-center justify-center shrink-0 border border-rose-300">
          <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M6 18L18 6M6 6l12 12" />
          </svg>
        </div>
      </div>

      {/* 4. Total Sessions */}
      <div className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl p-4 shadow-2xs flex items-center justify-between">
        <div>
          <span className="text-[11px] font-bold text-[#6C5119] uppercase tracking-wider block">
            Active Sessions
          </span>
          <p className="text-xl sm:text-2xl font-black text-[#24251C] mt-0.5">
            {isLoading ? "..." : sessionsCount}
          </p>
          <span className="text-[10px] text-[#77735F] font-semibold">
            {todayTotal > 0 ? "Today's Schedule" : "Institutional Register"}
          </span>
        </div>
        <div className="w-10 h-10 rounded-xl bg-[#EDE8D8] text-[#6C5119] flex items-center justify-center shrink-0 border border-[#E4DDCA]">
          <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
          </svg>
        </div>
      </div>
    </div>
  );
}
