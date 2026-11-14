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
  // Live attendance metrics from backend
  const overallPercentage = overallReport?.overall?.percentage ?? null;
  // A date with no attendance recorded has no rate. Showing 0% would claim
  // every student was absent, so fall back to the "no sessions" state.
  const todayTotal = todayReport?.overall?.total ?? 0;
  const todayPercentage = todayTotal > 0 ? todayReport?.overall?.percentage ?? null : null;
  const sessionsCount = sessions?.total ?? sessions?.items?.length ?? 0;

  // Rate for circular progress. This ring belongs to the Today's Attendance
  // panel, so it must never borrow the all-time rate when today has no data.
  const hasRate = todayPercentage !== null;
  const displayRate = todayPercentage !== null ? Math.round(todayPercentage) : null;
  const strokeDash = displayRate !== null ? Math.min(100, Math.max(0, displayRate)) : 0;
  const circumference = 2 * Math.PI * 28; // radius 28 -> 175.93
  const strokeOffset = circumference - (strokeDash / 100) * circumference;

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4 sm:gap-6">
      {/* 1. Today's Attendance Panel */}
      <div className="card-crisp bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl p-4 sm:p-5 shadow-2xs flex items-center justify-between">
        <div className="flex items-center space-x-3.5">
          <div className="w-11 h-11 rounded-xl bg-[#EDE8D8] text-[#6C5119] flex items-center justify-center shrink-0 border border-[#E4DDCA]/60">
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
            </svg>
          </div>
          <div>
            <p className="text-[11px] font-bold text-[#77735F] uppercase tracking-wider">
              Today&apos;s Attendance
            </p>
            <div className="flex items-baseline space-x-2 mt-0.5">
              <h2 className="text-xl sm:text-2xl font-extrabold text-[#24251C]">
                {isLoading
                  ? "..."
                  : todayTotal > 0 && todayReport?.overall
                  ? `${todayReport.overall.confirmed} / ${todayTotal}`
                  : sessionsCount > 0
                  ? `${sessionsCount} ${sessionsCount === 1 ? "Session" : "Sessions"}`
                  : "—"}
              </h2>
            </div>
            <p className="text-[11px] text-[#77735F] font-medium">
              {todayTotal > 0
                ? "Recorded Marks"
                : sessionsCount > 0
                ? "Active Timetable Sessions"
                : "No sessions recorded today"}
            </p>
          </div>
        </div>

        {/* Circular SVG Progress Ring */}
        <div className="relative w-15 h-15 shrink-0 flex items-center justify-center">
          <svg className="w-full h-full -rotate-90" viewBox="0 0 68 68">
            <circle
              cx="34"
              cy="34"
              r="28"
              fill="none"
              stroke="#EDE8D8"
              strokeWidth="6"
            />
            <circle
              cx="34"
              cy="34"
              r="28"
              fill="none"
              stroke="#72785E"
              strokeWidth="6"
              strokeDasharray={circumference}
              strokeDashoffset={strokeOffset}
              strokeLinecap="round"
              className="transition-all duration-700 ease-out"
            />
          </svg>
          <div className="absolute inset-0 flex items-center justify-center">
            <span className="text-xs font-extrabold text-[#24251C]">
              {isLoading ? "..." : hasRate ? `${displayRate}%` : "—"}
            </span>
          </div>
        </div>
      </div>

      {/* 2. Overall Attendance Panel */}
      <div className="card-crisp bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl p-4 sm:p-5 shadow-2xs flex items-center justify-between relative overflow-hidden">
        <div className="flex items-center space-x-3.5 z-10">
          <div className="w-11 h-11 rounded-xl bg-[#EDE8D8] text-[#6C5119] flex items-center justify-center shrink-0 border border-[#E4DDCA]/60">
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0zm6 3a2 2 0 11-4 0 2 2 0 014 0zM7 10a2 2 0 11-4 0 2 2 0 014 0z" />
            </svg>
          </div>
          <div>
            <p className="text-xs font-bold text-[#77735F] uppercase tracking-wider">
              Overall Attendance
            </p>
            <div className="flex items-baseline space-x-2 mt-1">
              <h2 className="text-2xl sm:text-3xl font-extrabold text-[#24251C]">
                {isLoading
                  ? "..."
                  : overallPercentage !== null
                  ? `${overallPercentage.toFixed(1)}%`
                  : "—"}
              </h2>
            </div>
            <div className="flex items-center space-x-1.5 mt-0.5">
              <span className="text-xs font-bold text-emerald-700">
                {overallReport?.overall?.total
                  ? `↑ ${overallReport.overall.confirmed} Confirmed`
                  : "Live Metric"}
              </span>
              <span className="text-[11px] text-[#77735F]">
                ({overallReport?.overall?.total ?? 0} total records)
              </span>
            </div>
          </div>
        </div>

        {/* Decorative Vertical Bar Chart with Wave Accent */}
        <div className="flex items-end space-x-1.5 h-12 z-10 opacity-85 shrink-0 pl-2">
          <div className="w-2 rounded-t-xs bg-[#6C5119]/40 h-5" />
          <div className="w-2 rounded-t-xs bg-[#72785E]/60 h-8" />
          <div className="w-2 rounded-t-xs bg-[#6C5119]/70 h-6" />
          <div className="w-2 rounded-t-xs bg-[#3F451F]/80 h-10" />
          <div className="w-2 rounded-t-xs bg-[#6C5119] h-12" />
        </div>

        {/* Subtle Wave Backdrop */}
        <div className="absolute right-0 bottom-0 pointer-events-none opacity-15">
          <svg width="140" height="60" viewBox="0 0 140 60" fill="none">
            <path d="M0 45 C40 10, 80 55, 140 25 L140 60 L0 60 Z" fill="#6C5119" />
          </svg>
        </div>
      </div>
    </div>
  );
}
