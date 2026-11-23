import React from "react";
import type { BranchSummary } from "@/services/api/exams";

export interface BranchSummaryTableProps {
  summaries: BranchSummary[];
  isLoading?: boolean;
}

export const BranchSummaryTable: React.FC<BranchSummaryTableProps> = ({
  summaries,
  isLoading = false,
}) => {
  if (isLoading) {
    return (
      <div className="bg-[#FBF8F0] dark:bg-[#181913] border border-[#E4DDCA] dark:border-[#2C3022] rounded-2xl p-8 text-center text-[#77735F]">
        <div className="inline-block animate-spin w-6 h-6 border-2 border-[#3F451F] border-t-transparent rounded-full mb-2" />
        <p className="text-xs font-semibold">Loading branch breakdown...</p>
      </div>
    );
  }

  if (!summaries || summaries.length === 0) {
    return (
      <div className="bg-[#FBF8F0] dark:bg-[#181913] border border-[#E4DDCA] dark:border-[#2C3022] rounded-2xl p-8 text-center text-[#77735F]">
        <p className="text-xs font-semibold">No branch summary data available.</p>
      </div>
    );
  }

  const grandTotal = summaries.reduce((acc, curr) => acc + curr.total, 0);
  const grandPresent = summaries.reduce((acc, curr) => acc + curr.present, 0);
  const grandAbsent = summaries.reduce((acc, curr) => acc + curr.absent, 0);
  const grandPercentage = grandTotal > 0 ? ((grandPresent / grandTotal) * 100).toFixed(1) : "0.0";

  return (
    <div className="bg-[#FBF8F0] dark:bg-[#181913] border border-[#E4DDCA] dark:border-[#2C3022] rounded-2xl overflow-hidden shadow-sm">
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className="bg-[#F2EDE0] dark:bg-[#11120D] text-[#77735F] dark:text-[#A9AE8C] uppercase text-xs border-b border-[#E4DDCA] dark:border-[#2C3022]">
            <tr>
              <th className="py-3 px-4 font-bold tracking-wider">Branch</th>
              <th className="py-3 px-4 font-bold tracking-wider text-right">Total</th>
              <th className="py-3 px-4 font-bold tracking-wider text-right">Present</th>
              <th className="py-3 px-4 font-bold tracking-wider text-right">Absent</th>
              <th className="py-3 px-4 font-bold tracking-wider text-right">Percentage</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#E4DDCA]/60 dark:divide-[#2C3022] text-[#24251C] dark:text-[#EDE8D8]">
            {summaries.map((item) => {
              const pct = typeof item.percentage === "number" ? item.percentage.toFixed(1) : item.percentage;
              return (
                <tr
                  key={item.branch}
                  className="hover:bg-[#F2EDE0]/50 dark:hover:bg-[#2C3117]/20 transition-colors"
                >
                  <td className="py-3.5 px-4">
                    <span className="font-mono font-bold text-[#3F451F] dark:text-[#D2A847] bg-[#EDE8D8] dark:bg-[#2C3117] px-2.5 py-1 rounded-md border border-[#E4DDCA] dark:border-[#2C3022] text-xs">
                      {item.branch}
                    </span>
                  </td>
                  <td className="py-3.5 px-4 font-mono font-semibold text-right">{item.total}</td>
                  <td className="py-3.5 px-4 font-mono font-bold text-emerald-700 dark:text-emerald-400 text-right">
                    {item.present}
                  </td>
                  <td className="py-3.5 px-4 font-mono font-bold text-rose-600 dark:text-rose-400 text-right">
                    {item.absent}
                  </td>
                  <td className="py-3.5 px-4 text-right">
                    <div className="flex items-center justify-end gap-2">
                      <span className="font-mono font-bold text-xs">{pct}%</span>
                      <div className="w-16 h-2 bg-[#EDE8D8] dark:bg-[#2C3117] rounded-full overflow-hidden hidden sm:block">
                        <div
                          className="h-full bg-[#3F451F] dark:bg-[#D2A847] rounded-full"
                          style={{ width: `${Math.min(100, Math.max(0, Number(pct)))}%` }}
                        />
                      </div>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
          <tfoot className="bg-[#EDE8D8]/50 dark:bg-[#1A1C15] font-bold text-xs uppercase tracking-wider text-[#24251C] dark:text-[#EDE8D8] border-t-2 border-[#E4DDCA] dark:border-[#2C3022]">
            <tr>
              <td className="py-3 px-4">Consolidated Total</td>
              <td className="py-3 px-4 font-mono text-right">{grandTotal}</td>
              <td className="py-3 px-4 font-mono text-emerald-700 dark:text-emerald-400 text-right">
                {grandPresent}
              </td>
              <td className="py-3 px-4 font-mono text-rose-600 dark:text-rose-400 text-right">
                {grandAbsent}
              </td>
              <td className="py-3 px-4 font-mono text-right text-sm text-[#3F451F] dark:text-[#D2A847]">
                {grandPercentage}%
              </td>
            </tr>
          </tfoot>
        </table>
      </div>
    </div>
  );
};
