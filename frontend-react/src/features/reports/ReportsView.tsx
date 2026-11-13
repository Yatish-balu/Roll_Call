import { useState } from "react";
import {
  fetchAnalyticsSummary,
  downloadExcelReport,
  downloadPdfReport,
} from "@/services/api/reports";
import { fetchSessions, type SessionItem } from "@/services/api/sessions";
import type { VerifiedSummaryReport } from "@/types/dashboard";
import { useResource } from "@/hooks/useResource";

export function ReportsView() {
  const summaryRes = useResource<VerifiedSummaryReport>(
    "/api/v1/reports/analytics-summary",
    () => fetchAnalyticsSummary()
  );
  const sessionsRes = useResource<{ items?: SessionItem[]; total?: number }>(
    "/api/v1/sessions?limit=50",
    () => fetchSessions({ limit: 50 })
  );

  const summary = summaryRes.data ?? null;
  const sessions = sessionsRes.data?.items ?? [];
  const isLoading = (summaryRes.isLoading && !summaryRes.data) || (sessionsRes.isLoading && !sessionsRes.data);
  const error = summaryRes.error
    ? summaryRes.error instanceof Error
      ? summaryRes.error.message
      : "Unable to load analytics report data."
    : null;

  const loadData = () => {
    void summaryRes.refresh();
    void sessionsRes.refresh();
  };

  // Filters
  const [selectedSessionId, setSelectedSessionId] = useState("");
  const [selectedDate, setSelectedDate] = useState("");
  const [includeBranchSummary, setIncludeBranchSummary] = useState(true);

  // Export State
  const [isExportingExcel, setIsExportingExcel] = useState(false);
  const [isExportingPdf, setIsExportingPdf] = useState(false);
  const [exportMessage, setExportMessage] = useState<string | null>(null);

  const handleExportExcel = async () => {
    setIsExportingExcel(true);
    setExportMessage(null);
    try {
      const blob = await downloadExcelReport({
        session_id: selectedSessionId || undefined,
        date: selectedDate || undefined,
        include_branch_summary: includeBranchSummary,
      });

      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `RollCall_Report_${selectedSessionId || selectedDate || "All"}.xlsx`;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);
      setExportMessage("Excel workbook exported successfully.");
    } catch (err: unknown) {
      if (err instanceof Error) {
        setExportMessage(`Excel export failed: ${err.message}`);
      } else {
        setExportMessage("Excel export failed.");
      }
    } finally {
      setIsExportingExcel(false);
    }
  };

  const handleExportPdf = async () => {
    setIsExportingPdf(true);
    setExportMessage(null);
    try {
      const blob = await downloadPdfReport({
        session_id: selectedSessionId || undefined,
        date: selectedDate || undefined,
        include_charts: true,
      });

      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `RollCall_Report_${selectedSessionId || selectedDate || "All"}.pdf`;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);
      setExportMessage("PDF document generated successfully.");
    } catch (err: unknown) {
      if (err instanceof Error) {
        setExportMessage(`PDF export failed: ${err.message}`);
      } else {
        setExportMessage("PDF export failed.");
      }
    } finally {
      setIsExportingPdf(false);
    }
  };

  const overall = summary?.overall;
  const branchList = summary?.branch_wise || [];

  return (
    <div className="space-y-6">
      {/* Header Bar */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-[#24251C] tracking-tight">
            Attendance Reports & Analytics
          </h1>
          <p className="text-sm text-[#77735F] mt-0.5">
            Audit-grade verification exports, departmental statistics, and official transcripts.
          </p>
        </div>
      </div>

      {exportMessage && (
        <div
          className={`p-3.5 rounded-xl text-xs font-semibold flex items-center justify-between ${
            exportMessage.includes("failed")
              ? "bg-red-50 text-red-700 border border-red-200"
              : "bg-emerald-50 text-emerald-800 border border-emerald-200"
          }`}
        >
          <span>{exportMessage}</span>
          <button onClick={() => setExportMessage(null)} className="text-xs hover:underline">
            Dismiss
          </button>
        </div>
      )}

      {/* Overview Metric Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl p-4 shadow-sm">
          <p className="text-xs uppercase font-bold text-[#77735F] tracking-wider">
            Verified Sessions
          </p>
          <p className="text-2xl font-bold text-[#24251C] mt-1">
            {isLoading ? "..." : sessions.length}
          </p>
          <span className="text-[11px] text-[#77735F]">Active academic calendar</span>
        </div>

        <div className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl p-4 shadow-sm">
          <p className="text-xs uppercase font-bold text-[#77735F] tracking-wider">
            Attendance Records
          </p>
          <p className="text-2xl font-bold text-[#3F451F] mt-1">
            {isLoading ? "..." : overall?.total ?? 0}
          </p>
          <span className="text-[11px] text-emerald-700 font-medium">Reconciled logs</span>
        </div>

        <div className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl p-4 shadow-sm">
          <p className="text-xs uppercase font-bold text-[#77735F] tracking-wider">
            Campus Average Rate
          </p>
          <p className="text-2xl font-bold text-[#6C5119] mt-1">
            {isLoading
              ? "..."
              : overall && overall.percentage !== undefined
              ? `${overall.percentage.toFixed(1)}%`
              : "—"}
          </p>
          <span className="text-[11px] text-[#77735F]">Across all active branches</span>
        </div>

        <div className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl p-4 shadow-sm">
          <p className="text-xs uppercase font-bold text-[#77735F] tracking-wider">
            Confirmed Marks
          </p>
          <p className="text-2xl font-bold text-[#24251C] mt-1">
            {isLoading ? "..." : overall?.confirmed ?? 0}
          </p>
          <span className="text-[11px] text-[#77735F]">Verified student attendances</span>
        </div>
      </div>

      {/* Export Control Panel */}
      <div className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl p-5 shadow-sm">
        <h2 className="text-base font-bold text-[#24251C] mb-1">Generate Verified Export</h2>
        <p className="text-xs text-[#77735F] mb-4">
          Select target session or date filter to export multi-sheet Excel or institutional PDF.
        </p>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4">
          <div>
            <label className="block text-xs font-semibold text-[#77735F] mb-1">
              Filter by Session ID
            </label>
            <select
              value={selectedSessionId}
              onChange={(e) => {
                setSelectedSessionId(e.target.value);
                if (e.target.value) setSelectedDate("");
              }}
              className="w-full bg-[#F2EDE0] border border-[#E4DDCA] rounded-xl px-3.5 py-2 text-sm text-[#24251C] focus:outline-none focus:border-[#3F451F]"
            >
              <option value="">All Sessions (Global Campus Roster)</option>
              {sessions.map((s) => (
                <option key={s.session_id} value={s.session_id}>
                  {s.session_id} — {s.subject || s.subject_code} ({s.date})
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-xs font-semibold text-[#77735F] mb-1">
              Or Filter by Date
            </label>
            <input
              type="date"
              value={selectedDate}
              onChange={(e) => {
                setSelectedDate(e.target.value);
                if (e.target.value) setSelectedSessionId("");
              }}
              className="w-full bg-[#F2EDE0] border border-[#E4DDCA] rounded-xl px-3.5 py-2 text-sm text-[#24251C] focus:outline-none focus:border-[#3F451F]"
            />
          </div>

          <div className="flex items-center pt-5">
            <label className="flex items-center gap-2 cursor-pointer text-xs font-semibold text-[#24251C]">
              <input
                type="checkbox"
                checked={includeBranchSummary}
                onChange={(e) => setIncludeBranchSummary(e.target.checked)}
                className="w-4 h-4 rounded text-[#3F451F] border-[#E4DDCA] focus:ring-[#3F451F]"
              />
              Include Branch & Room Breakdown Sheets
            </label>
          </div>
        </div>

        <div className="pt-2 flex flex-wrap items-center gap-3">
          <button
            onClick={handleExportExcel}
            disabled={isExportingExcel}
            className="inline-flex items-center gap-2 px-5 py-2.5 bg-[#3F451F] text-[#FBF8F0] text-sm font-semibold rounded-xl hover:bg-[#323719] transition-all shadow-sm disabled:opacity-50 cursor-pointer"
          >
            {isExportingExcel ? (
              <>
                <div className="w-4 h-4 border-2 border-[#FBF8F0] border-t-transparent rounded-full animate-spin" />
                Generating Excel...
              </>
            ) : (
              <>
                <svg className="w-4 h-4 text-emerald-300" fill="currentColor" viewBox="0 0 24 24">
                  <path d="M14 2H6c-1.1 0-1.99.9-1.99 2L4 20c0 1.1.89 2 1.99 2H18c1.1 0 2-.9 2-2V8l-6-6zm2 16H8v-2h8v2zm0-4H8v-2h8v2zm-3-5V3.5L18.5 9H13z" />
                </svg>
                Export Excel Report (.xlsx)
              </>
            )}
          </button>

          <button
            onClick={handleExportPdf}
            disabled={isExportingPdf}
            className="inline-flex items-center gap-2 px-5 py-2.5 bg-[#6C5119] text-[#FBF8F0] text-sm font-semibold rounded-xl hover:bg-[#584213] transition-all shadow-sm disabled:opacity-50 cursor-pointer"
          >
            {isExportingPdf ? (
              <>
                <div className="w-4 h-4 border-2 border-[#FBF8F0] border-t-transparent rounded-full animate-spin" />
                Generating PDF...
              </>
            ) : (
              <>
                <svg className="w-4 h-4 text-amber-200" fill="currentColor" viewBox="0 0 24 24">
                  <path d="M20 2H8c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm-8.5 7.5c0 .83-.67 1.5-1.5 1.5H9v2H7.5V7H10c.83 0 1.5.67 1.5 1.5v1zm5 2c0 .83-.67 1.5-1.5 1.5h-2.5V7H15c.83 0 1.5.67 1.5 1.5v3zm4-3H19v1h1.5V11H19v2h-1.5V7h3v1.5zM9 9.5h1v-1H9v1zM4 6H2v14c0 1.1.9 2 2 2h14v-2H4V6zm10 5.5h1v-3h-1v3z" />
                </svg>
                Export PDF Report (.pdf)
              </>
            )}
          </button>

          <button
            onClick={() => void loadData()}
            className="px-4 py-2.5 bg-[#F2EDE0] text-[#77735F] hover:text-[#24251C] text-sm font-semibold rounded-xl hover:bg-[#EAE4D4] transition-colors cursor-pointer"
          >
            Refresh Analytics
          </button>
        </div>
      </div>

      {/* Department & Branch Analytics Grid */}
      <div className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl overflow-hidden shadow-sm">
        <div className="p-4 border-b border-[#E4DDCA]">
          <h2 className="text-sm font-bold text-[#24251C] uppercase tracking-wider">
            Branch-Wise Attendance Breakdown
          </h2>
          <p className="text-xs text-[#77735F]">
            Computed percentage metrics based on live verified database records.
          </p>
        </div>

        {isLoading ? (
          <div className="p-10 text-center text-[#77735F]">
            <div className="inline-block animate-spin w-5 h-5 border-2 border-[#3F451F] border-t-transparent rounded-full mb-1.5" />
            <p className="text-xs">Computing statistics from backend...</p>
          </div>
        ) : error ? (
          <div className="p-8 text-center text-red-600 text-xs">{error}</div>
        ) : branchList.length === 0 ? (
          <div className="p-10 text-center text-[#77735F] text-xs">
            No departmental attendance records registered in database yet.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="bg-[#F2EDE0] text-[#77735F] uppercase text-xs border-b border-[#E4DDCA]">
                <tr>
                  <th className="py-3 px-4 font-semibold">Academic Branch</th>
                  <th className="py-3 px-4 font-semibold">Total Verified Records</th>
                  <th className="py-3 px-4 font-semibold">Present Count</th>
                  <th className="py-3 px-4 font-semibold">Compliance Rate</th>
                  <th className="py-3 px-4 font-semibold">Audit Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#E4DDCA]/60 text-[#24251C]">
                {branchList.map((row) => (
                  <tr key={row.branch} className="hover:bg-[#F2EDE0]/50 transition-colors">
                    <td className="py-3.5 px-4 font-bold text-[#3F451F]">{row.branch}</td>
                    <td className="py-3.5 px-4 font-mono">{row.total}</td>
                    <td className="py-3.5 px-4 font-mono text-emerald-700 font-semibold">
                      {row.present}
                    </td>
                    <td className="py-3.5 px-4 font-mono font-bold text-[#6C5119]">
                      {row.percentage !== undefined ? `${row.percentage.toFixed(1)}%` : "—"}
                    </td>
                    <td className="py-3.5 px-4">
                      <span className="inline-flex items-center gap-1.5 text-xs text-emerald-700 font-medium">
                        <span className="w-2 h-2 rounded-full bg-emerald-500" />
                        Accredited & Verified
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
