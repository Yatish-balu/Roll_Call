"use client";

import React, { useEffect, useState, useCallback, useMemo } from "react";
import {
  fetchTeacherSubjects,
  assignTeacherSubject,
  removeTeacherSubject,
  fetchAdminTeachers,
  updateTeacherName,
  fetchPermissionRequests,
  reviewPermissionRequest,
  submitPermissionRequest,
  type TeacherSubjectMapping,
  type AdminTeacherItem,
  type PermissionRequestItem,
  KNOWN_SUBJECTS,
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

  // Data States
  const [teachers, setTeachers] = useState<AdminTeacherItem[]>([]);
  const [mappings, setMappings] = useState<TeacherSubjectMapping[]>([]);
  const [requests, setRequests] = useState<PermissionRequestItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [feedbackMessage, setFeedbackMessage] = useState<{
    type: "success" | "error" | "info";
    text: string;
  } | null>(null);

  // Active Tab: TEACHERS | APPROVALS | MAPPINGS | DEPARTMENTS
  const [activeTab, setActiveTab] = useState<"TEACHERS" | "APPROVALS" | "MAPPINGS" | "DEPARTMENTS">("TEACHERS");

  // Admin Change Name Modal
  const [editNameTarget, setEditNameTarget] = useState<AdminTeacherItem | null>(null);
  const [newNameInput, setNewNameInput] = useState("");
  const [isUpdatingName, setIsUpdatingName] = useState(false);
  const [nameModalError, setNameModalError] = useState<string | null>(null);

  // Teacher Request Permission Modal
  const [isRequestModalOpen, setIsRequestModalOpen] = useState(false);
  const [requestSubject, setRequestSubject] = useState(Object.keys(KNOWN_SUBJECTS)[0] || "");
  const [requestReason, setRequestReason] = useState("");
  const [isSubmittingRequest, setIsSubmittingRequest] = useState(false);

  // Assign Subject Modal
  const [isAssignOpen, setIsAssignOpen] = useState(false);
  const [selectedTeacherId, setSelectedTeacherId] = useState("");
  const [selectedSubjectCode, setSelectedSubjectCode] = useState(Object.keys(KNOWN_SUBJECTS)[0] || "");
  const [isSubmittingAssign, setIsSubmittingAssign] = useState(false);
  const [assignError, setAssignError] = useState<string | null>(null);

  // Confirmation Modal for Removal
  const [pendingRemoval, setPendingRemoval] = useState<TeacherSubjectMapping | null>(null);
  const [isRemoving, setIsRemoving] = useState(false);

  // Reviewing a Request
  const [reviewingId, setReviewingId] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const promises: Array<Promise<unknown>> = [
        fetchTeacherSubjects().catch(() => ({ total: 0, items: [] })),
        fetchPermissionRequests().catch(() => ({ total: 0, items: [] })),
      ];
      if (isAdmin) {
        promises.push(fetchAdminTeachers().catch(() => ({ total: 0, items: [] })));
      }

      const [mapRes, reqRes, teachRes] = await Promise.all(promises);
      const mItems = (mapRes as { items: TeacherSubjectMapping[] })?.items || [];
      const rItems = (reqRes as { items: PermissionRequestItem[] })?.items || [];
      const tItems = (teachRes as { items: AdminTeacherItem[] })?.items || [];

      setMappings(mItems);
      setRequests(rItems);
      setTeachers(tItems);

      if (tItems.length > 0 && !selectedTeacherId) {
        setSelectedTeacherId(tItems[0].user_id);
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load faculty records.");
    } finally {
      setIsLoading(false);
    }
  }, [isAdmin, selectedTeacherId]);

  useEffect(() => {
    let isMounted = true;
    Promise.resolve().then(() => {
      if (isMounted) void loadData();
    });
    return () => {
      isMounted = false;
    };
  }, [loadData]);

  const pendingRequestsCount = useMemo(() => {
    return requests.filter((r) => r.status === "PENDING").length;
  }, [requests]);

  // Handle Admin Name Change
  const handleSaveTeacherName = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editNameTarget || !newNameInput.trim()) return;
    setIsUpdatingName(true);
    setNameModalError(null);

    try {
      const res = await updateTeacherName(editNameTarget.user_id, newNameInput.trim());
      setFeedbackMessage({
        type: "success",
        text: res.message || `Successfully renamed teacher to '${newNameInput.trim()}'.`,
      });
      setEditNameTarget(null);
      await loadData();
    } catch (err: unknown) {
      setNameModalError(err instanceof Error ? err.message : "Failed to update teacher name.");
    } finally {
      setIsUpdatingName(false);
    }
  };

  // Handle Permission Request Submit
  const handleRequestPermission = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!requestReason.trim()) return;
    setIsSubmittingRequest(true);

    try {
      await submitPermissionRequest({
        subject_code: requestSubject,
        request_type: "SUBJECT_ASSIGNMENT",
        reason: requestReason.trim(),
      });
      setFeedbackMessage({
        type: "success",
        text: `Permission request for '${requestSubject}' submitted to Admin.`,
      });
      setIsRequestModalOpen(false);
      setRequestReason("");
      await loadData();
    } catch (err: unknown) {
      setFeedbackMessage({
        type: "error",
        text: err instanceof Error ? err.message : "Failed to submit request.",
      });
    } finally {
      setIsSubmittingRequest(false);
    }
  };

  // Handle Admin Review of Request
  const handleReviewRequest = async (requestId: string, decision: "APPROVE" | "REJECT") => {
    setReviewingId(requestId);
    try {
      const res = await reviewPermissionRequest(requestId, decision);
      setFeedbackMessage({
        type: "success",
        text: res.message || `Request ${decision.toLowerCase()}d successfully.`,
      });
      await loadData();
    } catch (err: unknown) {
      setFeedbackMessage({
        type: "error",
        text: err instanceof Error ? err.message : "Failed to review request.",
      });
    } finally {
      setReviewingId(null);
    }
  };

  // Handle Subject Assignment
  const handleAssignSubject = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedTeacherId || !selectedSubjectCode) return;
    setIsSubmittingAssign(true);
    setAssignError(null);

    try {
      await assignTeacherSubject({
        user_id: selectedTeacherId,
        subject_code: selectedSubjectCode,
      });
      setFeedbackMessage({
        type: "success",
        text: `Assigned subject ${selectedSubjectCode} to teacher ${selectedTeacherId}.`,
      });
      setIsAssignOpen(false);
      await loadData();
    } catch (err: unknown) {
      setAssignError(err instanceof Error ? err.message : "Failed to assign subject.");
    } finally {
      setIsSubmittingAssign(false);
    }
  };

  // Handle Subject Removal
  const handleRemoveSubject = async () => {
    if (!pendingRemoval) return;
    setIsRemoving(true);
    const uid = pendingRemoval.user_id || pendingRemoval.teacher_id;
    try {
      await removeTeacherSubject(uid, pendingRemoval.subject_code);
      setFeedbackMessage({
        type: "info",
        text: `Unassigned ${pendingRemoval.subject_code} from ${uid}.`,
      });
      setPendingRemoval(null);
      await loadData();
    } catch (err: unknown) {
      setFeedbackMessage({
        type: "error",
        text: err instanceof Error ? err.message : "Failed to unassign subject.",
      });
    } finally {
      setIsRemoving(false);
    }
  };

  return (
    <div className="space-y-6 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-2">
        <div>
          <div className="flex items-center space-x-2.5 flex-wrap">
            <h1 className="text-2xl sm:text-3xl font-extrabold text-[#24251C] tracking-tight">
              Faculty & Academic Directory
            </h1>
            <span className="px-2.5 py-0.5 rounded-full text-xs font-bold bg-[#EDE8D8] text-[#6C5119] border border-[#E4DDCA]">
              {isAdmin ? "Admin Authority" : "Faculty Workspace"}
            </span>
            {pendingRequestsCount > 0 && (
              <span className="px-2.5 py-0.5 rounded-full text-xs font-black bg-amber-100 text-amber-900 border border-amber-300 animate-pulse">
                {pendingRequestsCount} Pending Approval{pendingRequestsCount > 1 ? "s" : ""}
              </span>
            )}
          </div>
          <p className="text-xs sm:text-sm text-[#77735F] mt-1">
            Faculty accounts, official teacher names, subject allocations, and permission approvals.
          </p>
        </div>

        <div className="flex items-center gap-2">
          {isAdmin ? (
            <button
              onClick={() => setIsAssignOpen(true)}
              className="inline-flex items-center gap-1.5 px-4 py-2 bg-[#3F451F] text-[#FBF8F0] text-xs font-bold rounded-xl hover:bg-[#323719] transition-all shadow-2xs cursor-pointer"
            >
              <span>+ Assign Subject</span>
            </button>
          ) : (
            <button
              onClick={() => setIsRequestModalOpen(true)}
              className="inline-flex items-center gap-1.5 px-4 py-2 bg-[#6C5119] text-white text-xs font-bold rounded-xl hover:bg-[#594214] transition-all shadow-2xs cursor-pointer"
            >
              <span>+ Request Permission</span>
            </button>
          )}
        </div>
      </div>

      {/* Global Feedback Banner */}
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
            className="text-xs font-bold underline cursor-pointer ml-4"
          >
            Dismiss
          </button>
        </div>
      )}

      {error && (
        <div className="p-3.5 rounded-xl bg-rose-50 text-rose-800 border border-rose-200 text-xs flex items-center justify-between">
          <span>{error}</span>
          <button onClick={() => void loadData()} className="font-bold underline ml-4">
            Retry
          </button>
        </div>
      )}

      {/* Tab Navigation */}
      <div className="flex items-center gap-2 border-b border-[#E4DDCA] pb-3 flex-wrap">
        <button
          onClick={() => setActiveTab("TEACHERS")}
          className={`px-4 py-2 rounded-xl text-xs font-bold transition-all cursor-pointer ${
            activeTab === "TEACHERS"
              ? "bg-[#3F451F] text-[#FBF8F0] shadow-xs"
              : "text-[#77735F] hover:bg-[#EDE8D8]/50"
          }`}
        >
          Faculty Directory ({teachers.length})
        </button>

        <button
          onClick={() => setActiveTab("APPROVALS")}
          className={`px-4 py-2 rounded-xl text-xs font-bold transition-all cursor-pointer relative ${
            activeTab === "APPROVALS"
              ? "bg-[#3F451F] text-[#FBF8F0] shadow-xs"
              : "text-[#77735F] hover:bg-[#EDE8D8]/50"
          }`}
        >
          Approvals & Permissions ({requests.length})
          {pendingRequestsCount > 0 && (
            <span className="ml-1.5 px-1.5 py-0.2 bg-amber-500 text-white rounded-full text-[10px]">
              {pendingRequestsCount}
            </span>
          )}
        </button>

        <button
          onClick={() => setActiveTab("MAPPINGS")}
          className={`px-4 py-2 rounded-xl text-xs font-bold transition-all cursor-pointer ${
            activeTab === "MAPPINGS"
              ? "bg-[#3F451F] text-[#FBF8F0] shadow-xs"
              : "text-[#77735F] hover:bg-[#EDE8D8]/50"
          }`}
        >
          Curriculum Allocations ({mappings.length})
        </button>

        <button
          onClick={() => setActiveTab("DEPARTMENTS")}
          className={`px-4 py-2 rounded-xl text-xs font-bold transition-all cursor-pointer ${
            activeTab === "DEPARTMENTS"
              ? "bg-[#3F451F] text-[#FBF8F0] shadow-xs"
              : "text-[#77735F] hover:bg-[#EDE8D8]/50"
          }`}
        >
          Departments
        </button>
      </div>

      {/* TAB 1: TEACHERS DIRECTORY (Admin Can Change Name) */}
      {activeTab === "TEACHERS" && (
        <div className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl shadow-2xs overflow-hidden">
          <div className="p-4 border-b border-[#E4DDCA] flex items-center justify-between bg-[#EDE8D8]/20">
            <div>
              <h2 className="text-sm font-bold text-[#24251C]">Institutional Faculty Members</h2>
              <p className="text-xs text-[#77735F]">
                {isAdmin
                  ? "As Administrator, you can update official teacher names and manage assignments."
                  : "Institutional faculty roster."}
              </p>
            </div>
            <button
              onClick={() => void loadData()}
              className="text-xs font-bold text-[#6C5119] hover:underline cursor-pointer"
            >
              Refresh Directory
            </button>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs sm:text-sm">
              <thead>
                <tr className="border-b border-[#E4DDCA] bg-[#EDE8D8]/40 text-[#77735F] font-semibold text-[11px] uppercase tracking-wider">
                  <th className="py-3 px-4">Faculty Member</th>
                  <th className="py-3 px-4">User ID</th>
                  <th className="py-3 px-4">Email</th>
                  <th className="py-3 px-4">Assigned Subjects</th>
                  <th className="py-3 px-4 text-center">Sessions</th>
                  <th className="py-3 px-4 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#E4DDCA]/60 text-[#24251C]">
                {isLoading ? (
                  <tr>
                    <td colSpan={6} className="py-12 text-center text-[#77735F]">
                      <div className="w-6 h-6 border-2 border-[#6C5119] border-t-transparent rounded-full animate-spin mx-auto mb-2" />
                      Loading faculty directory...
                    </td>
                  </tr>
                ) : teachers.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="py-12 text-center text-[#77735F]">
                      No faculty records registered.
                    </td>
                  </tr>
                ) : (
                  teachers.map((t) => (
                    <tr key={t.user_id} className="hover:bg-[#EDE8D8]/20 transition-colors">
                      <td className="py-3 px-4 font-bold text-[#24251C]">
                        <div className="flex items-center space-x-2">
                          <div className="w-7 h-7 rounded-lg bg-[#3F451F] text-[#EDE8D8] flex items-center justify-center font-bold text-xs uppercase">
                            {t.name ? t.name.charAt(0) : t.user_id.charAt(0)}
                          </div>
                          <span>{t.name || t.user_id}</span>
                        </div>
                      </td>
                      <td className="py-3 px-4 font-mono text-xs text-[#77735F]">{t.user_id}</td>
                      <td className="py-3 px-4 text-xs text-[#77735F]">{t.email || "—"}</td>
                      <td className="py-3 px-4">
                        <div className="flex flex-wrap gap-1">
                          {t.subject_codes && t.subject_codes.length > 0 ? (
                            t.subject_codes.map((sc) => (
                              <span
                                key={sc}
                                className="px-2 py-0.5 rounded text-[10px] font-bold bg-[#EDE8D8] text-[#6C5119] border border-[#E4DDCA]"
                              >
                                {sc}
                              </span>
                            ))
                          ) : (
                            <span className="text-xs text-[#77735F] italic">No subjects</span>
                          )}
                        </div>
                      </td>
                      <td className="py-3 px-4 text-center font-semibold text-xs">
                        {t.session_count}
                      </td>
                      <td className="py-3 px-4 text-right">
                        {isAdmin ? (
                          <button
                            onClick={() => {
                              setEditNameTarget(t);
                              setNewNameInput(t.name || "");
                              setNameModalError(null);
                            }}
                            className="px-3 py-1.5 rounded-xl bg-white border border-[#E4DDCA] text-xs font-bold text-[#6C5119] hover:bg-[#EDE8D8]/50 shadow-2xs transition-colors cursor-pointer"
                          >
                            Edit Name
                          </button>
                        ) : (
                          <span className="text-xs text-[#77735F] italic">Admin Only</span>
                        )}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* TAB 2: APPROVALS & PERMISSIONS (Teacher Requests & Admin Approval) */}
      {activeTab === "APPROVALS" && (
        <div className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl shadow-2xs overflow-hidden space-y-4 p-5">
          <div className="flex items-center justify-between pb-3 border-b border-[#E4DDCA]">
            <div>
              <h2 className="text-base font-bold text-[#24251C]">Teacher Permission & Approval Requests</h2>
              <p className="text-xs text-[#77735F]">
                {isAdmin
                  ? "Teachers must seek approval from Admin for new subjects or permissions. Approving automatically assigns the subject."
                  : "Your submitted permission requests and their review status."}
              </p>
            </div>
            {!isAdmin && (
              <button
                onClick={() => setIsRequestModalOpen(true)}
                className="px-3.5 py-1.5 bg-[#6C5119] text-white text-xs font-bold rounded-xl shadow-2xs hover:bg-[#594214] cursor-pointer"
              >
                + New Request
              </button>
            )}
          </div>

          {requests.length === 0 ? (
            <div className="py-12 text-center text-[#77735F]">
              <p className="font-bold text-[#24251C]">No Permission Requests Found</p>
              <p className="text-xs mt-1">
                {isAdmin
                  ? "When a faculty member requests permission or a subject, it will appear here for your approval."
                  : "Click 'New Request' above to request permission or a subject allocation from the administrator."}
              </p>
            </div>
          ) : (
            <div className="space-y-3">
              {requests.map((req) => {
                const isPending = req.status === "PENDING";
                const isApproved = req.status === "APPROVED";

                return (
                  <div
                    key={req.request_id}
                    className="p-4 rounded-xl bg-white border border-[#E4DDCA] flex flex-col md:flex-row md:items-center justify-between gap-4 shadow-2xs"
                  >
                    <div className="space-y-1">
                      <div className="flex items-center space-x-2">
                        <span className="font-mono text-xs font-bold text-[#77735F]">
                          {req.request_id}
                        </span>
                        <span
                          className={`px-2 py-0.5 rounded text-[10px] font-black uppercase tracking-wider ${
                            isPending
                              ? "bg-amber-100 text-amber-900 border border-amber-300"
                              : isApproved
                              ? "bg-emerald-100 text-emerald-900 border border-emerald-300"
                              : "bg-rose-100 text-rose-900 border border-rose-300"
                          }`}
                        >
                          {req.status}
                        </span>
                        {req.subject_code && (
                          <span className="px-2 py-0.5 rounded text-xs font-bold bg-[#EDE8D8] text-[#6C5119]">
                            Subject: {req.subject_code}
                          </span>
                        )}
                      </div>

                      <p className="text-xs font-semibold text-[#24251C]">
                        Faculty: <span className="font-bold">{req.teacher_name || req.user_id}</span>{" "}
                        <span className="text-[#77735F]">({req.user_id})</span>
                      </p>

                      <p className="text-xs text-[#77735F]">
                        <span className="font-medium text-[#24251C]">Reason:</span> {req.reason}
                      </p>

                      <p className="text-[10px] text-[#77735F]">Submitted: {req.created_at}</p>
                    </div>

                    {/* Actions for Admin on Pending Requests */}
                    {isAdmin && isPending && (
                      <div className="flex items-center gap-2 self-start md:self-auto shrink-0">
                        <button
                          disabled={reviewingId === req.request_id}
                          onClick={() => void handleReviewRequest(req.request_id, "APPROVE")}
                          className="px-3 py-1.5 rounded-xl bg-emerald-700 hover:bg-emerald-800 text-white text-xs font-bold transition-colors shadow-2xs cursor-pointer disabled:opacity-50"
                        >
                          ✓ Approve
                        </button>
                        <button
                          disabled={reviewingId === req.request_id}
                          onClick={() => void handleReviewRequest(req.request_id, "REJECT")}
                          className="px-3 py-1.5 rounded-xl bg-rose-700 hover:bg-rose-800 text-white text-xs font-bold transition-colors shadow-2xs cursor-pointer disabled:opacity-50"
                        >
                          ✕ Reject
                        </button>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* TAB 3: CURRICULUM ALLOCATIONS */}
      {activeTab === "MAPPINGS" && (
        <div className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl overflow-hidden shadow-2xs">
          <div className="p-4 border-b border-[#E4DDCA] flex items-center justify-between bg-[#EDE8D8]/20">
            <div>
              <h2 className="text-sm font-bold text-[#24251C]">Teacher-Subject Mapping Grid</h2>
              <p className="text-xs text-[#77735F]">
                Active assignments authorizing teachers to create and verify sessions.
              </p>
            </div>
            {isAdmin && (
              <button
                onClick={() => setIsAssignOpen(true)}
                className="text-xs font-bold text-[#6C5119] hover:underline cursor-pointer"
              >
                + Assign New
              </button>
            )}
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs sm:text-sm">
              <thead>
                <tr className="border-b border-[#E4DDCA] bg-[#EDE8D8]/40 text-[#77735F] font-semibold text-[11px] uppercase tracking-wider">
                  <th className="py-3 px-4">Teacher ID</th>
                  <th className="py-3 px-4">Subject Code</th>
                  <th className="py-3 px-4">Department</th>
                  <th className="py-3 px-4 text-right">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#E4DDCA]/60 text-[#24251C]">
                {mappings.length === 0 ? (
                  <tr>
                    <td colSpan={4} className="py-12 text-center text-[#77735F]">
                      No teacher-subject allocations found.
                    </td>
                  </tr>
                ) : (
                  mappings.map((m, idx) => {
                    const uid = m.user_id || m.teacher_id;
                    const subMeta = KNOWN_SUBJECTS[m.subject_code];
                    return (
                      <tr key={`${uid}-${m.subject_code}-${idx}`} className="hover:bg-[#EDE8D8]/20">
                        <td className="py-3 px-4 font-mono font-bold text-xs">{uid}</td>
                        <td className="py-3 px-4">
                          <span className="font-bold text-[#6C5119]">{m.subject_code}</span>
                          {subMeta && (
                            <span className="text-xs text-[#77735F] block">{subMeta.name}</span>
                          )}
                        </td>
                        <td className="py-3 px-4 text-xs text-[#77735F]">
                          {subMeta ? subMeta.branch : "General"}
                        </td>
                        <td className="py-3 px-4 text-right">
                          {isAdmin ? (
                            <button
                              onClick={() => setPendingRemoval(m)}
                              className="text-xs text-rose-700 hover:underline font-bold cursor-pointer"
                            >
                              Unassign
                            </button>
                          ) : (
                            <span className="text-xs text-[#77735F] italic">Admin Only</span>
                          )}
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* TAB 4: DEPARTMENTS */}
      {activeTab === "DEPARTMENTS" && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {DEPARTMENTS.map((dept) => (
            <div
              key={dept.code}
              className="p-5 rounded-2xl bg-[#FBF8F0] border border-[#E4DDCA] shadow-2xs space-y-3"
            >
              <div className="flex items-center justify-between">
                <span className="px-2.5 py-1 rounded-md text-xs font-black bg-[#EDE8D8] text-[#6C5119]">
                  {dept.code}
                </span>
                <span className="text-xs text-[#77735F] font-semibold">
                  {dept.totalFaculty} Faculty
                </span>
              </div>
              <h3 className="font-bold text-base text-[#24251C]">{dept.name}</h3>
              <p className="text-xs text-[#77735F]">Coordinator: {dept.coordinator}</p>
              <div className="flex flex-wrap gap-1 pt-2">
                {dept.activeSubjects.map((s) => (
                  <span
                    key={s}
                    className="px-2 py-0.5 rounded text-[10px] font-bold bg-white border border-[#E4DDCA] text-[#24251C]"
                  >
                    {s}
                  </span>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* MODAL 1: Admin Edit Teacher Name */}
      {editNameTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40 backdrop-blur-[2px]">
          <div className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl p-6 max-w-md w-full shadow-xl space-y-4">
            <div className="flex items-center justify-between pb-2 border-b border-[#E4DDCA]">
              <h3 className="text-base font-bold text-[#24251C]">Edit Teacher Official Name</h3>
              <button
                onClick={() => setEditNameTarget(null)}
                className="text-[#77735F] hover:text-[#24251C] text-sm cursor-pointer"
              >
                ✕
              </button>
            </div>

            <p className="text-xs text-[#77735F]">
              As Administrator, you have exclusive authority to alter official teacher names in the
              institutional registry.
            </p>

            {nameModalError && (
              <div className="p-2.5 rounded-xl bg-rose-50 text-rose-800 text-xs font-semibold">
                {nameModalError}
              </div>
            )}

            <form onSubmit={handleSaveTeacherName} className="space-y-4">
              <div>
                <label className="block text-xs font-bold text-[#77735F] uppercase mb-1">
                  Faculty User ID
                </label>
                <input
                  type="text"
                  disabled
                  value={editNameTarget.user_id}
                  className="w-full px-3 py-2 rounded-xl bg-stone-100 border border-[#E4DDCA] text-xs font-mono text-[#77735F]"
                />
              </div>

              <div>
                <label className="block text-xs font-bold text-[#77735F] uppercase mb-1">
                  Official Full Name
                </label>
                <input
                  type="text"
                  required
                  value={newNameInput}
                  onChange={(e) => setNewNameInput(e.target.value)}
                  placeholder="e.g. Dr. Machine Learning"
                  className="w-full px-3.5 py-2 rounded-xl bg-white border border-[#E4DDCA] text-sm text-[#24251C] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#6C5119]"
                />
              </div>

              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setEditNameTarget(null)}
                  className="px-4 py-2 rounded-xl border border-[#E4DDCA] text-xs font-bold text-[#77735F] hover:bg-[#EDE8D8]/50 cursor-pointer"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isUpdatingName || !newNameInput.trim()}
                  className="px-4 py-2 rounded-xl bg-[#3F451F] text-[#FBF8F0] text-xs font-bold hover:bg-[#323719] disabled:opacity-50 cursor-pointer"
                >
                  {isUpdatingName ? "Saving..." : "Save Name"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* MODAL 2: Teacher Request Permission */}
      {isRequestModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40 backdrop-blur-[2px]">
          <div className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl p-6 max-w-md w-full shadow-xl space-y-4">
            <div className="flex items-center justify-between pb-2 border-b border-[#E4DDCA]">
              <h3 className="text-base font-bold text-[#24251C]">Request Subject Permission</h3>
              <button
                onClick={() => setIsRequestModalOpen(false)}
                className="text-[#77735F] hover:text-[#24251C] text-sm cursor-pointer"
              >
                ✕
              </button>
            </div>

            <p className="text-xs text-[#77735F]">
              Submit a request to the Administrator to be assigned a new subject or to request elevated
              permission.
            </p>

            <form onSubmit={handleRequestPermission} className="space-y-4">
              <div>
                <label className="block text-xs font-bold text-[#77735F] uppercase mb-1">
                  Subject Code
                </label>
                <select
                  value={requestSubject}
                  onChange={(e) => setRequestSubject(e.target.value)}
                  className="w-full px-3 py-2 rounded-xl bg-white border border-[#E4DDCA] text-xs font-bold text-[#24251C] cursor-pointer"
                >
                  {Object.keys(KNOWN_SUBJECTS).map((code) => (
                    <option key={code} value={code}>
                      {code} — {KNOWN_SUBJECTS[code].name}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="block text-xs font-bold text-[#77735F] uppercase mb-1">
                  Justification / Reason
                </label>
                <textarea
                  required
                  rows={3}
                  value={requestReason}
                  onChange={(e) => setRequestReason(e.target.value)}
                  placeholder="Explain why you require permission or allocation for this subject..."
                  className="w-full px-3.5 py-2 rounded-xl bg-white border border-[#E4DDCA] text-xs text-[#24251C] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#6C5119]"
                />
              </div>

              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setIsRequestModalOpen(false)}
                  className="px-4 py-2 rounded-xl border border-[#E4DDCA] text-xs font-bold text-[#77735F] hover:bg-[#EDE8D8]/50 cursor-pointer"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isSubmittingRequest || !requestReason.trim()}
                  className="px-4 py-2 rounded-xl bg-[#6C5119] text-white text-xs font-bold hover:bg-[#594214] disabled:opacity-50 cursor-pointer"
                >
                  {isSubmittingRequest ? "Submitting..." : "Submit to Admin"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* MODAL 3: Admin Assign Subject */}
      {isAssignOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40 backdrop-blur-[2px]">
          <div className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl p-6 max-w-md w-full shadow-xl space-y-4">
            <div className="flex items-center justify-between pb-2 border-b border-[#E4DDCA]">
              <h3 className="text-base font-bold text-[#24251C]">Assign Subject to Teacher</h3>
              <button
                onClick={() => setIsAssignOpen(false)}
                className="text-[#77735F] hover:text-[#24251C] text-sm cursor-pointer"
              >
                ✕
              </button>
            </div>

            {assignError && (
              <div className="p-2.5 rounded-xl bg-rose-50 text-rose-800 text-xs font-semibold">
                {assignError}
              </div>
            )}

            <form onSubmit={handleAssignSubject} className="space-y-4">
              <div>
                <label className="block text-xs font-bold text-[#77735F] uppercase mb-1">
                  Select Teacher
                </label>
                <select
                  value={selectedTeacherId}
                  onChange={(e) => setSelectedTeacherId(e.target.value)}
                  className="w-full px-3 py-2 rounded-xl bg-white border border-[#E4DDCA] text-xs font-bold text-[#24251C] cursor-pointer"
                >
                  {teachers.map((t) => (
                    <option key={t.user_id} value={t.user_id}>
                      {t.name} ({t.user_id})
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="block text-xs font-bold text-[#77735F] uppercase mb-1">
                  Subject Code
                </label>
                <select
                  value={selectedSubjectCode}
                  onChange={(e) => setSelectedSubjectCode(e.target.value)}
                  className="w-full px-3 py-2 rounded-xl bg-white border border-[#E4DDCA] text-xs font-bold text-[#24251C] cursor-pointer"
                >
                  {Object.keys(KNOWN_SUBJECTS).map((code) => (
                    <option key={code} value={code}>
                      {code} — {KNOWN_SUBJECTS[code].name}
                    </option>
                  ))}
                </select>
              </div>

              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setIsAssignOpen(false)}
                  className="px-4 py-2 rounded-xl border border-[#E4DDCA] text-xs font-bold text-[#77735F] hover:bg-[#EDE8D8]/50 cursor-pointer"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isSubmittingAssign}
                  className="px-4 py-2 rounded-xl bg-[#3F451F] text-[#FBF8F0] text-xs font-bold hover:bg-[#323719] disabled:opacity-50 cursor-pointer"
                >
                  {isSubmittingAssign ? "Assigning..." : "Assign Subject"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* MODAL 4: Unassign Confirmation */}
      {pendingRemoval && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40 backdrop-blur-[2px]">
          <div className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl p-6 max-w-sm w-full shadow-xl space-y-4">
            <h3 className="text-base font-bold text-[#24251C]">Confirm Unassignment</h3>
            <p className="text-xs text-[#77735F]">
              Are you sure you want to unassign subject{" "}
              <span className="font-bold text-[#24251C]">{pendingRemoval.subject_code}</span> from
              teacher{" "}
              <span className="font-bold text-[#24251C]">
                {pendingRemoval.user_id || pendingRemoval.teacher_id}
              </span>
              ?
            </p>
            <div className="flex justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={() => setPendingRemoval(null)}
                className="px-4 py-2 rounded-xl border border-[#E4DDCA] text-xs font-bold text-[#77735F] hover:bg-[#EDE8D8]/50 cursor-pointer"
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={isRemoving}
                onClick={() => void handleRemoveSubject()}
                className="px-4 py-2 rounded-xl bg-rose-700 text-white text-xs font-bold hover:bg-rose-800 disabled:opacity-50 cursor-pointer"
              >
                {isRemoving ? "Unassigning..." : "Yes, Unassign"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
