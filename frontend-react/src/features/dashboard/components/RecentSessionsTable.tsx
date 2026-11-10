"use client";

import React from "react";
import { Link } from "react-router-dom";
import type { VerifiedSession } from "@/types/dashboard";

interface RecentSessionsTableProps {
  sessions: VerifiedSession[];
  isLoading?: boolean;
}

export function RecentSessionsTable({ sessions, isLoading }: RecentSessionsTableProps) {
  // Format date: e.g. "08 Nov 2026"
  const formatDate = (isoStr: string) => {
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

  // Recent 5 sessions from API
  const displaySessions = sessions.slice(0, 5);

  return (
    <div className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl p-5 sm:p-6 shadow-2xs space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between pb-1">
        <div className="flex items-center space-x-2.5">
          <svg className="w-5 h-5 text-[#24251C]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
          </svg>
          <h2 className="text-lg font-bold text-[#24251C] tracking-tight">
            Recent Sessions
          </h2>
        </div>
        <Link
          to="/sessions"
          className="text-xs font-bold text-[#6C5119] hover:underline flex items-center space-x-1"
        >
          <span>View All</span>
          <span>→</span>
        </Link>
      </div>

      {/* Table */}
      <div className="overflow-x-auto">
        <table className="w-full text-left text-xs">
          <thead>
            <tr className="border-b border-[#E4DDCA] text-[#77735F] font-semibold">
              <th className="pb-2.5 pl-2">Session</th>
              <th className="pb-2.5">Room</th>
              <th className="pb-2.5">Date</th>
              <th className="pb-2.5 pr-2 text-right">Attendance</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#E4DDCA]/50 text-[#24251C]">
            {isLoading && (
              <tr>
                <td colSpan={4} className="py-6 text-center text-[#77735F]">
                  Loading recent sessions...
                </td>
              </tr>
            )}

            {!isLoading && displaySessions.length === 0 && (
              <tr>
                <td colSpan={4} className="py-6 text-center text-[#77735F]">
                  No session history available yet.
                </td>
              </tr>
            )}

            {!isLoading &&
              displaySessions.map((sess) => {
                const code = sess.subject_code || sess.session_id;
                const dateFormatted = formatDate(sess.date);

                return (
                  <tr key={sess.session_id} className="hover:bg-[#EDE8D8]/20 transition-colors">
                    <td className="py-3 pl-2 font-bold text-[#24251C]">
                      {code}
                    </td>
                    <td className="py-3 font-medium text-[#77735F]">
                      —
                    </td>
                    <td className="py-3 font-medium text-[#77735F]">
                      {dateFormatted}
                    </td>
                    <td className="py-3 pr-2 text-right">
                      {/* Attendance metric: Honest display of unavailable per-session breakdown */}
                      <span className="inline-flex px-2.5 py-0.5 rounded-full text-xs font-semibold bg-[#EDE8D8] text-[#77735F] border border-[#E4DDCA]">
                        Pending Summary
                      </span>
                    </td>
                  </tr>
                );
              })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
