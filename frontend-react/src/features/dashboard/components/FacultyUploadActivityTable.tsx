import React, { useMemo, useState } from "react";
import type { VerifiedSession } from "@/types/dashboard";

export interface FacultyActivityItem {
  teacherId: string;
  assignedSubjects: string[];
  sessionCount: number;
  lastUploadTime: string | null;
  lastUploadTimestamp: number;
}

interface FacultyUploadActivityTableProps {
  sessions: VerifiedSession[];
  teacherMappings: Array<{ teacher_id: string; subject_code: string }> | null;
  isLoading?: boolean;
}

export function FacultyUploadActivityTable({
  sessions,
  teacherMappings,
  isLoading = false,
}: FacultyUploadActivityTableProps) {
  const [sortOrder, setSortOrder] = useState<"desc" | "asc">("desc");

  const facultyData = useMemo(() => {
    // Collect all unique faculty IDs
    const facultyMap = new Map<string, { subjects: Set<string>; sessionList: VerifiedSession[] }>();

    // 1. Ingest all teacher mappings from backend (including those with 0 sessions)
    if (teacherMappings && teacherMappings.length > 0) {
      for (const m of teacherMappings) {
        const tid = m.teacher_id.trim();
        if (!facultyMap.has(tid)) {
          facultyMap.set(tid, { subjects: new Set(), sessionList: [] });
        }
        if (m.subject_code) {
          facultyMap.get(tid)!.subjects.add(m.subject_code.trim().toUpperCase());
        }
      }
    }

    // 2. Ingest all sessions and attribute to faculty
    for (const s of sessions) {
      const tid = (s.teacher_id || "unassigned").trim();
      if (!facultyMap.has(tid)) {
        facultyMap.set(tid, { subjects: new Set(), sessionList: [] });
      }
      facultyMap.get(tid)!.sessionList.push(s);
      if (s.subject_code) {
        facultyMap.get(tid)!.subjects.add(s.subject_code.trim().toUpperCase());
      }
    }

    // 3. Format rows
    const rows: FacultyActivityItem[] = [];
    facultyMap.forEach((entry, tid) => {
      // Find latest upload timestamp
      let latestIso: string | null = null;
      let latestTs = 0;

      for (const sess of entry.sessionList) {
        const timeCandidate = sess.created_at || sess.date;
        if (timeCandidate) {
          const ts = new Date(timeCandidate).getTime();
          if (!isNaN(ts) && ts > latestTs) {
            latestTs = ts;
            latestIso = timeCandidate;
          }
        }
      }

      rows.push({
        teacherId: tid,
        assignedSubjects: Array.from(entry.subjects),
        sessionCount: entry.sessionList.length,
        lastUploadTime: latestIso,
        lastUploadTimestamp: latestTs,
      });
    });

    // 4. Sort by last upload time
    rows.sort((a, b) => {
      if (sortOrder === "desc") {
        return b.lastUploadTimestamp - a.lastUploadTimestamp;
      }
      return a.lastUploadTimestamp - b.lastUploadTimestamp;
    });

    return rows;
  }, [sessions, teacherMappings, sortOrder]);

  const formatLastUpload = (isoStr: string | null) => {
    if (!isoStr) return "No uploads recorded";
    try {
      const d = new Date(isoStr);
      if (isNaN(d.getTime())) return isoStr;
      return new Intl.DateTimeFormat("en-GB", {
        day: "2-digit",
        month: "short",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      }).format(d);
    } catch {
      return isoStr;
    }
  };

  return (
    <div className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl p-5 shadow-2xs space-y-4">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-2 border-b border-[#E4DDCA]/60">
        <div>
          <div className="flex items-center space-x-2">
            <h3 className="text-base font-extrabold text-[#24251C]">
              Faculty Upload & Session Activity
            </h3>
            <span className="px-2 py-0.5 rounded-full text-[11px] font-bold bg-[#EDE8D8] text-[#6C5119] border border-[#E4DDCA]">
              {facultyData.length} Faculty
            </span>
          </div>
          <p className="text-xs text-[#77735F] mt-0.5">
            Audit trace of faculty session generation and attendance roster upload activity.
          </p>
        </div>

        <button
          type="button"
          onClick={() => setSortOrder((prev) => (prev === "desc" ? "asc" : "desc"))}
          className="inline-flex items-center space-x-1.5 px-3 py-1.5 rounded-xl bg-white border border-[#E4DDCA] text-xs font-semibold text-[#24251C] hover:bg-[#EDE8D8]/50 transition-colors shadow-2xs self-start sm:self-auto cursor-pointer"
        >
          <svg className="w-3.5 h-3.5 text-[#6C5119]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 16V4m0 0L3 8m4-4l4 4m6 0v12m0 0l4-4m-4 4l-4-4" />
          </svg>
          <span>Sort by Upload Time ({sortOrder === "desc" ? "Newest First" : "Oldest First"})</span>
        </button>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-left text-xs sm:text-sm">
          <thead>
            <tr className="border-b border-[#E4DDCA] bg-[#EDE8D8]/30 text-[#77735F] font-semibold">
              <th className="py-3 px-4">Faculty Member</th>
              <th className="py-3 px-4">Assigned Subjects</th>
              <th className="py-3 px-4 text-center">Sessions Uploaded</th>
              <th className="py-3 px-4 text-right">Last Upload Timestamp</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#E4DDCA]/60 text-[#24251C]">
            {isLoading && (
              <tr>
                <td colSpan={4} className="py-10 text-center text-[#77735F]">
                  <div className="flex flex-col items-center space-y-2">
                    <div className="w-5 h-5 border-2 border-[#6C5119] border-t-transparent rounded-full animate-spin" />
                    <span className="text-xs">Loading faculty upload activity...</span>
                  </div>
                </td>
              </tr>
            )}

            {!isLoading && facultyData.length === 0 && (
              <tr>
                <td colSpan={4} className="py-10 text-center text-[#77735F]">
                  <p className="font-semibold text-xs">No faculty upload activity recorded.</p>
                </td>
              </tr>
            )}

            {!isLoading &&
              facultyData.map((faculty) => {
                const hasUploads = faculty.sessionCount > 0;

                return (
                  <tr key={faculty.teacherId} className="hover:bg-[#EDE8D8]/20 transition-colors">
                    <td className="py-3 px-4">
                      <div className="flex items-center space-x-2.5">
                        <div className="w-7 h-7 rounded-lg bg-[#EDE8D8] text-[#6C5119] font-bold text-xs flex items-center justify-center border border-[#E4DDCA]">
                          {faculty.teacherId.slice(0, 2).toUpperCase()}
                        </div>
                        <div>
                          <span className="font-bold text-[#24251C]">{faculty.teacherId}</span>
                        </div>
                      </div>
                    </td>

                    <td className="py-3 px-4">
                      {faculty.assignedSubjects.length > 0 ? (
                        <div className="flex flex-wrap gap-1">
                          {faculty.assignedSubjects.map((sub) => (
                            <span
                              key={sub}
                              className="px-2 py-0.5 rounded-md text-[11px] font-mono font-semibold bg-[#EDE8D8]/60 text-[#6C5119] border border-[#E4DDCA]"
                            >
                              {sub}
                            </span>
                          ))}
                        </div>
                      ) : (
                        <span className="text-xs text-[#77735F] italic">No active mappings</span>
                      )}
                    </td>

                    <td className="py-3 px-4 text-center">
                      <span
                        className={`inline-block px-2.5 py-0.5 rounded-full text-xs font-bold ${
                          hasUploads
                            ? "bg-emerald-100 text-emerald-800 border border-emerald-300"
                            : "bg-stone-100 text-stone-600 border border-stone-200"
                        }`}
                      >
                        {faculty.sessionCount} {faculty.sessionCount === 1 ? "Session" : "Sessions"}
                      </span>
                    </td>

                    <td className="py-3 px-4 text-right">
                      <span
                        className={`text-xs ${
                          faculty.lastUploadTime
                            ? "font-mono font-medium text-[#24251C]"
                            : "text-[#77735F] italic"
                        }`}
                      >
                        {formatLastUpload(faculty.lastUploadTime)}
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

