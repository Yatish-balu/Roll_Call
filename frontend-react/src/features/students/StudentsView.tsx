"use client";

import React, { useEffect, useState, useCallback, useRef } from "react";
import {
  fetchStudents,
  createStudent,
  fetchStudentAttendanceSummary,
  type Student,
  type StudentAttendanceSummary,
} from "@/services/api/students";
import {
  downloadStudentRosterPdf,
  fetchStudentRosterFilters,
} from "@/services/api/reports";
import { useAuth } from "@/hooks/useAuth";

const SEMESTERS = [1, 2, 3, 4, 5, 6, 7, 8];

export function StudentsView() {
  const { canManageStudents } = useAuth();
  const [students, setStudents] = useState<Student[]>([]);
  const [totalCount, setTotalCount] = useState(0);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Search & Filter state
  const [searchQuery, setSearchQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [selectedBranch, setSelectedBranch] = useState("ALL");
  const [selectedSemester, setSelectedSemester] = useState<number | "ALL">("ALL");
  const [branchOptions, setBranchOptions] = useState<string[]>([]);
  const [isExporting, setIsExporting] = useState(false);
  const [exportNotice, setExportNotice] = useState<string | null>(null);
  const [exportError, setExportError] = useState<string | null>(null);

  // Selected Student & Ledger State (F8 - N12)
  const [selectedStudentUsn, setSelectedStudentUsn] = useState<string | null>(null);
  const [ledgerSummary, setLedgerSummary] = useState<StudentAttendanceSummary | null>(null);
  const [isLedgerLoading, setIsLedgerLoading] = useState(false);
  const [ledgerError, setLedgerError] = useState<string | null>(null);

  // Add Student Modal state (Admin only)
  const [isAddModalOpen, setIsAddModalOpen] = useState(false);
  const [newUsn, setNewUsn] = useState("");
  const [newName, setNewName] = useState("");
  const [newBranch, setNewBranch] = useState("CSE");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  // 300ms Search Debounce
  const debounceTimerRef = useRef<NodeJS.Timeout | null>(null);

  const handleSearchChange = (val: string) => {
    setSearchQuery(val);
    if (debounceTimerRef.current) clearTimeout(debounceTimerRef.current);
    debounceTimerRef.current = setTimeout(() => {
      setDebouncedQuery(val.trim());
    }, 300);
  };

  useEffect(() => {
    return () => {
      if (debounceTimerRef.current) clearTimeout(debounceTimerRef.current);
    };
  }, []);

  const loadStudents = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await fetchStudents({
        limit: 100,
        branch: selectedBranch !== "ALL" ? selectedBranch : undefined,
        semester: selectedSemester !== "ALL" ? selectedSemester : undefined,
        search: debouncedQuery || undefined,
      });
      setStudents(res.items || []);
      setTotalCount(res.total || 0);
    } catch (err: unknown) {
      if (err instanceof Error) {
        setError(err.message);
      } else {
        setError("Unable to load student directory from server.");
      }
    } finally {
      setIsLoading(false);
    }
  }, [selectedBranch, selectedSemester, debouncedQuery]);

  // Branch options come from the backend (authorised roster), never hardcoded.
  useEffect(() => {
    let isMounted = true;
    fetchStudentRosterFilters()
      .then((filters) => {
        if (!isMounted) return;
        setBranchOptions(filters.branches || []);
      })
      .catch(() => {
        if (isMounted) setBranchOptions([]);
      });
    return () => {
      isMounted = false;
    };
  }, []);

  const handleExportPdf = async () => {
    setIsExporting(true);
    setExportNotice(null);
    setExportError(null);
    try {
      const blob = await downloadStudentRosterPdf({
        branch: selectedBranch !== "ALL" ? selectedBranch : undefined,
        semester: selectedSemester !== "ALL" ? selectedSemester : undefined,
        title: "RollCall AI Student Roster",
      });
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      const suffix = [
        selectedBranch !== "ALL" ? selectedBranch : "all-branches",
        selectedSemester !== "ALL" ? `sem-${selectedSemester}` : "all-semesters",
      ].join("_");
      link.download = `student_roster_${suffix}.pdf`;
      document.body.appendChild(link);
      link.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(link);
      setExportNotice(
        `The backend generated the PDF with the selected filters applied (${totalCount} student(s)).`
      );
    } catch (err: unknown) {
      setExportError(
        err instanceof Error
          ? err.message
          : "The student roster PDF could not be generated."
      );
    } finally {
      setIsExporting(false);
    }
  };

  const clearFilters = () => {
    setSelectedBranch("ALL");
    setSelectedSemester("ALL");
    setSearchQuery("");
    setDebouncedQuery("");
  };

  useEffect(() => {
    let isMounted = true;
    Promise.resolve().then(() => {
      if (isMounted) void loadStudents();
    });
    return () => {
      isMounted = false;
    };
  }, [loadStudents]);

  // Load Individual Student Ledger (F8 - N12)
  const handleSelectStudent = async (usn: string) => {
    setSelectedStudentUsn(usn);
    setIsLedgerLoading(true);
    setLedgerError(null);
    setLedgerSummary(null);

    try {
      const summary = await fetchStudentAttendanceSummary(usn);
      setLedgerSummary(summary);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to load student attendance history.";
      setLedgerError(msg);
    } finally {
      setIsLedgerLoading(false);
    }
  };

  const handleAddSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!canManageStudents) {
      setFormError("Only administrators are permitted to register students.");
      return;
    }
    if (!newUsn.trim() || !newName.trim()) {
      setFormError("Please fill out both USN and Student Name.");
      return;
    }
    setIsSubmitting(true);
    setFormError(null);

    try {
      const created = await createStudent({
        usn: newUsn.trim().toUpperCase(),
        name: newName.trim(),
        branch: newBranch.trim(),
      });
      setStudents((prev) => [created, ...prev]);
      setTotalCount((prev) => prev + 1);
      setIsAddModalOpen(false);
      setNewUsn("");
      setNewName("");
    } catch (err: unknown) {
      if (err instanceof Error) {
        setFormError(err.message);
      } else {
        setFormError("Failed to register student record.");
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Header Bar */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-[#24251C] tracking-tight">
            Student Directory & Attendance Ledger
          </h1>
          <p className="text-sm text-[#77735F] mt-0.5">
            Search verified institutional student roster, inspect individual attendance records, and audit standing.
          </p>
        </div>

        {canManageStudents && (
          <button
            onClick={() => setIsAddModalOpen(true)}
            className="inline-flex items-center justify-center gap-2 px-4 py-2 bg-[#3F451F] text-[#FBF8F0] text-sm font-semibold rounded-xl hover:bg-[#323719] transition-all shadow-sm cursor-pointer"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 4v16m8-8H4" />
            </svg>
            Register Student
          </button>
        )}
      </div>

      {/* Search & Filter Bar (300ms Debounce) */}
      <div className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl p-4 shadow-sm flex flex-col sm:flex-row items-center gap-3">
        <div className="relative flex-1 w-full">
          <svg
            className="w-4 h-4 absolute left-3.5 top-1/2 -translate-y-1/2 text-[#77735F]"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth="2"
              d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
            />
          </svg>
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => handleSearchChange(e.target.value)}
            placeholder="Search by student name or roll number / USN (e.g. 1MS21CS001)..."
            className="w-full pl-10 pr-4 py-2 bg-[#F2EDE0] border border-[#E4DDCA] rounded-xl text-xs sm:text-sm text-[#24251C] placeholder-[#77735F] focus:outline-none focus:border-[#3F451F]"
          />
        </div>

        <div className="flex flex-wrap items-center gap-2 w-full sm:w-auto">
          <span className="text-xs font-semibold text-[#77735F]">Branch:</span>
          <select
            value={selectedBranch}
            onChange={(e) => setSelectedBranch(e.target.value)}
            className="flex-1 sm:flex-none bg-[#F2EDE0] border border-[#E4DDCA] rounded-xl px-3 py-2 text-xs text-[#24251C] focus:outline-none focus:border-[#3F451F] cursor-pointer"
          >
            <option value="ALL">All Branches</option>
            {branchOptions.map((branch) => (
              <option key={branch} value={branch}>
                {branch}
              </option>
            ))}
          </select>

          <span className="text-xs font-semibold text-[#77735F]">Semester:</span>
          <select
            value={String(selectedSemester)}
            onChange={(e) =>
              setSelectedSemester(
                e.target.value === "ALL" ? "ALL" : Number(e.target.value)
              )
            }
            className="flex-1 sm:flex-none bg-[#F2EDE0] border border-[#E4DDCA] rounded-xl px-3 py-2 text-xs text-[#24251C] focus:outline-none focus:border-[#3F451F] cursor-pointer"
          >
            <option value="ALL">All Semesters</option>
            {SEMESTERS.map((semester) => (
              <option key={semester} value={semester}>
                Semester {semester}
              </option>
            ))}
          </select>

          <button
            type="button"
            onClick={clearFilters}
            className="px-3 py-2 rounded-xl border border-[#E4DDCA] bg-white text-xs font-semibold text-[#77735F] hover:bg-[#EDE8D8]/60 transition-colors cursor-pointer"
          >
            Clear filters
          </button>

          <button
            type="button"
            onClick={() => void handleExportPdf()}
            disabled={isExporting}
            className="inline-flex items-center gap-2 px-3.5 py-2 rounded-xl bg-[#6C5119] text-white text-xs font-bold hover:bg-[#594214] transition-colors disabled:opacity-50 cursor-pointer"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M12 10v6m0 0l-3-3m3 3l3-3M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z"
              />
            </svg>
            {isExporting ? "Generating…" : "Export PDF"}
          </button>
        </div>
      </div>

      {/* Export feedback */}
      {exportNotice && (
        <div className="p-3.5 bg-emerald-50 border border-emerald-200 rounded-xl text-xs text-emerald-800">
          {exportNotice}
        </div>
      )}
      {exportError && (
        <div className="p-3.5 bg-rose-50 border border-rose-200 rounded-xl text-xs text-rose-800">
          {exportError}
        </div>
      )}

      {/* Main Student Directory Table */}
      <div className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl overflow-hidden shadow-sm">
        <div className="p-4 border-b border-[#E4DDCA] flex items-center justify-between">
          <h2 className="text-sm font-bold text-[#24251C] uppercase tracking-wider">
            Enrolled Students ({totalCount})
          </h2>
          <span className="text-xs text-[#77735F]">
            Click any student to view chronological attendance ledger
          </span>
        </div>

        {isLoading ? (
          <div className="p-12 text-center text-[#77735F]">
            <div className="inline-block animate-spin w-6 h-6 border-2 border-[#3F451F] border-t-transparent rounded-full mb-2" />
            <p className="text-sm font-medium">Loading student records...</p>
          </div>
        ) : error ? (
          <div className="p-10 text-center">
            <p className="text-sm text-rose-600 mb-3">{error}</p>
            <button
              onClick={() => void loadStudents()}
              className="px-4 py-1.5 bg-[#3F451F] text-[#FBF8F0] text-xs font-semibold rounded-lg hover:bg-[#323719] cursor-pointer"
            >
              Retry
            </button>
          </div>
        ) : students.length === 0 ? (
          <div className="p-12 text-center text-[#77735F] space-y-1">
            <p className="text-sm font-bold text-[#24251C]">No student found</p>
            <p className="text-xs">
              {debouncedQuery
                ? `No student matching "${debouncedQuery}" in the selected branch.`
                : "No students registered in this branch category."}
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="bg-[#F2EDE0] text-[#77735F] uppercase text-xs border-b border-[#E4DDCA]">
                <tr>
                  <th className="py-3 px-4 font-semibold">USN</th>
                  <th className="py-3 px-4 font-semibold">Student Name</th>
                  <th className="py-3 px-4 font-semibold">Department</th>
                  <th className="py-3 px-4 font-semibold">Semester / Batch</th>
                  <th className="py-3 px-4 font-semibold text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#E4DDCA]/60 text-[#24251C]">
                {students.map((student) => (
                  <tr
                    key={student.usn}
                    onClick={() => void handleSelectStudent(student.usn)}
                    className="hover:bg-[#F2EDE0]/60 transition-colors cursor-pointer group"
                  >
                    <td className="py-3.5 px-4 font-mono font-bold text-[#6C5119]">
                      {student.usn}
                    </td>
                    <td className="py-3.5 px-4 font-semibold text-[#24251C] group-hover:text-[#3F451F]">
                      {student.name}
                    </td>
                    <td className="py-3.5 px-4">
                      <span className="inline-flex items-center px-2 py-0.5 rounded-md text-xs font-semibold bg-[#3F451F]/10 text-[#3F451F]">
                        {student.branch}
                      </span>
                    </td>
                    <td className="py-3.5 px-4 text-xs text-[#77735F]">
                      {student.semester
                        ? `Semester ${student.semester}`
                        : "Semester not assigned"}
                      {student.section ? ` • ${student.section}` : ""}
                      {student.batch ? ` (${student.batch})` : ""}
                    </td>
                    <td className="py-3.5 px-4 text-right">
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          void handleSelectStudent(student.usn);
                        }}
                        className="inline-flex items-center gap-1 px-3 py-1 text-xs font-semibold rounded-lg bg-[#3F451F]/10 text-[#3F451F] hover:bg-[#3F451F] hover:text-[#FBF8F0] transition-colors cursor-pointer"
                      >
                        View Ledger
                        <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                        </svg>
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Individual Student Attendance Ledger Modal (F8 - N12) */}
      {selectedStudentUsn && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40 backdrop-blur-xs">
          <div className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl p-6 max-w-2xl w-full shadow-2xl max-h-[90vh] flex flex-col space-y-4">
            {/* Modal Header */}
            <div className="flex items-center justify-between pb-3 border-b border-[#E4DDCA]">
              <div>
                <h3 className="text-lg font-bold text-[#24251C]">
                  Individual Attendance Ledger
                </h3>
                <p className="text-xs text-[#77735F]">
                  USN: <span className="font-mono font-bold text-[#6C5119]">{selectedStudentUsn}</span>
                </p>
              </div>
              <button
                onClick={() => setSelectedStudentUsn(null)}
                className="text-[#77735F] hover:text-[#24251C] text-sm font-bold p-1 cursor-pointer"
              >
                ✕
              </button>
            </div>

            {/* Modal Body */}
            <div className="flex-1 overflow-y-auto space-y-4 pr-1">
              {isLedgerLoading ? (
                <div className="p-12 text-center text-[#77735F]">
                  <div className="inline-block animate-spin w-6 h-6 border-2 border-[#3F451F] border-t-transparent rounded-full mb-2" />
                  <p className="text-xs font-medium">Fetching verified attendance ledger from server...</p>
                </div>
              ) : ledgerError ? (
                <div className="p-6 text-center text-rose-700 bg-rose-50 border border-rose-200 rounded-xl text-xs">
                  {ledgerError}
                </div>
              ) : ledgerSummary ? (
                <>
                  {/* Student Details Card */}
                  <div className="bg-[#F2EDE0] border border-[#E4DDCA] rounded-xl p-4 grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
                    <div>
                      <span className="text-[#77735F] block">Student Name</span>
                      {/* Safely escaped text, no raw HTML */}
                      <span className="font-bold text-[#24251C] text-sm block">
                        {ledgerSummary.student.name}
                      </span>
                    </div>
                    <div>
                      <span className="text-[#77735F] block">Department</span>
                      <span className="font-semibold text-[#24251C] block">
                        {ledgerSummary.student.branch}
                      </span>
                    </div>
                    <div>
                      <span className="text-[#77735F] block">Attendance %</span>
                      <span className="font-mono font-bold text-[#24251C] text-sm block">
                        {ledgerSummary.attendance_percentage.toFixed(1)}%
                      </span>
                    </div>
                    <div>
                      <span className="text-[#77735F] block">Standing Band</span>
                      {/* Health Band Presentation: Green >85%, Yellow 70-85%, Red <70% */}
                      <span
                        className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full font-bold text-[11px] mt-0.5 border ${
                          ledgerSummary.health_band === "GREEN"
                            ? "bg-emerald-100 text-emerald-800 border-emerald-300"
                            : ledgerSummary.health_band === "YELLOW"
                            ? "bg-amber-100 text-amber-900 border-amber-300"
                            : "bg-rose-100 text-rose-800 border-rose-300"
                        }`}
                      >
                        <span
                          className={`w-1.5 h-1.5 rounded-full ${
                            ledgerSummary.health_band === "GREEN"
                              ? "bg-emerald-600"
                              : ledgerSummary.health_band === "YELLOW"
                              ? "bg-amber-600"
                              : "bg-rose-600"
                          }`}
                        />
                        {ledgerSummary.health_band_label}
                      </span>
                    </div>
                  </div>

                  {/* Attendance Ledger Table */}
                  <div>
                    <h4 className="text-xs font-bold text-[#24251C] uppercase tracking-wider mb-2">
                      Chronological Attendance History ({ledgerSummary.ledger.length} sessions)
                    </h4>

                    {ledgerSummary.ledger.length === 0 ? (
                      <div className="p-8 text-center text-[#77735F] bg-white rounded-xl border border-[#E4DDCA]">
                        <p className="text-xs">No attendance marks recorded for this student yet.</p>
                      </div>
                    ) : (
                      <div className="overflow-x-auto border border-[#E4DDCA] rounded-xl bg-white">
                        <table className="w-full text-left text-xs">
                          <thead className="bg-[#F2EDE0] text-[#77735F] uppercase text-[10px] border-b border-[#E4DDCA]">
                            <tr>
                              <th className="py-2.5 px-3">Date</th>
                              <th className="py-2.5 px-3">Subject</th>
                              <th className="py-2.5 px-3">Room</th>
                              <th className="py-2.5 px-3 text-center">Status</th>
                              <th className="py-2.5 px-3 text-right">Source</th>
                            </tr>
                          </thead>
                          <tbody className="divide-y divide-[#E4DDCA]/50 text-[#24251C]">
                            {ledgerSummary.ledger.map((entry, idx) => (
                              <tr key={`${entry.session_id}-${idx}`} className="hover:bg-[#F2EDE0]/30">
                                <td className="py-2.5 px-3 font-mono font-semibold text-[#3F451F]">
                                  {entry.date}
                                </td>
                                <td className="py-2.5 px-3 font-medium">
                                  {entry.subject}
                                </td>
                                <td className="py-2.5 px-3 font-mono text-[#77735F]">
                                  {entry.room}
                                </td>
                                <td className="py-2.5 px-3 text-center">
                                  <span
                                    className={`inline-flex items-center px-2 py-0.5 rounded text-[10px] font-bold ${
                                      entry.status === "PRESENT"
                                        ? "bg-emerald-100 text-emerald-800 border border-emerald-200"
                                        : entry.status === "ABSENT"
                                        ? "bg-rose-100 text-rose-800 border border-rose-200"
                                        : "bg-amber-100 text-amber-800 border border-amber-200"
                                    }`}
                                  >
                                    {entry.status}
                                  </span>
                                </td>
                                <td className="py-2.5 px-3 text-right font-mono text-[10px] text-[#77735F]">
                                  {entry.source}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </div>
                </>
              ) : null}
            </div>

            {/* Modal Footer */}
            <div className="pt-2 flex justify-end border-t border-[#E4DDCA]">
              <button
                onClick={() => setSelectedStudentUsn(null)}
                className="px-4 py-2 rounded-xl bg-[#EDE8D8] text-[#24251C] hover:bg-[#E4DDCA] font-bold text-xs transition-colors cursor-pointer"
              >
                Close Ledger
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Add Student Modal (Admin only) */}
      {isAddModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40 backdrop-blur-xs">
          <div className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl p-6 max-w-md w-full shadow-xl space-y-4">
            <div className="flex items-center justify-between pb-2 border-b border-[#E4DDCA]">
              <h3 className="text-base font-bold text-[#24251C]">Register New Student</h3>
              <button
                onClick={() => setIsAddModalOpen(false)}
                className="text-[#77735F] hover:text-[#24251C] text-sm font-bold cursor-pointer"
              >
                ✕
              </button>
            </div>

            {formError && (
              <div className="p-3 rounded-xl bg-rose-50 border border-rose-200 text-rose-800 text-xs">
                {formError}
              </div>
            )}

            <form onSubmit={handleAddSubmit} className="space-y-4 text-xs sm:text-sm">
              <div>
                <label className="block font-semibold text-[#24251C] mb-1">
                  Unique Student Number (USN) *
                </label>
                <input
                  type="text"
                  value={newUsn}
                  onChange={(e) => setNewUsn(e.target.value)}
                  placeholder="e.g. 1RV21CS042"
                  required
                  className="w-full px-3.5 py-2 rounded-xl bg-white border border-[#E4DDCA] text-[#24251C] uppercase focus:outline-none focus:border-[#3F451F]"
                />
              </div>

              <div>
                <label className="block font-semibold text-[#24251C] mb-1">
                  Student Full Name *
                </label>
                <input
                  type="text"
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  placeholder="e.g. Ananya Sharma"
                  required
                  className="w-full px-3.5 py-2 rounded-xl bg-white border border-[#E4DDCA] text-[#24251C] focus:outline-none focus:border-[#3F451F]"
                />
              </div>

              <div>
                <label className="block font-semibold text-[#24251C] mb-1">
                  Department / Branch *
                </label>
                {branchOptions.length > 0 ? (
                  <select
                    value={newBranch}
                    onChange={(e) => setNewBranch(e.target.value)}
                    className="w-full px-3.5 py-2 rounded-xl bg-white border border-[#E4DDCA] text-[#24251C] focus:outline-none focus:ring-2 focus:ring-[#3F451F] cursor-pointer"
                  >
                    {branchOptions.map((branch) => (
                      <option key={branch} value={branch}>
                        {branch}
                      </option>
                    ))}
                  </select>
                ) : (
                  <input
                    type="text"
                    value={newBranch}
                    onChange={(e) => setNewBranch(e.target.value.toUpperCase())}
                    placeholder="e.g. CSE"
                    className="w-full px-3.5 py-2 rounded-xl bg-white border border-[#E4DDCA] text-[#24251C] uppercase focus:outline-none focus:ring-2 focus:ring-[#3F451F]"
                  />
                )}
              </div>

              <div className="pt-2 flex justify-end space-x-2">
                <button
                  type="button"
                  onClick={() => setIsAddModalOpen(false)}
                  className="px-4 py-2 rounded-xl bg-[#EDE8D8] text-[#24251C] hover:bg-[#E4DDCA] font-semibold text-xs transition-colors cursor-pointer"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isSubmitting}
                  className="px-4 py-2 rounded-xl bg-[#3F451F] hover:bg-[#343919] text-[#FBF8F0] font-bold text-xs shadow-2xs transition-colors disabled:opacity-50 cursor-pointer"
                >
                  {isSubmitting ? "Registering..." : "Save Student"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
