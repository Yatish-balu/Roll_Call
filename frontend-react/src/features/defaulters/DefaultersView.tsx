"use client";

import React, { useEffect, useState, useCallback } from "react";
import {
  fetchDefaulters,
  downloadDefaulterPdf,
  type DefaulterStudent,
  type DefaultersResponse,
} from "@/services/api/defaulters";
import { useAuth } from "@/hooks/useAuth";

export function DefaultersView() {
  const { isAdmin } = useAuth();
  const [data, setData] = useState<DefaultersResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filters
  const [selectedBranch, setSelectedBranch] = useState("ALL");
  const [selectedSubject, setSelectedSubject] = useState("ALL");
  const [selectedSemester, setSelectedSemester] = useState("ALL");

  // PDF Export state
  const [isDownloadingPdf, setIsDownloadingPdf] = useState(false);
  const [pdfMessage, setPdfMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);

  const loadDefaulters = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await fetchDefaulters({
        branch: selectedBranch,
        subject: selectedSubject,
        semester: selectedSemester,
      });
      setData(res);
    } catch (err: unknown) {
      if (err instanceof Error) {
        setError(err.message);
      } else {
        setError("Unable to load institutional defaulters list.");
      }
    } finally {
      setIsLoading(false);
    }
  }, [selectedBranch, selectedSubject, selectedSemester]);

  useEffect(() => {
    let isMounted = true;
    Promise.resolve().then(() => {
      if (isMounted) void loadDefaulters();
    });
    return () => {
      isMounted = false;
    };
  }, [loadDefaulters]);

  const handleDownloadPdf = async () => {
    if (!isAdmin) return;
    setIsDownloadingPdf(true);
    setPdfMessage(null);

    try {
      const blob = await downloadDefaulterPdf({
        branch: selectedBranch !== "ALL" ? selectedBranch : undefined,
        subject: selectedSubject !== "ALL" ? selectedSubject : undefined,
      });

      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `RollCall_Defaulter_Notice_${selectedBranch || "Institution"}.pdf`;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);

      setPdfMessage({
        type: "success",
        text: "Official Defaulter Notice PDF generated and downloaded successfully.",
      });
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "PDF export failed.";
      setPdfMessage({
        type: "error",
        text: `Failed to download Defaulter PDF: ${msg}`,
      });
    } finally {
      setIsDownloadingPdf(false);
    }
  };

  const defaulters: DefaulterStudent[] = data?.items || [];
  const threshold = data?.threshold_percent ?? 75.0;

  return (
    <div className="space-y-6">
      {/* Header Bar */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <div className="flex items-center gap-2.5">
            <h1 className="text-2xl font-bold text-[#24251C] tracking-tight">
              Attendance Defaulter Registry
            </h1>
            <span className="px-2.5 py-0.5 rounded-full text-xs font-bold bg-rose-100 text-rose-800 border border-rose-200">
              Cut-off &lt; {threshold}%
            </span>
          </div>
          <p className="text-sm text-[#77735F] mt-0.5">
            Authoritative tracking of students below official university attendance criteria and required class recovery metrics.
          </p>
        </div>

        {/* ADMIN only PDF Download Action */}
        {isAdmin && (
          <button
            onClick={() => void handleDownloadPdf()}
            disabled={isDownloadingPdf}
            className="inline-flex items-center justify-center gap-2 px-4 py-2 bg-[#3F451F] text-[#FBF8F0] text-sm font-semibold rounded-xl hover:bg-[#323719] transition-all shadow-sm disabled:opacity-50 cursor-pointer"
          >
            {isDownloadingPdf ? (
              <>
                <span className="w-4 h-4 border-2 border-[#FBF8F0] border-t-transparent rounded-full animate-spin" />
                <span>Generating Notice Board PDF...</span>
              </>
            ) : (
              <>
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                </svg>
                <span>Download Defaulter PDF</span>
              </>
            )}
          </button>
        )}
      </div>

      {/* Backend Dependency Warning (if applicable) */}
      {data?.is_mock_fallback && data.dependency_message && (
        <div className="p-3.5 bg-amber-50 border border-amber-200 rounded-xl text-xs text-amber-900 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-amber-500 shrink-0" />
            <span className="font-semibold">{data.dependency_message}</span>
          </div>
          <span className="text-[11px] font-bold text-amber-800 bg-amber-100/70 px-2 py-0.5 rounded">
            Dev Mode Sandbox
          </span>
        </div>
      )}

      {/* PDF Status Alert */}
      {pdfMessage && (
        <div
          className={`p-3.5 rounded-xl text-xs font-semibold flex items-center justify-between border ${
            pdfMessage.type === "success"
              ? "bg-emerald-50 text-emerald-800 border-emerald-200"
              : "bg-rose-50 text-rose-800 border-rose-200"
          }`}
        >
          <span>{pdfMessage.text}</span>
          <button
            onClick={() => setPdfMessage(null)}
            className="text-xs hover:underline cursor-pointer"
          >
            Dismiss
          </button>
        </div>
      )}

      {/* Filters Bar */}
      <div className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl p-4 shadow-sm flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold text-[#77735F]">Branch:</span>
          <select
            value={selectedBranch}
            onChange={(e) => setSelectedBranch(e.target.value)}
            className="bg-[#F2EDE0] border border-[#E4DDCA] rounded-xl px-3 py-1.5 text-xs text-[#24251C] focus:outline-none focus:border-[#3F451F]"
          >
            <option value="ALL">All Branches</option>
            <option value="CSE">Computer Science (CSE)</option>
            <option value="AIML">Artificial Intelligence (AIML)</option>
            <option value="CYBER">Cyber Security (CYBER)</option>
            <option value="ECE">Electronics (ECE)</option>
            <option value="ISE">Information Science (ISE)</option>
          </select>
        </div>

        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold text-[#77735F]">Subject:</span>
          <select
            value={selectedSubject}
            onChange={(e) => setSelectedSubject(e.target.value)}
            className="bg-[#F2EDE0] border border-[#E4DDCA] rounded-xl px-3 py-1.5 text-xs text-[#24251C] focus:outline-none focus:border-[#3F451F]"
          >
            <option value="ALL">All Subjects</option>
            <option value="DIST-SYS">DIST-SYS (Distributed Systems)</option>
            <option value="DB-SYS">DB-SYS (Database Systems)</option>
            <option value="ML">ML (Machine Learning)</option>
            <option value="NET-SEC">NET-SEC (Network Security)</option>
            <option value="ES">ES (Embedded Systems)</option>
          </select>
        </div>

        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold text-[#77735F]">Semester:</span>
          <select
            value={selectedSemester}
            onChange={(e) => setSelectedSemester(e.target.value)}
            className="bg-[#F2EDE0] border border-[#E4DDCA] rounded-xl px-3 py-1.5 text-xs text-[#24251C] focus:outline-none focus:border-[#3F451F]"
          >
            <option value="ALL">All Semesters</option>
            <option value="4">Semester 4</option>
            <option value="5">Semester 5</option>
            <option value="6">Semester 6</option>
            <option value="7">Semester 7</option>
          </select>
        </div>

        <button
          onClick={() => {
            setSelectedBranch("ALL");
            setSelectedSubject("ALL");
            setSelectedSemester("ALL");
          }}
          className="ml-auto text-xs text-[#6C5119] font-semibold hover:underline cursor-pointer"
        >
          Reset Filters
        </button>
      </div>

      {/* Main Table Card */}
      <div className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl overflow-hidden shadow-sm">
        <div className="p-4 border-b border-[#E4DDCA] flex items-center justify-between">
          <div>
            <h2 className="text-sm font-bold text-[#24251C] uppercase tracking-wider">
              Identified Defaulters ({defaulters.length})
            </h2>
            <p className="text-xs text-[#77735F]">
              Official Threshold: &lt; {threshold}% • Derived from server-side attendance calculations
            </p>
          </div>
          <button
            onClick={() => void loadDefaulters()}
            className="text-xs font-semibold text-[#6C5119] hover:underline cursor-pointer flex items-center gap-1"
          >
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
            Refresh List
          </button>
        </div>

        {isLoading ? (
          <div className="p-12 text-center text-[#77735F]">
            <div className="inline-block animate-spin w-6 h-6 border-2 border-[#3F451F] border-t-transparent rounded-full mb-2" />
            <p className="text-sm font-medium">Evaluating attendance records against {threshold}% threshold...</p>
          </div>
        ) : error ? (
          <div className="p-10 text-center">
            <p className="text-sm text-rose-600 mb-3">{error}</p>
            <button
              onClick={() => void loadDefaulters()}
              className="px-4 py-1.5 bg-[#3F451F] text-[#FBF8F0] text-xs font-semibold rounded-lg hover:bg-[#323719] cursor-pointer"
            >
              Retry
            </button>
          </div>
        ) : defaulters.length === 0 ? (
          <div className="p-12 text-center text-[#77735F] space-y-2">
            <div className="w-10 h-10 rounded-full bg-emerald-100 text-emerald-800 flex items-center justify-center mx-auto mb-2">
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
              </svg>
            </div>
            <h3 className="text-base font-bold text-[#24251C]">No defaulters</h3>
            <p className="text-xs max-w-sm mx-auto">
              All students currently satisfy the minimum {threshold}% attendance threshold for the selected filters.
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="bg-[#F2EDE0] text-[#77735F] uppercase text-xs border-b border-[#E4DDCA]">
                <tr>
                  <th className="py-3 px-4 font-semibold">USN</th>
                  <th className="py-3 px-4 font-semibold">Student Name</th>
                  <th className="py-3 px-4 font-semibold">Branch</th>
                  <th className="py-3 px-4 font-semibold text-center">Attended / Conducted</th>
                  <th className="py-3 px-4 font-semibold text-center">Attendance %</th>
                  <th className="py-3 px-4 font-semibold text-center">Classes to Recover</th>
                  <th className="py-3 px-4 font-semibold text-right">Academic Standing</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#E4DDCA]/60 text-[#24251C]">
                {defaulters.map((student, idx) => (
                  <tr
                    key={`${student.usn}-${idx}`}
                    className="hover:bg-[#F2EDE0]/50 transition-colors"
                  >
                    <td className="py-3.5 px-4 font-mono font-bold text-[#6C5119]">
                      {student.usn}
                    </td>
                    <td className="py-3.5 px-4 font-semibold text-[#24251C]">
                      {student.student_name}
                    </td>
                    <td className="py-3.5 px-4">
                      <span className="inline-flex items-center px-2 py-0.5 rounded-md text-xs font-semibold bg-[#3F451F]/10 text-[#3F451F]">
                        {student.branch}
                      </span>
                    </td>
                    <td className="py-3.5 px-4 text-center font-mono text-xs">
                      <span className="font-bold text-[#24251C]">{student.attended_classes}</span>
                      <span className="text-[#77735F] mx-1">/</span>
                      <span className="text-[#77735F]">{student.conducted_classes}</span>
                    </td>
                    <td className="py-3.5 px-4 text-center">
                      <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-bold bg-rose-100 text-rose-800 border border-rose-200">
                        {student.attendance_percentage.toFixed(1)}%
                      </span>
                    </td>
                    <td className="py-3.5 px-4 text-center">
                      <span className="inline-flex items-center px-2 py-0.5 rounded-md text-xs font-bold bg-amber-100 text-amber-900 border border-amber-200">
                        +{student.classes_needed_to_recover} classes
                      </span>
                    </td>
                    <td className="py-3.5 px-4 text-right">
                      {/* Visible text badge 'Defaulter', not color alone */}
                      <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-bold bg-rose-50 text-rose-800 border border-rose-200">
                        <span className="w-1.5 h-1.5 rounded-full bg-rose-600" />
                        Defaulter
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

