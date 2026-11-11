"use client";

import React, { useEffect, useState, useCallback, useMemo } from "react";
import { Link } from "react-router-dom";
import {
  fetchTeacherSubjects,
  assignTeacherSubject,
  removeTeacherSubject,
  type TeacherSubjectMapping,
  KNOWN_SUBJECTS,
  AVAILABLE_FACULTY,
} from "@/services/api/faculty";
import { useAuth } from "@/hooks/useAuth";

interface DepartmentInfo {
  code: string;
  name: string;
  coordinator: string;
  totalFaculty: number;
  activeSubjects: string[];
}

const DEPARTMENTS: DepartmentInfo[] = [
  {
    code: "CSE",
    name: "Computer Science & Engineering",
    coordinator: "Prof. Arvind Sharma",
    totalFaculty: 18,
    activeSubjects: ["DIST-SYS", "DB-SYS", "CN", "ALGO"],
  },
  {
    code: "CYBER",
    name: "Cyber Security & Digital Forensics",
    coordinator: "Dr. Kavita Menon",
    totalFaculty: 12,
    activeSubjects: ["NET-SEC", "CRYPT", "FORENSICS"],
  },
  {
    code: "AIML",
    name: "Artificial Intelligence & Machine Learning",
    coordinator: "Dr. Rajesh Raman",
    totalFaculty: 15,
    activeSubjects: ["ML", "NLP", "DEEP-LEARN"],
  },
  {
    code: "ECE",
    name: "Electronics & Communication Engineering",
    coordinator: "Prof. S. N. Murthy",
    totalFaculty: 14,
    activeSubjects: ["ES", "VLSI", "SIG-SYS"],
  },
  {
    code: "ISE",
    name: "Information Science & Engineering",
    coordinator: "Dr. Meenakshi Rao",
    totalFaculty: 11,
    activeSubjects: ["CLOUD-COMP", "WEB-TECH"],
  },
];

