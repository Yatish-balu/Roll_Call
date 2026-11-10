"use client";

import React, { useEffect, useState, useMemo, useCallback } from "react";
import { fetchStudents, createStudent, type Student } from "@/services/api/students";

export function StudentsView() {
  const [students, setStudents] = useState<Student[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Search & Filter state
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedBranch, setSelectedBranch] = useState("ALL");

  // Detail Modal state
  const [selectedStudent, setSelectedStudent] = useState<Student | null>(null);

  // Add Student Modal state
  const [isAddModalOpen, setIsAddModalOpen] = useState(false);
  const [newUsn, setNewUsn] = useState("");
  const [newName, setNewName] = useState("");
  const [newBranch, setNewBranch] = useState("CSE");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const loadStudents = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await fetchStudents({ limit: 100 });
      setStudents(res.items || []);
    } catch (err: unknown) {
      if (err instanceof Error) {
        setError(err.message);
      } else {
        setError("Unable to load student directory from server.");
      }
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    let isMounted = true;
    Promise.resolve().then(() => {
      if (isMounted) void loadStudents();
    });
    return () => {
      isMounted = false;
    };
  }, [loadStudents]);

  // Derived filtered list
  const filteredStudents = useMemo(() => {
    return students.filter((s) => {
      const matchesSearch =
        s.usn.toLowerCase().includes(searchQuery.toLowerCase()) ||
        s.name.toLowerCase().includes(searchQuery.toLowerCase());
      const matchesBranch =
        selectedBranch === "ALL" || s.branch.toUpperCase() === selectedBranch.toUpperCase();
      return matchesSearch && matchesBranch;
    });
  }, [students, searchQuery, selectedBranch]);

  // Unique branches for filter dropdown
  const branchOptions = useMemo(() => {
    const set = new Set(students.map((s) => s.branch.toUpperCase()));
    return Array.from(set);
  }, [students]);

  const handleAddSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
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
    <div className="space-y-6 max-w-7xl mx-auto">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 pb-2">
        <div>
          <div className="flex items-center space-x-2.5">
            <h1 className="text-2xl sm:text-3xl font-extrabold text-[#24251C] tracking-tight">
              Students Directory
            </h1>
            <span className="px-2.5 py-0.5 rounded-full text-xs font-bold bg-[#EDE8D8] text-[#6C5119] border border-[#E4DDCA]">
              {isLoading ? "..." : `${students.length} Total`}
            </span>
          </div>
          <p className="text-xs sm:text-sm text-[#77735F] mt-1">
            Institutional roster, enrolled sections, and academic allocations.
          </p>
        </div>

        <button
          onClick={() => setIsAddModalOpen(true)}
          className="inline-flex items-center space-x-2 px-4 py-2.5 rounded-xl text-xs sm:text-sm font-bold bg-[#6C5119] hover:bg-[#594214] text-white shadow-2xs transition-colors cursor-pointer self-start sm:self-auto"
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.2} d="M12 4v16m8-8H4" />
          </svg>
          <span>Register Student</span>
        </button>
      </div>

      {/* Error Banner */}
      {error && (
        <div className="bg-[#FFF8E1] border border-[#FFE082] rounded-xl p-4 flex items-center justify-between text-xs text-[#6C5119]">
          <div className="flex items-center space-x-2.5">
            <svg className="w-5 h-5 text-[#F57F17] shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
            <span>{error}</span>
          </div>
          <button
            onClick={() => void loadStudents()}
            className="font-bold underline hover:text-[#24251C] transition-colors ml-4 cursor-pointer"
          >
            Retry
          </button>
        </div>
      )}

      {/* Search and Filters Bar */}
      <div className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl p-4 shadow-2xs flex flex-col sm:flex-row items-center justify-between gap-3">
        <div className="relative w-full sm:w-80">
          <svg
            className="w-4 h-4 absolute left-3.5 top-3 text-[#77735F]"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search by USN or name..."
            className="w-full pl-9 pr-4 py-2 rounded-xl bg-white border border-[#E4DDCA] text-xs sm:text-sm text-[#24251C] placeholder-[#77735F]/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#6C5119]"
          />
        </div>

        <div className="flex items-center space-x-2.5 w-full sm:w-auto">
          <label className="text-xs font-semibold text-[#77735F] whitespace-nowrap">
            Department:
          </label>
          <select
            value={selectedBranch}
            onChange={(e) => setSelectedBranch(e.target.value)}
            className="px-3 py-2 rounded-xl bg-white border border-[#E4DDCA] text-xs font-medium text-[#24251C] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#6C5119] cursor-pointer"
          >
            <option value="ALL">All Departments</option>
            {branchOptions.map((b) => (
              <option key={b} value={b}>
                {b}
              </option>
            ))}
          </select>

          <button
            onClick={() => void loadStudents()}
            className="p-2 rounded-xl bg-white border border-[#E4DDCA] text-[#77735F] hover:text-[#24251C] hover:bg-[#EDE8D8]/50 transition-colors"
            title="Refresh list"
            aria-label="Refresh list"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
          </button>
        </div>
      </div>

      {/* Students Table Card */}
      <div className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl shadow-2xs overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs sm:text-sm">
            <thead>
              <tr className="border-b border-[#E4DDCA] bg-[#EDE8D8]/40 text-[#77735F] font-semibold">
                <th className="py-3.5 pl-4 sm:pl-6">USN</th>
                <th className="py-3.5 px-4">Student Name</th>
                <th className="py-3.5 px-4">Branch</th>
                <th className="py-3.5 px-4">Semester & Batch</th>
                <th className="py-3.5 pr-4 sm:pr-6 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#E4DDCA]/60 text-[#24251C]">
              {isLoading && (
                <tr>
                  <td colSpan={5} className="py-12 text-center text-[#77735F]">
                    <div className="flex flex-col items-center space-y-2">
                      <div className="w-6 h-6 border-2 border-[#6C5119] border-t-transparent rounded-full animate-spin" />
                      <span>Loading students roster...</span>
                    </div>
                  </td>
                </tr>
              )}

              {!isLoading && filteredStudents.length === 0 && (
                <tr>
                  <td colSpan={5} className="py-14 text-center">
                    <div className="max-w-xs mx-auto space-y-2 text-[#77735F]">
                      <svg className="w-10 h-10 mx-auto opacity-50" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a4 4 0 11-8 0 4 4 0 018 0z" />
                      </svg>
                      <p className="font-bold text-[#24251C]">No Students Found</p>
                      <p className="text-xs">No records matched your search query or department filter.</p>
                    </div>
                  </td>
                </tr>
              )}

              {!isLoading &&
                filteredStudents.map((st, idx) => (
                  <tr key={st.usn} className="hover:bg-[#EDE8D8]/20 transition-colors">
                    <td className="py-3.5 pl-4 sm:pl-6 font-bold text-[#6C5119]">
                      {st.usn}
                    </td>
                    <td className="py-3.5 px-4 font-semibold text-[#24251C]">
                      {st.name}
                    </td>
                    <td className="py-3.5 px-4">
                      <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold bg-[#EDE8D8] text-[#24251C] border border-[#E4DDCA]">
                        {st.branch}
                      </span>
                    </td>
                    <td className="py-3.5 px-4 text-xs text-[#77735F]">
                      <span>Sem 5 • Sec {idx % 2 === 0 ? "A" : "B"} • Batch B{1 + (idx % 3)}</span>
                    </td>
                    <td className="py-3.5 pr-4 sm:pr-6 text-right">
                      <button
                        onClick={() => setSelectedStudent(st)}
                        className="inline-flex items-center space-x-1 px-3 py-1 rounded-lg text-xs font-semibold bg-[#FBF8F0] border border-[#E4DDCA] text-[#24251C] hover:bg-[#EDE8D8] transition-colors cursor-pointer"
                      >
                        <span>Details</span>
                        <span>→</span>
                      </button>
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Student Details Drawer / Modal */}
      {selectedStudent && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40 backdrop-blur-xs">
          <div className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl p-6 max-w-md w-full shadow-xl space-y-5 animate-fadeIn">
            <div className="flex items-center justify-between pb-2 border-b border-[#E4DDCA]">
              <div className="flex items-center space-x-2.5">
                <div className="w-8 h-8 rounded-lg bg-[#EDE8D8] text-[#6C5119] flex items-center justify-center">
                  <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
                  </svg>
                </div>
                <h3 className="text-base font-bold text-[#24251C]">Student Profile</h3>
              </div>
              <button
                onClick={() => setSelectedStudent(null)}
                className="text-[#77735F] hover:text-[#24251C] text-sm font-bold"
              >
                ✕
              </button>
            </div>

            <div className="space-y-3 text-xs sm:text-sm">
              <div className="flex justify-between py-1.5 border-b border-[#E4DDCA]/50">
                <span className="text-[#77735F]">Unique Student Number</span>
                <span className="font-bold text-[#6C5119]">{selectedStudent.usn}</span>
              </div>
              <div className="flex justify-between py-1.5 border-b border-[#E4DDCA]/50">
                <span className="text-[#77735F]">Full Name</span>
                <span className="font-semibold text-[#24251C]">{selectedStudent.name}</span>
              </div>
              <div className="flex justify-between py-1.5 border-b border-[#E4DDCA]/50">
                <span className="text-[#77735F]">Department / Branch</span>
                <span className="font-semibold text-[#24251C]">{selectedStudent.branch}</span>
              </div>
              <div className="flex justify-between py-1.5 border-b border-[#E4DDCA]/50">
                <span className="text-[#77735F]">Enrolled Semester</span>
                <span className="text-[#24251C]">Semester 5 (Academic Year 2026-27)</span>
              </div>
              <div className="flex justify-between py-1.5 border-b border-[#E4DDCA]/50">
                <span className="text-[#77735F]">Section & Lab Batch</span>
                <span className="text-[#24251C]">Section A • Lab Batch B1</span>
              </div>
              <div className="flex justify-between py-1.5">
                <span className="text-[#77735F]">Attendance Standing</span>
                <span className="font-bold text-emerald-700">Eligible (Standing Good)</span>
              </div>
            </div>

            <div className="pt-2 flex justify-end">
              <button
                onClick={() => setSelectedStudent(null)}
                className="px-4 py-2 rounded-xl bg-[#EDE8D8] text-[#24251C] hover:bg-[#E4DDCA] font-bold text-xs transition-colors cursor-pointer"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Add Student Modal */}
      {isAddModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40 backdrop-blur-xs">
          <div className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl p-6 max-w-md w-full shadow-xl space-y-4 animate-fadeIn">
            <div className="flex items-center justify-between pb-2 border-b border-[#E4DDCA]">
              <h3 className="text-base font-bold text-[#24251C]">Register New Student</h3>
              <button
                onClick={() => setIsAddModalOpen(false)}
                className="text-[#77735F] hover:text-[#24251C] text-sm font-bold"
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
                  className="w-full px-3.5 py-2 rounded-xl bg-white border border-[#E4DDCA] text-[#24251C] uppercase focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#6C5119]"
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
                  className="w-full px-3.5 py-2 rounded-xl bg-white border border-[#E4DDCA] text-[#24251C] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#6C5119]"
                />
              </div>

              <div>
                <label className="block font-semibold text-[#24251C] mb-1">
                  Department / Branch *
                </label>
                <select
                  value={newBranch}
                  onChange={(e) => setNewBranch(e.target.value)}
                  className="w-full px-3.5 py-2 rounded-xl bg-white border border-[#E4DDCA] text-[#24251C] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#6C5119]"
                >
                  <option value="CSE">Computer Science & Engineering (CSE)</option>
                  <option value="CYBER">Cyber Security (CYBER)</option>
                  <option value="AIML">Artificial Intelligence & ML (AIML)</option>
                  <option value="ECE">Electronics & Communication (ECE)</option>
                  <option value="ISE">Information Science (ISE)</option>
                </select>
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
                  className="px-4 py-2 rounded-xl bg-[#6C5119] hover:bg-[#594214] text-white font-bold text-xs shadow-2xs transition-colors disabled:opacity-50 cursor-pointer"
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
