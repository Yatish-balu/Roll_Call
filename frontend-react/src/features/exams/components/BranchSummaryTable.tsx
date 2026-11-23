import React from "react";
import type { BranchSummaryItem } from "@/services/api/exams";

interface BranchSummaryTableProps {
  branches: BranchSummaryItem[];
}

export function BranchSummaryTable({ branches }: BranchSummaryTableProps) {
  if (!branches || branches.length === 0) {
    return (
      <div className="text-center py-6 text-sm text-gray-500">
        No branch summary data available yet.
      </div>
    );
  }

  const totals = branches.reduce(
    (acc, b) => ({
      total: acc.total + b.total_students,
      present: acc.present + b.present_count,
      absent: acc.absent + b.absent_count,
    }),
    { total: 0, present: 0, absent: 0 }
  );

  const overallPct = totals.total > 0
    ? Math.round((totals.present / totals.total) * 100)
    : 0;

  return (
    <div className="overflow-x-auto rounded-xl border border-gray-200">
      <table className="min-w-full divide-y divide-gray-200 text-sm">
        <thead className="bg-[#EDE8D8]/50">
          <tr>
            <th className="px-4 py-3 text-left font-semibold text-[#3F451F]">Branch</th>
            <th className="px-4 py-3 text-right font-semibold text-[#3F451F]">Total Candidates</th>
            <th className="px-4 py-3 text-right font-semibold text-[#3F451F]">Present</th>
            <th className="px-4 py-3 text-right font-semibold text-[#3F451F]">Absent</th>
            <th className="px-4 py-3 text-right font-semibold text-[#3F451F]">Attendance %</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100 bg-white">
          {branches.map((b) => (
            <tr key={b.branch} className="hover:bg-gray-50/80 transition-colors">
              <td className="px-4 py-2.5 font-bold text-gray-900">{b.branch}</td>
              <td className="px-4 py-2.5 text-right text-gray-700">{b.total_students}</td>
              <td className="px-4 py-2.5 text-right font-medium text-emerald-700">{b.present_count}</td>
              <td className="px-4 py-2.5 text-right font-medium text-red-600">
                {b.absent_count > 0 ? b.absent_count : "—"}
              </td>
              <td className="px-4 py-2.5 text-right font-semibold text-gray-900">
                {b.attendance_percentage}%
              </td>
            </tr>
          ))}
          <tr className="bg-gray-50/80 font-bold border-t-2 border-gray-200">
            <td className="px-4 py-3 text-gray-900">Total Across Branches</td>
            <td className="px-4 py-3 text-right text-gray-900">{totals.total}</td>
            <td className="px-4 py-3 text-right text-emerald-800">{totals.present}</td>
            <td className="px-4 py-3 text-right text-red-700">{totals.absent}</td>
            <td className="px-4 py-3 text-right text-[#3F451F]">{overallPct}%</td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}
