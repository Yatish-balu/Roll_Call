import React, { useState, useMemo } from "react";
import { fetchAuditLogs, type AuditLogItem, type AuditLogQueryParams } from "@/services/api/audit";
import { useResource } from "@/hooks/useResource";

const EVENT_TYPES = [
  "ALL",
  "ATTENDANCE_REPLACE",
  "ATTENDANCE_RECORD",
  "ATTENDANCE_RECONCILE",
  "SESSION_CREATE",
  "TEACHER_SUBJECT_ASSIGN",
  "AGENT_CONFIRMED",
];

export function AuditLogView() {
  // Filters
  const [eventType, setEventType] = useState("ALL");
  const [actorFilter, setActorFilter] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");

  // Pagination
  const [page, setPage] = useState(0);
  const pageSize = 15;

  const params: AuditLogQueryParams = useMemo(() => {
    const p: AuditLogQueryParams = {
      limit: pageSize,
      offset: page * pageSize,
    };
    if (eventType !== "ALL") p.event_type = eventType;
    if (actorFilter.trim()) p.actor = actorFilter.trim();
    if (startDate) p.start_date = startDate;
    if (endDate) p.end_date = endDate;
    return p;
  }, [eventType, actorFilter, startDate, endDate, page]);

  const auditKey = `/api/v1/audit/logs?limit=${pageSize}&offset=${page * pageSize}&type=${eventType}&actor=${actorFilter}&start=${startDate}&end=${endDate}`;
  const auditRes = useResource<{ items?: AuditLogItem[]; total?: number }>(
    auditKey,
    () => fetchAuditLogs(params)
  );

  const logs = auditRes.data?.items ?? [];
  const total = auditRes.data?.total ?? 0;
  const isLoading = auditRes.isLoading && !auditRes.data;
  const error = auditRes.error
    ? auditRes.error instanceof Error
      ? auditRes.error.message
      : "Failed to retrieve audit log trail from server."
    : null;

  const loadLogs = () => {
    void auditRes.refresh();
  };

  const formatLocalTime = (isoStr: string) => {
    try {
      const d = new Date(isoStr);
      if (isNaN(d.getTime())) return isoStr;
      return new Intl.DateTimeFormat("en-GB", {
        day: "2-digit",
        month: "short",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      }).format(d);
    } catch {
      return isoStr;
    }
  };

  const totalPages = Math.ceil(total / pageSize);

  return (
    <div className="space-y-6 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-2 border-b border-[#E4DDCA]/60">
        <div>
          <div className="flex items-center space-x-2.5 flex-wrap">
            <h1 className="text-2xl sm:text-3xl font-extrabold text-[#24251C] tracking-tight">
              Institutional Audit Logs
            </h1>
            <span className="px-2.5 py-0.5 rounded-full text-xs font-bold bg-[#EDE8D8] text-[#6C5119] border border-[#E4DDCA]">
              {total} Total Records
            </span>
            <span className="px-2 py-0.5 rounded-md text-[11px] font-black bg-rose-100 text-rose-800 border border-rose-300 uppercase">
              Admin Read-Only
            </span>
          </div>
          <p className="text-xs sm:text-sm text-[#77735F] mt-1">
            Immutable, append-only security trace of all attendance edits, subject mappings, and agent confirmations.
          </p>
        </div>

        <button
          onClick={() => void loadLogs()}
          disabled={isLoading}
          className="inline-flex items-center space-x-2 px-4 py-2 rounded-xl text-xs font-bold bg-white border border-[#E4DDCA] text-[#24251C] hover:bg-[#EDE8D8]/50 transition-colors shadow-2xs self-start sm:self-auto cursor-pointer disabled:opacity-50"
        >
          <svg className={`w-4 h-4 text-[#6C5119] ${isLoading ? "animate-spin" : ""}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
          </svg>
          <span>Refresh Trail</span>
        </button>
      </div>

      {/* Error Alert */}
      {error && (
        <div className="p-4 rounded-xl bg-rose-50 border border-rose-300 text-rose-900 text-xs flex items-center justify-between">
          <div className="flex items-center space-x-2.5">
            <svg className="w-5 h-5 text-rose-600 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
            <span>{error}</span>
          </div>
          <button
            onClick={() => void loadLogs()}
            className="font-bold underline ml-4 hover:text-[#24251C]"
          >
            Retry
          </button>
        </div>
      )}

      {/* Filters Bar */}
      <div className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl p-4 shadow-2xs grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
        {/* Event Type Filter */}
        <div>
          <label className="block text-[11px] font-bold text-[#77735F] uppercase mb-1">
            Event Type
          </label>
          <select
            value={eventType}
            onChange={(e) => {
              setEventType(e.target.value);
              setPage(0);
            }}
            className="w-full px-3 py-2 rounded-xl bg-white border border-[#E4DDCA] text-xs font-semibold text-[#24251C] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#6C5119] cursor-pointer"
          >
            {EVENT_TYPES.map((t) => (
              <option key={t} value={t}>
                {t === "ALL" ? "All Event Types" : t}
              </option>
            ))}
          </select>
        </div>

        {/* Actor Filter */}
        <div>
          <label className="block text-[11px] font-bold text-[#77735F] uppercase mb-1">
            Actor User ID
          </label>
          <input
            type="text"
            value={actorFilter}
            onChange={(e) => {
              setActorFilter(e.target.value);
              setPage(0);
            }}
            placeholder="e.g. faculty_ml"
            className="w-full px-3 py-2 rounded-xl bg-white border border-[#E4DDCA] text-xs font-medium text-[#24251C] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#6C5119]"
          />
        </div>

        {/* Start Date */}
        <div>
          <label className="block text-[11px] font-bold text-[#77735F] uppercase mb-1">
            From Date
          </label>
          <input
            type="date"
            value={startDate}
            onChange={(e) => {
              setStartDate(e.target.value);
              setPage(0);
            }}
            className="w-full px-3 py-2 rounded-xl bg-white border border-[#E4DDCA] text-xs font-medium text-[#24251C] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#6C5119]"
          />
        </div>

        {/* End Date */}
        <div>
          <label className="block text-[11px] font-bold text-[#77735F] uppercase mb-1">
            To Date
          </label>
          <input
            type="date"
            value={endDate}
            onChange={(e) => {
              setEndDate(e.target.value);
              setPage(0);
            }}
            className="w-full px-3 py-2 rounded-xl bg-white border border-[#E4DDCA] text-xs font-medium text-[#24251C] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#6C5119]"
          />
        </div>
      </div>

      {/* Audit Log Table */}
      <div className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl shadow-2xs overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs sm:text-sm">
            <thead>
              <tr className="border-b border-[#E4DDCA] bg-[#EDE8D8]/40 text-[#77735F] font-semibold text-[11px] uppercase tracking-wider">
                <th className="py-3 px-4">Local Timestamp</th>
                <th className="py-3 px-4">Event Type</th>
                <th className="py-3 px-4">Actor</th>
                <th className="py-3 px-4">Session ID</th>
                <th className="py-3 px-4">Student USN</th>
                <th className="py-3 px-4 text-center">Status Transition</th>
                <th className="py-3 px-4">Audit Reason / Value</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#E4DDCA]/60 text-[#24251C]">
              {isLoading && (
                <tr>
                  <td colSpan={7} className="py-12 text-center text-[#77735F]">
                    <div className="flex flex-col items-center space-y-2">
                      <div className="w-6 h-6 border-2 border-[#6C5119] border-t-transparent rounded-full animate-spin" />
                      <span>Loading institutional audit trail...</span>
                    </div>
                  </td>
                </tr>
              )}

              {!isLoading && logs.length === 0 && (
                <tr>
                  <td colSpan={7} className="py-12 text-center text-[#77735F]">
                    <p className="font-bold text-[#24251C]">No Audit Entries Found</p>
                    <p className="text-xs mt-1">Adjust your filters to inspect recorded events.</p>
                  </td>
                </tr>
              )}

              {!isLoading &&
                logs.map((log) => (
                  <tr key={log.id} className="hover:bg-[#EDE8D8]/20 transition-colors">
                    <td className="py-3 px-4 font-mono text-[11px] text-[#77735F] whitespace-nowrap">
                      {formatLocalTime(log.timestamp)}
                    </td>

                    <td className="py-3 px-4">
                      <span className="px-2 py-0.5 rounded-md text-[10px] font-black bg-[#EDE8D8] text-[#6C5119] border border-[#E4DDCA] font-mono whitespace-nowrap">
                        {log.event_type}
                      </span>
                    </td>

                    <td className="py-3 px-4 font-semibold text-[#24251C]">
                      {log.actor_id}
                    </td>

                    <td className="py-3 px-4 font-mono text-xs text-[#6C5119]">
                      {log.session_id || "—"}
                    </td>

                    <td className="py-3 px-4 font-mono text-xs font-bold text-[#24251C]">
                      {log.usn || "—"}
                    </td>

                    <td className="py-3 px-4 text-center">
                      {log.old_status || log.new_status ? (
                        <div className="inline-flex items-center space-x-1.5 text-[11px]">
                          {log.old_status ? (
                            <span className="px-1.5 py-0.5 rounded bg-rose-50 text-rose-800 font-bold border border-rose-200">
                              {log.old_status}
                            </span>
                          ) : (
                            <span className="text-[#77735F] italic">None</span>
                          )}
                          <span className="text-[#77735F]">→</span>
                          {log.new_status ? (
                            <span className="px-1.5 py-0.5 rounded bg-emerald-50 text-emerald-800 font-bold border border-emerald-200">
                              {log.new_status}
                            </span>
                          ) : (
                            <span className="text-[#77735F] italic">None</span>
                          )}
                        </div>
                      ) : (
                        <span className="text-[#77735F] italic">—</span>
                      )}
                    </td>

                    <td className="py-3 px-4 text-xs text-[#77735F] max-w-xs truncate" title={log.reason || ""}>
                      {log.reason || "—"}
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>

        {/* API-based Pagination Bar */}
        {totalPages > 1 && (
          <div className="p-4 border-t border-[#E4DDCA] flex items-center justify-between text-xs">
            <span className="text-[#77735F]">
              Showing {page * pageSize + 1}–{Math.min((page + 1) * pageSize, total)} of {total} records
            </span>
            <div className="flex items-center space-x-2">
              <button
                type="button"
                onClick={() => setPage((p) => Math.max(0, p - 1))}
                disabled={page === 0}
                className="px-3 py-1.5 rounded-lg bg-white border border-[#E4DDCA] font-semibold text-[#24251C] hover:bg-[#EDE8D8]/50 disabled:opacity-40 cursor-pointer"
              >
                Previous
              </button>
              <span className="font-bold text-[#24251C]">
                Page {page + 1} of {totalPages}
              </span>
              <button
                type="button"
                onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
                disabled={page >= totalPages - 1}
                className="px-3 py-1.5 rounded-lg bg-white border border-[#E4DDCA] font-semibold text-[#24251C] hover:bg-[#EDE8D8]/50 disabled:opacity-40 cursor-pointer"
              >
                Next
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
