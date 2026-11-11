import React from "react";
import type { VerifiedSummaryReport } from "@/types/dashboard";

interface InstitutionalBreakdownTablesProps {
  overviewReport: VerifiedSummaryReport | null;
  isLoading?: boolean;
}

export function InstitutionalBreakdownTables({
  overviewReport,
  isLoading = false,
}: InstitutionalBreakdownTablesProps) {
  const overall = overviewReport?.overall;
  const branchWise = overviewReport?.branch_wise ?? [];
  const roomWise = overviewReport?.room_wise ?? [];

  return (
    <div className="space-y-6">
      {/* 1. Numerical Attendance KPI Summary Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        {/* PRESENT */}
        <div className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl p-5 shadow-2xs flex items-center justify-between">
          <div>
            <span className="text-xs font-bold text-[#1B5E20] uppercase tracking-wider">
              Total Present
            </span>
            <p className="text-2xl sm:text-3xl font-extrabold text-[#1B5E20] mt-1">
              {isLoading ? "..." : overall?.present ?? 0}
            </p>
            <p className="text-xs text-[#77735F] mt-0.5">Authoritative Present Marks</p>
          </div>
          <div className="w-11 h-11 rounded-xl bg-emerald-100 text-emerald-800 flex items-center justify-center shrink-0 border border-emerald-300">
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" />
            </svg>
          </div>
        </div>

        {/* ABSENT */}
        <div className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl p-5 shadow-2xs flex items-center justify-between">
          <div>
            <span className="text-xs font-bold text-[#B71C1C] uppercase tracking-wider">
              Total Absent
            </span>
            <p className="text-2xl sm:text-3xl font-extrabold text-[#B71C1C] mt-1">
              {isLoading ? "..." : overall?.absent ?? 0}
            </p>
            <p className="text-xs text-[#77735F] mt-0.5">Confirmed Absent Marks</p>
          </div>
          <div className="w-11 h-11 rounded-xl bg-rose-100 text-rose-800 flex items-center justify-center shrink-0 border border-rose-300">
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </div>
        </div>

        {/* PERCENTAGE */}
        <div className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl p-5 shadow-2xs flex items-center justify-between">
          <div>
            <span className="text-xs font-bold text-[#6C5119] uppercase tracking-wider">
              Institute Attendance Rate
            </span>
            <p className="text-2xl sm:text-3xl font-extrabold text-[#24251C] mt-1">
              {isLoading ? "..." : overall?.percentage !== undefined ? `${overall.percentage.toFixed(1)}%` : "0.0%"}
            </p>
            <p className="text-xs text-[#77735F] mt-0.5">
              Out of {overall?.total ?? 0} total enrolled entries
            </p>
          </div>
          <div className="w-11 h-11 rounded-xl bg-[#EDE8D8] text-[#6C5119] flex items-center justify-center shrink-0 border border-[#E4DDCA]">
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
            </svg>
          </div>
        </div>
      </div>

      {/* 2. Branch-Wise Summary Table and Room-Wise Summary Table in 2 Columns */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 items-start">
        {/* Branch-Wise Summary */}
        <div className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl p-5 shadow-2xs space-y-3">
          <div className="flex items-center justify-between pb-2 border-b border-[#E4DDCA]/60">
            <div>
              <h3 className="text-base font-extrabold text-[#24251C]">Branch Breakdown</h3>
              <p className="text-xs text-[#77735F]">Academic department aggregation</p>
            </div>
            <span className="px-2.5 py-0.5 rounded-full text-xs font-bold bg-[#EDE8D8] text-[#6C5119] border border-[#E4DDCA]">
              {branchWise.length} Branches
            </span>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs sm:text-sm">
              <thead>
                <tr className="border-b border-[#E4DDCA] bg-[#EDE8D8]/30 text-[#77735F] font-semibold text-[11px] uppercase tracking-wider">
                  <th className="py-2.5 px-3">Branch</th>
                  <th className="py-2.5 px-3 text-right">Present</th>
                  <th className="py-2.5 px-3 text-right">Absent</th>
                  <th className="py-2.5 px-3 text-right">Total</th>
                  <th className="py-2.5 px-3 text-right">Rate</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#E4DDCA]/60 text-[#24251C]">
                {isLoading && (
                  <tr>
                    <td colSpan={5} className="py-6 text-center text-[#77735F] text-xs">
                      Loading branch statistics...
                    </td>
                  </tr>
                )}

                {!isLoading && branchWise.length === 0 && (
                  <tr>
                    <td colSpan={5} className="py-6 text-center text-[#77735F] text-xs">
                      No branch statistics available.
                    </td>
                  </tr>
                )}

                {!isLoading &&
                  branchWise.map((b) => (
                    <tr key={b.branch} className="hover:bg-[#EDE8D8]/20 transition-colors">
                      <td className="py-2.5 px-3 font-bold text-[#6C5119]">{b.branch}</td>
                      <td className="py-2.5 px-3 text-right font-medium text-emerald-800">{b.present}</td>
                      <td className="py-2.5 px-3 text-right font-medium text-rose-800">{b.absent}</td>
                      <td className="py-2.5 px-3 text-right font-medium">{b.total}</td>
                      <td className="py-2.5 px-3 text-right font-mono font-bold text-[#24251C]">
                        {typeof b.percentage === "number" ? `${b.percentage.toFixed(1)}%` : "0.0%"}
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Room-Wise Summary */}
        <div className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl p-5 shadow-2xs space-y-3">
          <div className="flex items-center justify-between pb-2 border-b border-[#E4DDCA]/60">
            <div>
              <h3 className="text-base font-extrabold text-[#24251C]">Room Breakdown</h3>
              <p className="text-xs text-[#77735F]">Lecture hall & lab facility utilization</p>
            </div>
            <span className="px-2.5 py-0.5 rounded-full text-xs font-bold bg-[#EDE8D8] text-[#6C5119] border border-[#E4DDCA]">
              {roomWise.length} Rooms
            </span>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs sm:text-sm">
              <thead>
                <tr className="border-b border-[#E4DDCA] bg-[#EDE8D8]/30 text-[#77735F] font-semibold text-[11px] uppercase tracking-wider">
                  <th className="py-2.5 px-3">Room ID</th>
                  <th className="py-2.5 px-3 text-right">Present</th>
                  <th className="py-2.5 px-3 text-right">Absent</th>
                  <th className="py-2.5 px-3 text-right">Total</th>
                  <th className="py-2.5 px-3 text-right">Rate</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#E4DDCA]/60 text-[#24251C]">
                {isLoading && (
                  <tr>
                    <td colSpan={5} className="py-6 text-center text-[#77735F] text-xs">
                      Loading room statistics...
                    </td>
                  </tr>
                )}

                {!isLoading && roomWise.length === 0 && (
                  <tr>
                    <td colSpan={5} className="py-6 text-center text-[#77735F] text-xs">
                      No room statistics available.
                    </td>
                  </tr>
                )}

                {!isLoading &&
                  roomWise.map((r) => (
                    <tr key={r.room_id} className="hover:bg-[#EDE8D8]/20 transition-colors">
                      <td className="py-2.5 px-3 font-mono font-bold text-[#6C5119]">{r.room_id}</td>
                      <td className="py-2.5 px-3 text-right font-medium text-emerald-800">{r.present}</td>
                      <td className="py-2.5 px-3 text-right font-medium text-rose-800">{r.absent}</td>
                      <td className="py-2.5 px-3 text-right font-medium">{r.total}</td>
                      <td className="py-2.5 px-3 text-right font-mono font-bold text-[#24251C]">
                        {typeof r.percentage === "number" ? `${r.percentage.toFixed(1)}%` : "0.0%"}
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}

