"use client";

import React, { useEffect, useState, useCallback } from "react";
import { Link } from "react-router-dom";
import {
  fetchTeacherSubjects,
  assignTeacherSubject,
  type TeacherSubjectMapping,
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

  // Active Tab
  const [activeTab, setActiveTab] = useState<"FACULTY" | "DEPARTMENTS">("FACULTY");

  // Assignment Modal
  const [isAssignOpen, setIsAssignOpen] = useState(false);
  const [teacherId, setTeacherId] = useState("");
  const [subjectCode, setSubjectCode] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

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

  const handleAssign = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!teacherId.trim() || !subjectCode.trim()) {
      setFormError("Both Teacher ID and Subject Code are required.");
      return;
    }

    setIsSubmitting(true);
    setFormError(null);
    try {
      await assignTeacherSubject({
        teacher_id: teacherId.trim(),
        subject_code: subjectCode.trim().toUpperCase(),
      });
      setIsAssignOpen(false);
      setTeacherId("");
      setSubjectCode("");
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

  const isAdminOrCoordinator = isAdmin;

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
          Faculty and department coordinator management is restricted to institutional administrators. As a Course Faculty member, your assigned subjects and timetable can be accessed directly in <strong>My Timetable</strong> and <strong>Settings</strong>.
        </p>
        <div className="pt-2">
          <Link to="/" className="px-4 py-2 rounded-xl bg-[#3F451F] text-[#EDE8D8] text-xs font-bold hover:bg-[#343919] transition-colors shadow-2xs inline-block">
            Return to Teacher Dashboard
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
            Faculty & Academic Departments
          </h1>
          <p className="text-sm text-[#77735F] mt-0.5">
            Teacher-subject allocations, Department Coordinator management, and institutional units.
          </p>
        </div>
        {isAdminOrCoordinator && (
          <button
            onClick={() => setIsAssignOpen(true)}
            className="inline-flex items-center justify-center gap-2 px-4 py-2 bg-[#3F451F] text-[#FBF8F0] text-sm font-semibold rounded-xl hover:bg-[#323719] transition-all shadow-sm"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 4v16m8-8H4" />
            </svg>
            Assign Subject
          </button>
        )}
      </div>

      {/* Tabs */}
      <div className="flex items-center gap-2 border-b border-[#E4DDCA] pb-3">
        <button
          onClick={() => setActiveTab("FACULTY")}
          className={`px-4 py-2 rounded-xl text-sm font-semibold transition-all ${
            activeTab === "FACULTY"
              ? "bg-[#3F451F] text-[#FBF8F0] shadow-xs"
              : "text-[#77735F] hover:bg-[#F2EDE0]"
          }`}
        >
          Faculty Subject Allocations
        </button>
        <button
          onClick={() => setActiveTab("DEPARTMENTS")}
          className={`px-4 py-2 rounded-xl text-sm font-semibold transition-all ${
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
            <h2 className="text-sm font-bold text-[#24251C] uppercase tracking-wider">
              Assigned Faculty Members ({mappings.length})
            </h2>
            <button
              onClick={() => void loadMappings()}
              className="text-xs font-semibold text-[#6C5119] hover:underline"
            >
              Refresh Data
            </button>
          </div>

          {isLoading ? (
            <div className="p-12 text-center text-[#77735F]">
              <div className="inline-block animate-spin w-6 h-6 border-2 border-[#3F451F] border-t-transparent rounded-full mb-2" />
              <p className="text-sm">Loading teacher mappings...</p>
            </div>
          ) : error ? (
            <div className="p-10 text-center">
              <p className="text-sm text-red-600 mb-3">{error}</p>
              <button
                onClick={() => void loadMappings()}
                className="px-4 py-1.5 bg-[#3F451F] text-[#FBF8F0] text-xs font-semibold rounded-lg hover:bg-[#323719]"
              >
                Retry
              </button>
            </div>
          ) : mappings.length === 0 ? (
            <div className="p-12 text-center text-[#77735F]">
              <p className="text-sm">No teacher-subject allocations found.</p>
              {isAdminOrCoordinator && (
                <button
                  onClick={() => setIsAssignOpen(true)}
                  className="mt-3 px-3 py-1.5 bg-[#3F451F] text-[#FBF8F0] text-xs font-semibold rounded-lg"
                >
                  Assign First Subject
                </button>
              )}
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="bg-[#F2EDE0] text-[#77735F] uppercase text-xs border-b border-[#E4DDCA]">
                  <tr>
                    <th className="py-3 px-4 font-semibold">Faculty User ID</th>
                    <th className="py-3 px-4 font-semibold">Assigned Subject Code</th>
                    <th className="py-3 px-4 font-semibold">Authorization Scope</th>
                    <th className="py-3 px-4 font-semibold">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#E4DDCA]/60 text-[#24251C]">
                  {mappings.map((m, idx) => (
                    <tr key={`${m.teacher_id}-${m.subject_code}-${idx}`} className="hover:bg-[#F2EDE0]/50 transition-colors">
                      <td className="py-3.5 px-4 font-mono font-semibold text-[#3F451F]">
                        {m.teacher_id}
                      </td>
                      <td className="py-3.5 px-4">
                        <span className="inline-flex items-center px-2 py-0.5 rounded-md text-xs font-bold bg-[#6C5119]/15 text-[#6C5119] border border-[#6C5119]/30">
                          {m.subject_code}
                        </span>
                      </td>
                      <td className="py-3.5 px-4 text-xs text-[#77735F]">
                        Direct Attendance Verification & Roster Confirmation
                      </td>
                      <td className="py-3.5 px-4">
                        <span className="inline-flex items-center gap-1.5 text-xs text-emerald-700 font-medium">
                          <span className="w-2 h-2 rounded-full bg-emerald-500" />
                          Authorized
                        </span>
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

      {/* Assign Subject Modal */}
      {isAssignOpen && (
        <div className="fixed inset-0 z-50 bg-black/40 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl p-6 max-w-md w-full shadow-xl">
            <h3 className="text-lg font-bold text-[#24251C]">Assign Subject to Faculty</h3>
            <p className="text-xs text-[#77735F] mt-1">
              Grant a faculty user permission to record and verify attendance for a subject.
            </p>

            {formError && (
              <div className="mt-3 p-2.5 bg-red-50 border border-red-200 rounded-xl text-xs text-red-600">
                {formError}
              </div>
            )}

            <form onSubmit={handleAssign} className="mt-4 space-y-3.5">
              <div>
                <label className="block text-xs font-semibold text-[#77735F] mb-1">
                  Faculty User ID (e.g. TEACHER_ID)
                </label>
                <input
                  type="text"
                  required
                  value={teacherId}
                  onChange={(e) => setTeacherId(e.target.value)}
                  placeholder="TEACHER_ID"
                  className="w-full bg-[#F2EDE0] border border-[#E4DDCA] rounded-xl px-3.5 py-2 text-sm text-[#24251C] focus:outline-none focus:border-[#3F451F]"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-[#77735F] mb-1">
                  Subject Code (e.g. DIST-SYS, ML, CN, DB-SYS)
                </label>
                <input
                  type="text"
                  required
                  value={subjectCode}
                  onChange={(e) => setSubjectCode(e.target.value)}
                  placeholder="DIST-SYS"
                  className="w-full bg-[#F2EDE0] border border-[#E4DDCA] rounded-xl px-3.5 py-2 text-sm text-[#24251C] focus:outline-none focus:border-[#3F451F]"
                />
              </div>

              <div className="pt-3 flex items-center justify-end gap-2.5">
                <button
                  type="button"
                  onClick={() => setIsAssignOpen(false)}
                  className="px-4 py-2 rounded-xl text-sm font-semibold text-[#77735F] hover:bg-[#F2EDE0] transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isSubmitting}
                  className="px-4 py-2 rounded-xl text-sm font-semibold bg-[#3F451F] text-[#FBF8F0] hover:bg-[#323719] transition-colors disabled:opacity-50"
                >
                  {isSubmitting ? "Assigning..." : "Confirm Assignment"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