export function FacultyView() {
  const { isAdmin } = useAuth();
  const [mappings, setMappings] = useState<TeacherSubjectMapping[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [feedbackMessage, setFeedbackMessage] = useState<{ type: "success" | "error" | "info"; text: string } | null>(null);

  // Active Tab
  const [activeTab, setActiveTab] = useState<"FACULTY" | "DEPARTMENTS">("FACULTY");

  // Assignment Modal
  const [isAssignOpen, setIsAssignOpen] = useState(false);
  const [selectedTeacherId, setSelectedTeacherId] = useState(AVAILABLE_FACULTY[0].id);
  const [customTeacherId, setCustomTeacherId] = useState("");
  const [isCustomTeacher, setIsCustomTeacher] = useState(false);
  const [selectedSubjectCode, setSelectedSubjectCode] = useState(Object.keys(KNOWN_SUBJECTS)[0]);
  const [customSubjectCode, setCustomSubjectCode] = useState("");
  const [isCustomSubject, setIsCustomSubject] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  // Confirmation Modal for Removal
  const [pendingRemoval, setPendingRemoval] = useState<TeacherSubjectMapping | null>(null);
  const [isRemoving, setIsRemoving] = useState(false);

  const loadMappings = useCallback(async () => {
    if (!isAdmin) {
      setIsLoading(false);
      return;
    }
    setIsLoading(true);
    setError(null);
    try {
      const res = await fetchTeacherSubjects();
      setMappings(res.items || []);
    } catch (err: unknown) {
      if (err instanceof Error) {
        setError(err.message);
      } else {
        setError("Unable to load faculty subject assignments.");
      }
    } finally {
      setIsLoading(false);
    }
  }, [isAdmin]);

  useEffect(() => {
    let isMounted = true;
    Promise.resolve().then(() => {
      if (isMounted) void loadMappings();
    });
    return () => {
      isMounted = false;
    };
  }, [loadMappings]);

  // Enrich mappings with subject name, semester, branch, and teacher name
  const enrichedMappings = useMemo(() => {
    return mappings.map((m) => {
      const teacherId = m.teacher_id || m.user_id || "";
      const sub = KNOWN_SUBJECTS[m.subject_code] || {
        code: m.subject_code,
        name: `${m.subject_code} Theory & Lab`,
        semester: 5,
        branch: "General Engineering",
      };
      const faculty = AVAILABLE_FACULTY.find((f) => f.id === teacherId);

      return {
        ...m,
        teacher_id: teacherId,
        teacher_name: faculty ? faculty.name : teacherId,
        subject_name: sub.name,
        semester: sub.semester,
        branch: sub.branch,
      };
    });
  }, [mappings]);

  const handleAssign = async (e: React.FormEvent) => {
    e.preventDefault();
    const effectiveTeacherId = (isCustomTeacher ? customTeacherId : selectedTeacherId).trim();
    const effectiveSubjectCode = (isCustomSubject ? customSubjectCode : selectedSubjectCode).trim().toUpperCase();

    if (!effectiveTeacherId || !effectiveSubjectCode) {
      setFormError("Both Teacher ID and Subject Code are required.");
      return;
    }

    setIsSubmitting(true);
    setFormError(null);
    setFeedbackMessage(null);

    try {
      await assignTeacherSubject({
        user_id: effectiveTeacherId,
        subject_code: effectiveSubjectCode,
      });

      setFeedbackMessage({
        type: "success",
        text: `Subject ${effectiveSubjectCode} successfully assigned to ${effectiveTeacherId}.`,
      });
      setIsAssignOpen(false);
      setCustomTeacherId("");
      setCustomSubjectCode("");
      await loadMappings();
    } catch (err: unknown) {
      if (err instanceof Error) {
        setFormError(err.message);
      } else {
        setFormError("Failed to assign subject to faculty member.");
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleConfirmRemoval = async () => {
    if (!pendingRemoval) return;
    setIsRemoving(true);
    setFeedbackMessage(null);

    try {
      const teacherId = pendingRemoval.teacher_id || pendingRemoval.user_id || "";
      const result = await removeTeacherSubject(teacherId, pendingRemoval.subject_code);

      if (result.success) {
        setFeedbackMessage({
          type: "success",
          text: `Mapping for ${pendingRemoval.subject_code} (${teacherId}) removed successfully.`,
        });
      } else {
        // Clear dependency notification
        setFeedbackMessage({
          type: "info",
          text: result.message,
        });
      }
      setPendingRemoval(null);
      await loadMappings();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to remove mapping.";
      setFeedbackMessage({
        type: "error",
        text: `Error removing mapping: ${msg}`,
      });
    } finally {
      setIsRemoving(false);
    }
  };

  if (!isAdmin) {
    return (
      <div className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl p-8 max-w-xl mx-auto text-center space-y-4 shadow-sm my-12">
        <div className="w-12 h-12 rounded-2xl bg-amber-100 text-amber-800 flex items-center justify-center mx-auto">
          <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
          </svg>
        </div>
        <h2 className="text-xl font-bold text-[#24251C]">Administrator Privilege Required</h2>
        <p className="text-xs text-[#77735F] leading-relaxed">
          Faculty and subject allocation management is strictly restricted to institutional administrators. As a Course Faculty member, your assigned subjects and timetable can be viewed in <strong>Timetable</strong> and <strong>Sessions</strong>.
        </p>
        <div className="pt-2">
          <Link to="/" className="px-4 py-2 rounded-xl bg-[#3F451F] text-[#EDE8D8] text-xs font-bold hover:bg-[#343919] transition-colors shadow-2xs inline-block">
            Return to Dashboard
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header Bar */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-[#24251C] tracking-tight">
            Teacher-Subject Allocations & Departments
          </h1>
          <p className="text-sm text-[#77735F] mt-0.5">
            Institutional mapping grid: assign faculty to curriculum subjects, manage academic scopes, and maintain department boundaries.
          </p>
        </div>
        <button
          onClick={() => {
            setFormError(null);
            setIsAssignOpen(true);
          }}
          className="inline-flex items-center justify-center gap-2 px-4 py-2 bg-[#3F451F] text-[#FBF8F0] text-sm font-semibold rounded-xl hover:bg-[#323719] transition-all shadow-sm cursor-pointer"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 4v16m8-8H4" />
          </svg>
          Add Mapping
        </button>
      </div>

      {/* Global Feedback Alert */}
      {feedbackMessage && (
        <div
          className={`p-3.5 rounded-xl text-xs font-semibold flex items-center justify-between border ${
            feedbackMessage.type === "success"
              ? "bg-emerald-50 text-emerald-800 border-emerald-200"
              : feedbackMessage.type === "error"
              ? "bg-rose-50 text-rose-800 border-rose-200"
              : "bg-amber-50 text-amber-800 border-amber-200"
          }`}
        >
          <span>{feedbackMessage.text}</span>
          <button
            onClick={() => setFeedbackMessage(null)}
            className="text-xs hover:underline cursor-pointer"
          >
            Dismiss
          </button>
        </div>
      )}

      {/* Tabs */}
      <div className="flex items-center gap-2 border-b border-[#E4DDCA] pb-3">
        <button
          onClick={() => setActiveTab("FACULTY")}
          className={`px-4 py-2 rounded-xl text-sm font-semibold transition-all cursor-pointer ${
            activeTab === "FACULTY"
              ? "bg-[#3F451F] text-[#FBF8F0] shadow-xs"
              : "text-[#77735F] hover:bg-[#F2EDE0]"
          }`}
        >
          Teacher-Subject Mapping Grid ({mappings.length})
        </button>
        <button
          onClick={() => setActiveTab("DEPARTMENTS")}
          className={`px-4 py-2 rounded-xl text-sm font-semibold transition-all cursor-pointer ${
            activeTab === "DEPARTMENTS"
              ? "bg-[#3F451F] text-[#FBF8F0] shadow-xs"
              : "text-[#77735F] hover:bg-[#F2EDE0]"
          }`}
        >
          Academic Departments
        </button>
      </div>

      {activeTab === "FACULTY" ? (
        <div className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl overflow-hidden shadow-sm">
          <div className="p-4 border-b border-[#E4DDCA] flex items-center justify-between">
            <div>
              <h2 className="text-sm font-bold text-[#24251C] uppercase tracking-wider">
                Active Curriculum Allocations
              </h2>
              <p className="text-xs text-[#77735F]">
                Backend Authoritative • Governs Faculty Session & Attendance Edit Permissions
              </p>
            </div>
            <button
              onClick={() => void loadMappings()}
              className="text-xs font-semibold text-[#6C5119] hover:underline cursor-pointer flex items-center gap-1"
            >
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
              </svg>
              Refresh
            </button>
          </div>

          {isLoading ? (
            <div className="p-12 text-center text-[#77735F]">
              <div className="inline-block animate-spin w-6 h-6 border-2 border-[#3F451F] border-t-transparent rounded-full mb-2" />
              <p className="text-sm font-medium">Loading teacher-subject allocations...</p>
            </div>
          ) : error ? (
            <div className="p-10 text-center">
              <p className="text-sm text-rose-600 mb-3">{error}</p>
              <button
                onClick={() => void loadMappings()}
                className="px-4 py-1.5 bg-[#3F451F] text-[#FBF8F0] text-xs font-semibold rounded-lg hover:bg-[#323719] cursor-pointer"
              >
                Retry
              </button>
            </div>
          ) : enrichedMappings.length === 0 ? (
            <div className="p-12 text-center text-[#77735F]">
              <p className="text-sm font-semibold">No teacher-subject allocations found.</p>
              <p className="text-xs mt-1">Assign curriculum subjects to active faculty users.</p>
              <button
                onClick={() => setIsAssignOpen(true)}
                className="mt-4 px-4 py-2 bg-[#3F451F] text-[#FBF8F0] text-xs font-semibold rounded-xl cursor-pointer"
              >
                Assign First Subject
              </button>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="bg-[#F2EDE0] text-[#77735F] uppercase text-xs border-b border-[#E4DDCA]">
                  <tr>
                    <th className="py-3 px-4 font-semibold">Teacher Name / ID</th>
                    <th className="py-3 px-4 font-semibold">Subject Code</th>
                    <th className="py-3 px-4 font-semibold">Subject Name</th>
                    <th className="py-3 px-4 font-semibold">Semester</th>
                    <th className="py-3 px-4 font-semibold">Branch</th>
                    <th className="py-3 px-4 font-semibold text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#E4DDCA]/60 text-[#24251C]">
                  {enrichedMappings.map((m, idx) => (
                    <tr
                      key={`${m.teacher_id}-${m.subject_code}-${idx}`}
                      className="hover:bg-[#F2EDE0]/50 transition-colors"
                    >
                      <td className="py-3.5 px-4">
                        <div>
                          <span className="font-semibold text-[#24251C] block">
                            {m.teacher_name}
                          </span>
                          <span className="font-mono text-xs text-[#77735F]">
                            {m.teacher_id}
                          </span>
                        </div>
                      </td>
                      <td className="py-3.5 px-4 font-mono">
                        <span className="inline-flex items-center px-2.5 py-0.5 rounded-md text-xs font-bold bg-[#6C5119]/15 text-[#6C5119] border border-[#6C5119]/30">
                          {m.subject_code}
                        </span>
                      </td>
                      <td className="py-3.5 px-4 font-medium text-xs sm:text-sm text-[#24251C]">
                        {m.subject_name}
                      </td>
                      <td className="py-3.5 px-4 text-xs font-semibold text-[#77735F]">
                        Sem {m.semester}
                      </td>
                      <td className="py-3.5 px-4">
                        <span className="inline-flex items-center px-2 py-0.5 rounded-md text-xs font-semibold bg-[#3F451F]/10 text-[#3F451F]">
                          {m.branch}
                        </span>
                      </td>
                      <td className="py-3.5 px-4 text-right">
                        <button
                          onClick={() => setPendingRemoval(m)}
                          className="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-semibold text-rose-700 hover:text-rose-900 bg-rose-50 hover:bg-rose-100 rounded-lg transition-colors cursor-pointer"
                          title="Remove allocation"
                        >
                          <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                          </svg>
                          Remove
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      ) : (
        /* Departments Grid */
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
          {DEPARTMENTS.map((dept) => (
            <div
              key={dept.code}
              className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl p-5 shadow-sm hover:shadow-md transition-all flex flex-col justify-between"
            >
              <div>
                <div className="flex items-center justify-between mb-3">
                  <span className="inline-flex items-center px-2.5 py-1 rounded-lg text-xs font-bold bg-[#3F451F] text-[#FBF8F0]">
                    {dept.code}
                  </span>
                  <span className="text-xs text-[#77735F] font-medium">
                    {dept.totalFaculty} Active Faculty
                  </span>
                </div>
                <h3 className="text-base font-bold text-[#24251C]">{dept.name}</h3>
                <div className="mt-3 pt-3 border-t border-[#E4DDCA]/70 text-xs text-[#77735F] space-y-1.5">
                  <p>
                    <span className="font-semibold text-[#24251C]">Coordinator:</span>{" "}
                    {dept.coordinator}
                  </p>
                  <div>
                    <span className="font-semibold text-[#24251C]">Curriculum:</span>
                    <div className="flex flex-wrap gap-1.5 mt-1.5">
                      {dept.activeSubjects.map((sub) => (
                        <span
                          key={sub}
                          className="px-2 py-0.5 rounded-md text-[11px] font-semibold bg-[#F2EDE0] border border-[#E4DDCA] text-[#3F451F]"
                        >
                          {sub}
                        </span>
                      ))}
                    </div>
                  </div>
                </div>
              </div>

              <div className="mt-5 pt-3 border-t border-[#E4DDCA]/60 flex items-center justify-between">
                <span className="text-xs text-emerald-700 font-semibold flex items-center gap-1">
                  <span className="w-2 h-2 rounded-full bg-emerald-500" />
                  Accredited Program
                </span>
                <span className="text-xs font-bold text-[#6C5119]">2026 Academic Term</span>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Add Mapping Modal */}
      {isAssignOpen && (
        <div className="fixed inset-0 z-50 bg-black/40 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl p-6 max-w-md w-full shadow-xl">
            <h3 className="text-lg font-bold text-[#24251C]">Assign Curriculum Subject</h3>
            <p className="text-xs text-[#77735F] mt-1">
              Select an authorized faculty member and allocate their teaching subject code.
            </p>

            {formError && (
              <div className="mt-3 p-2.5 bg-rose-50 border border-rose-200 rounded-xl text-xs text-rose-700">
                {formError}
              </div>
            )}

            <form onSubmit={handleAssign} className="mt-4 space-y-4">
              <div>
                <label className="block text-xs font-semibold text-[#77735F] mb-1">
                  Available Faculty Member *
                </label>
                {!isCustomTeacher ? (
                  <div className="space-y-1.5">
                    <select
                      value={selectedTeacherId}
                      onChange={(e) => setSelectedTeacherId(e.target.value)}
                      className="w-full bg-[#F2EDE0] border border-[#E4DDCA] rounded-xl px-3 py-2 text-sm text-[#24251C] focus:outline-none focus:border-[#3F451F]"
                    >
                      {AVAILABLE_FACULTY.map((f) => (
                        <option key={f.id} value={f.id}>
                          {f.name} ({f.id}) — {f.department}
                        </option>
                      ))}
                    </select>
                    <button
                      type="button"
                      onClick={() => setIsCustomTeacher(true)}
                      className="text-[11px] text-[#6C5119] font-semibold hover:underline cursor-pointer"
                    >
                      + Enter custom User ID
                    </button>
                  </div>
                ) : (
                  <div className="space-y-1.5">
                    <input
                      type="text"
                      required
                      value={customTeacherId}
                      onChange={(e) => setCustomTeacherId(e.target.value)}
                      placeholder="e.g. faculty_ml"
                      className="w-full bg-[#F2EDE0] border border-[#E4DDCA] rounded-xl px-3.5 py-2 text-sm text-[#24251C] focus:outline-none focus:border-[#3F451F]"
                    />
                    <button
                      type="button"
                      onClick={() => setIsCustomTeacher(false)}
                      className="text-[11px] text-[#6C5119] font-semibold hover:underline cursor-pointer"
                    >
                      ← Back to dropdown
                    </button>
                  </div>
                )}
              </div>

              <div>
                <label className="block text-xs font-semibold text-[#77735F] mb-1">
                  Subject Code & Curriculum *
                </label>
                {!isCustomSubject ? (
                  <div className="space-y-1.5">
                    <select
                      value={selectedSubjectCode}
                      onChange={(e) => setSelectedSubjectCode(e.target.value)}
                      className="w-full bg-[#F2EDE0] border border-[#E4DDCA] rounded-xl px-3 py-2 text-sm text-[#24251C] focus:outline-none focus:border-[#3F451F]"
                    >
                      {Object.values(KNOWN_SUBJECTS).map((s) => (
                        <option key={s.code} value={s.code}>
                          {s.code} — {s.name} (Sem {s.semester}, {s.branch})
                        </option>
                      ))}
                    </select>
                    <button
                      type="button"
                      onClick={() => setIsCustomSubject(true)}
                      className="text-[11px] text-[#6C5119] font-semibold hover:underline cursor-pointer"
                    >
                      + Enter custom subject code
                    </button>
                  </div>
                ) : (
                  <div className="space-y-1.5">
                    <input
                      type="text"
                      required
                      value={customSubjectCode}
                      onChange={(e) => setCustomSubjectCode(e.target.value)}
                      placeholder="e.g. DIST-SYS"
                      className="w-full bg-[#F2EDE0] border border-[#E4DDCA] rounded-xl px-3.5 py-2 text-sm text-[#24251C] uppercase focus:outline-none focus:border-[#3F451F]"
                    />
                    <button
                      type="button"
                      onClick={() => setIsCustomSubject(false)}
                      className="text-[11px] text-[#6C5119] font-semibold hover:underline cursor-pointer"
                    >
                      ← Back to dropdown
                    </button>
                  </div>
                )}
              </div>

              <div className="pt-3 flex items-center justify-end gap-2.5">
                <button
                  type="button"
                  onClick={() => setIsAssignOpen(false)}
                  className="px-4 py-2 rounded-xl text-sm font-semibold text-[#77735F] hover:bg-[#F2EDE0] transition-colors cursor-pointer"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isSubmitting}
                  className="px-4 py-2 rounded-xl text-sm font-semibold bg-[#3F451F] text-[#FBF8F0] hover:bg-[#323719] transition-colors disabled:opacity-50 cursor-pointer"
                >
                  {isSubmitting ? "Saving..." : "Confirm Allocation"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Removal Confirmation Dialog */}
      {pendingRemoval && (
        <div className="fixed inset-0 z-50 bg-black/40 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl p-6 max-w-md w-full shadow-xl space-y-4">
            <div className="w-10 h-10 rounded-xl bg-rose-100 text-rose-700 flex items-center justify-center">
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
              </svg>
            </div>
            <div>
              <h3 className="text-base font-bold text-[#24251C]">Confirm Allocation Removal</h3>
              <p className="text-xs text-[#77735F] mt-1.5 leading-relaxed">
                Are you sure you want to remove the subject mapping for{" "}
                <strong className="text-[#24251C]">
                  {pendingRemoval.subject_code}
                </strong>{" "}
                assigned to faculty member{" "}
                <strong className="text-[#24251C]">
                  {pendingRemoval.teacher_name || pendingRemoval.teacher_id}
                </strong>
                ? This will revoke the faculty member&apos;s direct verification rights for this subject.
              </p>
            </div>

            <div className="pt-2 flex items-center justify-end gap-2.5">
              <button
                type="button"
                onClick={() => setPendingRemoval(null)}
                className="px-4 py-2 rounded-xl text-xs font-semibold text-[#77735F] hover:bg-[#F2EDE0] transition-colors cursor-pointer"
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={isRemoving}
                onClick={() => void handleConfirmRemoval()}
                className="px-4 py-2 rounded-xl text-xs font-bold bg-rose-700 text-white hover:bg-rose-800 transition-colors disabled:opacity-50 cursor-pointer"
              >
                {isRemoving ? "Removing..." : "Confirm Removal"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
