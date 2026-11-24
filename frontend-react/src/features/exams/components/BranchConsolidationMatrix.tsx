"use client";

import React, { useState, useMemo } from "react";
import {
  type BranchConsolidationReport,
  type ExamHeaderInfo,
  type StudentExamAttendanceRow,
} from "@/services/api/exams";

interface Props {
  branches: BranchConsolidationReport[];
  seriesTitle?: string;
  semester?: number;
  isLoading?: boolean;
}

export function BranchConsolidationMatrix({
  branches,
  seriesTitle = "Continuous Internal Assessment (CIE) Series",
  semester = 7,
  isLoading = false,
}: Props) {
  const [selectedBranch, setSelectedBranch] = useState<string>("ALL");
  const [searchQuery, setSearchQuery] = useState("");
  const [filterMode, setFilterMode] = useState<"ALL" | "PERFECT" | "ABSENT">("ALL");

  // Determine active branch data
  const activeBranchData = useMemo(() => {
    if (branches.length === 0) return null;
    if (selectedBranch === "ALL") {
      // Aggregate all branches
      const allStudents: StudentExamAttendanceRow[] = [];
      const examMap = new Map<string, ExamHeaderInfo>();

      branches.forEach((b) => {
        allStudents.push(...b.students);
        b.exams.forEach((ex) => {
          if (!examMap.has(ex.subject_code)) {
            examMap.set(ex.subject_code, ex);
          }
        });
      });

      const uniqueExams = Array.from(examMap.values()).sort((a, b) =>
        a.date.localeCompare(b.date) || a.start_time.localeCompare(b.start_time)
      );

      const perfectCount = allStudents.filter((s) => s.exams_absent === 0).length;
      const totalWritten = allStudents.reduce((acc, s) => acc + s.exams_written, 0);
      const totalPossible = allStudents.reduce((acc, s) => acc + s.total_exams, 0);
      const overallPct =
        totalPossible > 0 ? Math.round((totalWritten / totalPossible) * 1000) / 10 : 0;

      return {
        branch: "ALL",
        branch_name: "All Enrolled Engineering Branches",
        total_students: allStudents.length,
        total_exams: uniqueExams.length,
        overall_attendance_pct: overallPct,
        perfect_attendance_count: perfectCount,
        partial_attendance_count: allStudents.length - perfectCount,
        exams: uniqueExams,
        students: allStudents,
      };
    }

    return branches.find((b) => b.branch === selectedBranch) || branches[0] || null;
  }, [branches, selectedBranch]);

  // Filtered students according to search and status filter
  const filteredStudents = useMemo(() => {
    if (!activeBranchData) return [];
    let list = activeBranchData.students;

    if (filterMode === "PERFECT") {
      list = list.filter((s) => s.exams_absent === 0);
    } else if (filterMode === "ABSENT") {
      list = list.filter((s) => s.exams_absent > 0);
    }

    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase().trim();
      list = list.filter(
        (s) =>
          s.usn.toLowerCase().includes(q) ||
          s.name.toLowerCase().includes(q) ||
          s.branch.toLowerCase().includes(q) ||
          s.missed_subjects.some((sub) => sub.toLowerCase().includes(q))
      );
    }

    return list;
  }, [activeBranchData, filterMode, searchQuery]);

  // Export to CSV function
  const handleExportCSV = () => {
    if (!activeBranchData || activeBranchData.students.length === 0) return;

    const headers = [
      "Sl No",
      "USN",
      "Student Name",
      "Branch",
      ...activeBranchData.exams.map((ex) => `${ex.subject_code} (${ex.date} ${ex.slot || ""})`),
      "Exams Written",
      "Total Exams",
      "Attendance %",
      "Missed Subjects",
    ];

    const rows = activeBranchData.students.map((s, idx) => [
      idx + 1,
      `"${s.usn}"`,
      `"${s.name}"`,
      s.branch,
      ...activeBranchData.exams.map((ex) => `"${s.exam_status[ex.subject_code] || "ABSENT"}"`),
      s.exams_written,
      s.total_exams,
      `${s.attendance_pct}%`,
      `"${s.missed_subjects.join(", ") || "None"}"`,
    ]);

    const csvContent = [headers.join(","), ...rows.map((r) => r.join(","))].join("\n");
    const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.setAttribute(
      "download",
      `CIE_Attendance_Consolidation_${selectedBranch}_Sem${semester}.csv`
    );
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  if (isLoading) {
    return (
      <div className="bg-white rounded-2xl border border-gray-200/80 p-8 text-center text-gray-500 shadow-sm">
        <div className="animate-spin inline-block w-8 h-8 border-4 border-current border-t-transparent text-[#3F451F] rounded-full mb-3" />
        <p className="text-sm font-medium">Consolidating branch-wise CIE attendance data...</p>
      </div>
    );
  }

  if (branches.length === 0) {
    return (
      <div className="bg-white rounded-2xl border border-gray-200/80 p-8 text-center text-gray-500 shadow-sm">
        <p className="text-base font-bold text-gray-800 mb-1">No Multi-Exam Data Available</p>
        <p className="text-xs text-gray-500">
          No scheduled CIE examination seatings found for Semester {semester}. Ensure examinations are created and Form-B rosters uploaded.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Top Header Card */}
      <div className="bg-white rounded-2xl border border-gray-200/80 p-5 shadow-sm">
        <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <span className="px-2.5 py-0.5 rounded-full text-xs font-bold bg-[#3F451F] text-white">
                Semester {semester} CIE
              </span>
              <span className="text-xs font-medium text-gray-500">
                Official Multi-Exam College Attendance Consolidation
              </span>
            </div>
            <h3 className="text-lg font-bold text-gray-900 mt-1">{seriesTitle}</h3>
            <p className="text-xs text-gray-600 mt-0.5">
              Unified cross-subject tracking: verifies exactly which subjects each student wrote across the entire CIE series.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={handleExportCSV}
              className="inline-flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-bold bg-[#3F451F] text-white shadow-sm hover:bg-[#343919] transition-all"
            >
              <span>📥</span>
              <span>Export Consolidation CSV</span>
            </button>
          </div>
        </div>

        {/* Branch Selector Tabs */}
        <div className="mt-5 border-t border-gray-100 pt-4 flex flex-wrap items-center gap-2">
          <span className="text-xs font-bold text-gray-500 mr-1">Select Branch:</span>
          <button
            type="button"
            onClick={() => setSelectedBranch("ALL")}
            className={`px-3 py-1.5 rounded-xl text-xs font-bold transition-all ${
              selectedBranch === "ALL"
                ? "bg-[#3F451F] text-white shadow-sm"
                : "bg-gray-100 text-gray-700 hover:bg-gray-200"
            }`}
          >
            All Branches ({branches.reduce((acc, b) => acc + b.total_students, 0)})
          </button>
          {branches.map((b) => (
            <button
              key={b.branch}
              type="button"
              onClick={() => setSelectedBranch(b.branch)}
              className={`px-3 py-1.5 rounded-xl text-xs font-bold transition-all ${
                selectedBranch === b.branch
                  ? "bg-[#3F451F] text-white shadow-sm"
                  : "bg-gray-100 text-gray-700 hover:bg-gray-200"
              }`}
            >
              {b.branch} · {b.branch_name ? b.branch_name.split("(")[0].trim() : b.branch} ({b.total_students})
            </button>
          ))}
        </div>
      </div>

      {activeBranchData && (
        <>
          {/* Branch Key Performance Stats */}
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
            <div className="bg-white rounded-2xl border border-gray-200/80 p-4 shadow-sm">
              <span className="text-xs text-gray-500 font-medium">Total Registered</span>
              <p className="text-2xl font-black text-gray-900 mt-1">{activeBranchData.total_students}</p>
              <span className="text-[11px] text-gray-400">Enrolled Candidates</span>
            </div>

            <div className="bg-white rounded-2xl border border-gray-200/80 p-4 shadow-sm">
              <span className="text-xs text-gray-500 font-medium">Exams in Series</span>
              <p className="text-2xl font-black text-gray-900 mt-1">{activeBranchData.total_exams}</p>
              <span className="text-[11px] text-gray-400">Scheduled Subjects</span>
            </div>

            <div className="bg-white rounded-2xl border border-gray-200/80 p-4 shadow-sm">
              <span className="text-xs text-gray-500 font-medium">Overall Attendance</span>
              <p className="text-2xl font-black text-emerald-700 mt-1">
                {activeBranchData.overall_attendance_pct}%
              </p>
              <span className="text-[11px] text-emerald-600 font-medium">Across all exam sittings</span>
            </div>

            <div className="bg-white rounded-2xl border border-gray-200/80 p-4 shadow-sm">
              <span className="text-xs text-gray-500 font-medium">Wrote All Exams</span>
              <p className="text-2xl font-black text-emerald-800 mt-1">
                {activeBranchData.perfect_attendance_count}
              </p>
              <span className="text-[11px] text-emerald-700">100% CIE attendance</span>
            </div>

            <div className="bg-white rounded-2xl border border-gray-200/80 p-4 shadow-sm">
              <span className="text-xs text-gray-500 font-medium">Missed 1+ Exams</span>
              <p className="text-2xl font-black text-amber-700 mt-1">
                {activeBranchData.partial_attendance_count}
              </p>
              <span className="text-[11px] text-amber-600 font-medium">Absent for ≥ 1 subject</span>
            </div>
          </div>

          {/* Scheduled Subject Columns Overview Bar */}
          <div className="bg-[#EDE8D8]/50 border border-[#3F451F]/15 rounded-2xl p-4 shadow-sm">
            <div className="flex items-center justify-between mb-2">
              <h4 className="text-xs font-bold text-gray-900 uppercase tracking-wider">
                Scheduled CIE Subjects & Dates:
              </h4>
              <span className="text-[11px] text-gray-600">
                {activeBranchData.exams.length} Distinct Subjects
              </span>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-2.5">
              {activeBranchData.exams.map((ex, idx) => (
                <div
                  key={ex.subject_code}
                  className="bg-white rounded-xl border border-gray-200 p-3 shadow-xs flex flex-col justify-between"
                >
                  <div>
                    <div className="flex items-center justify-between">
                      <span className="px-2 py-0.5 rounded text-[10px] font-black bg-[#3F451F] text-white">
                        {ex.subject_code}
                      </span>
                      <span className="text-[10px] font-bold text-gray-500 uppercase">
                        {ex.slot || (idx % 2 === 0 ? "FN" : "AN")}
                      </span>
                    </div>
                    <p className="text-xs font-bold text-gray-900 mt-1 line-clamp-1" title={ex.subject_name}>
                      {ex.subject_name || ex.subject_code}
                    </p>
                    <p className="text-[11px] text-gray-500 font-mono mt-0.5">📅 {ex.date}</p>
                  </div>

                  <div className="mt-2 pt-2 border-t border-gray-100 flex items-center justify-between text-[11px]">
                    <span className="text-gray-600">Turnout:</span>
                    <span className="font-bold text-emerald-700">
                      {ex.total_present}/{ex.total_registered} ({ex.attendance_pct}%)
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Search & Filter Toolbar */}
          <div className="bg-white rounded-2xl border border-gray-200/80 p-4 shadow-sm flex flex-col sm:flex-row items-center justify-between gap-3">
            <div className="w-full sm:w-72">
              <input
                type="text"
                placeholder="Search by USN or Name..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full px-3 py-2 rounded-xl text-xs border border-gray-300 bg-white shadow-xs focus:border-[#3F451F] focus:outline-none"
              />
            </div>

            <div className="flex items-center gap-1.5 w-full sm:w-auto overflow-x-auto">
              <button
                type="button"
                onClick={() => setFilterMode("ALL")}
                className={`px-3 py-1.5 rounded-xl text-xs font-bold transition-all ${
                  filterMode === "ALL"
                    ? "bg-[#3F451F] text-white shadow-xs"
                    : "bg-gray-100 text-gray-700 hover:bg-gray-200"
                }`}
              >
                All ({activeBranchData.students.length})
              </button>
              <button
                type="button"
                onClick={() => setFilterMode("PERFECT")}
                className={`px-3 py-1.5 rounded-xl text-xs font-bold transition-all ${
                  filterMode === "PERFECT"
                    ? "bg-emerald-700 text-white shadow-xs"
                    : "bg-emerald-50 text-emerald-800 hover:bg-emerald-100"
                }`}
              >
                ✓ Wrote All ({activeBranchData.perfect_attendance_count})
              </button>
              <button
                type="button"
                onClick={() => setFilterMode("ABSENT")}
                className={`px-3 py-1.5 rounded-xl text-xs font-bold transition-all ${
                  filterMode === "ABSENT"
                    ? "bg-amber-700 text-white shadow-xs"
                    : "bg-amber-50 text-amber-800 hover:bg-amber-100"
                }`}
              >
                ⚠️ Missed Any ({activeBranchData.partial_attendance_count})
              </button>
            </div>
          </div>

          {/* Master Student Multi-Subject Attendance Matrix */}
          <div className="bg-white rounded-2xl border border-gray-200/80 shadow-sm overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="bg-gray-50 border-b border-gray-200 text-gray-700 uppercase font-semibold">
                  <tr>
                    <th className="px-3 py-3 w-10 text-center font-mono">#</th>
                    <th className="px-3 py-3 font-mono">USN</th>
                    <th className="px-4 py-3 min-w-[160px]">Student Name</th>
                    <th className="px-3 py-3 w-16 text-center">Branch</th>
                    {/* Dynamic Exam Columns */}
                    {activeBranchData.exams.map((ex) => (
                      <th
                        key={ex.subject_code}
                        className="px-3 py-3 text-center min-w-[110px] bg-gray-100/50 border-l border-gray-200"
                      >
                        <div className="font-bold text-gray-900">{ex.subject_code}</div>
                        <div className="text-[10px] font-normal text-gray-500 font-mono lowercase">
                          {ex.date}
                        </div>
                      </th>
                    ))}
                    {/* The Critical "Exams Written" Column requested by User */}
                    <th className="px-4 py-3 text-center min-w-[130px] bg-emerald-50/70 border-l border-emerald-200 font-bold text-emerald-950">
                      Exams Written
                    </th>
                    <th className="px-4 py-3 min-w-[150px] text-gray-700">Missed Subjects</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {filteredStudents.length === 0 ? (
                    <tr>
                      <td
                        colSpan={6 + activeBranchData.exams.length}
                        className="px-4 py-8 text-center text-gray-500"
                      >
                        No students match the selected search or filter.
                      </td>
                    </tr>
                  ) : (
                    filteredStudents.map((st, idx) => {
                      const isPerfect = st.exams_absent === 0;
                      return (
                        <tr
                          key={st.usn}
                          className={`hover:bg-gray-50/80 transition-colors ${
                            !isPerfect ? "bg-amber-50/20" : ""
                          }`}
                        >
                          <td className="px-3 py-2.5 text-center font-mono text-gray-400">
                            {idx + 1}
                          </td>
                          <td className="px-3 py-2.5 font-mono font-bold text-gray-900 whitespace-nowrap">
                            {st.usn}
                          </td>
                          <td className="px-4 py-2.5 font-medium text-gray-800 whitespace-nowrap">
                            {st.name}
                          </td>
                          <td className="px-3 py-2.5 text-center">
                            <span className="px-2 py-0.5 rounded text-[11px] font-mono bg-gray-100 text-gray-700 font-bold">
                              {st.branch}
                            </span>
                          </td>

                          {/* Status for each subject in series */}
                          {activeBranchData.exams.map((ex) => {
                            const status = st.exam_status[ex.subject_code] || "ABSENT";
                            const isPresent = status === "PRESENT";
                            return (
                              <td
                                key={ex.subject_code}
                                className="px-3 py-2.5 text-center border-l border-gray-100"
                              >
                                {isPresent ? (
                                  <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold bg-emerald-100 text-emerald-800">
                                    <span>✓</span>
                                    <span>PRESENT</span>
                                  </span>
                                ) : (
                                  <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold bg-red-100 text-red-800">
                                    <span>✗</span>
                                    <span>ABSENT</span>
                                  </span>
                                )}
                              </td>
                            );
                          })}

                          {/* How many they wrote */}
                          <td className="px-4 py-2.5 text-center border-l border-emerald-100 bg-emerald-50/20 whitespace-nowrap">
                            <div className="inline-flex items-center gap-1.5">
                              <span
                                className={`px-2.5 py-1 rounded-xl text-xs font-black shadow-2xs ${
                                  st.exams_written === st.total_exams
                                    ? "bg-emerald-600 text-white"
                                    : st.exams_written >= st.total_exams - 1
                                    ? "bg-amber-600 text-white"
                                    : "bg-red-600 text-white"
                                }`}
                              >
                                {st.exams_written} / {st.total_exams}
                              </span>
                              <span className="text-[11px] font-bold text-gray-600">
                                ({st.attendance_pct}%)
                              </span>
                            </div>
                          </td>

                          {/* Missed subjects */}
                          <td className="px-4 py-2.5">
                            {st.missed_subjects.length === 0 ? (
                              <span className="text-emerald-700 text-[11px] font-medium">
                                None (All Written)
                              </span>
                            ) : (
                              <div className="flex flex-wrap gap-1">
                                {st.missed_subjects.map((sub) => (
                                  <span
                                    key={sub}
                                    className="px-2 py-0.5 rounded text-[10px] font-bold bg-red-50 border border-red-200 text-red-700 font-mono"
                                  >
                                    {sub}
                                  </span>
                                ))}
                              </div>
                            )}
                          </td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>
            <div className="p-3 bg-gray-50 border-t border-gray-200 flex items-center justify-between text-xs text-gray-500">
              <span>Showing {filteredStudents.length} of {activeBranchData.students.length} candidates</span>
              <span>RollCall AI Exam Intelligence · Form-B Verification</span>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
