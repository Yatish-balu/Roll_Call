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
  createTeacherAccount,
  toggleTeacherActive,
  type TeacherSubjectMapping,
  type AdminTeacherItem,
  type PermissionRequestItem,
  KNOWN_SUBJECTS,
} from "@/services/api/faculty";
import {
  fetchAttendanceUnlockRequests,
  reviewAttendanceUnlockRequest,
  type AttendanceUnlockRequest,
} from "@/services/api/attendance";
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
  const [unlockRequests, setUnlockRequests] = useState<AttendanceUnlockRequest[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [feedbackMessage, setFeedbackMessage] = useState<{
    type: "success" | "error" | "info";
    text: string;
  } | null>(null);

  // Active Tab: TEACHERS | APPROVALS | MAPPINGS | DEPARTMENTS
  const [activeTab, setActiveTab] = useState<"TEACHERS" | "APPROVALS" | "MAPPINGS" | "DEPARTMENTS">("TEACHERS");
  const [approvalFilter, setApprovalFilter] = useState<"ALL" | "UNLOCKS" | "SUBJECTS" | "RESOLVED">("ALL");

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

  // Full Teacher Profile View Modal (Admin & Directory)
  const [viewingProfileTeacher, setViewingProfileTeacher] = useState<AdminTeacherItem | null>(null);

  // Reviewing a Request
  const [reviewingId, setReviewingId] = useState<string | null>(null);
  const [reviewingUnlockId, setReviewingUnlockId] = useState<string | null>(null);

  // Add New Teacher Modal
  const [isAddTeacherOpen, setIsAddTeacherOpen] = useState(false);
  const [addTeacherForm, setAddTeacherForm] = useState({
    user_id: "",
    name: "",
    email: "",
    password: "",
    branch: "",
    designation: "",
    department: "",
  });
  const [showAddPassword, setShowAddPassword] = useState(false);
  const [isSubmittingAddTeacher, setIsSubmittingAddTeacher] = useState(false);
  const [addTeacherError, setAddTeacherError] = useState<string | null>(null);

  // Toggle active tracking (userId → loading)
  const [togglingActiveId, setTogglingActiveId] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const promises: Array<Promise<unknown>> = [
        fetchTeacherSubjects().catch(() => ({ total: 0, items: [] })),
        fetchPermissionRequests().catch(() => ({ total: 0, items: [] })),
        fetchAttendanceUnlockRequests().catch(() => []),
      ];
      if (isAdmin) {
        promises.push(fetchAdminTeachers().catch(() => ({ total: 0, items: [] })));
      }

      const [mapRes, reqRes, unlockRes, teachRes] = await Promise.all(promises);
      const mItems = (mapRes as { items: TeacherSubjectMapping[] })?.items || [];
      const rItems = (reqRes as { items: PermissionRequestItem[] })?.items || [];
      const uItems = (unlockRes as AttendanceUnlockRequest[]) || [];
      const tItems = (teachRes as { items: AdminTeacherItem[] })?.items || [];

      setMappings(mItems);
      setRequests(rItems);
      setUnlockRequests(uItems);
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
    void loadData();
    const handleSync = () => {
      void loadData();
    };
    window.addEventListener("rollcall-unlock-request-updated", handleSync);
    window.addEventListener("rollcall-attendance-updated", handleSync);
    return () => {
      window.removeEventListener("rollcall-unlock-request-updated", handleSync);
      window.removeEventListener("rollcall-attendance-updated", handleSync);
    };
  }, [loadData]);

  const pendingSubjectRequests = useMemo(() => requests.filter((r) => r.status === "PENDING"), [requests]);
  const pendingUnlockRequests = useMemo(() => unlockRequests.filter((r) => r.status === "PENDING"), [unlockRequests]);
  const totalPendingCount = pendingSubjectRequests.length + pendingUnlockRequests.length;
  const activeTeachersCount = useMemo(() => teachers.filter((t) => t.is_active).length, [teachers]);
  const totalSessionCount = useMemo(() => teachers.reduce((acc, t) => acc + (t.session_count || 0), 0), [teachers]);

  const handleReviewUnlock = async (requestId: string, decision: "APPROVED" | "REJECTED") => {
    setReviewingUnlockId(requestId);
    try {
      await reviewAttendanceUnlockRequest(requestId, {
        decision,
        unlock_hours: 24,
        admin_notes: decision === "APPROVED" ? "Approved from Admin Command Center" : "Rejected from Admin Command Center",
      });
      setFeedbackMessage({
        type: "success",
        text: `Attendance unlock request ${decision === "APPROVED" ? "approved (24h edit window unlocked)" : "declined"}.`,
      });
      window.dispatchEvent(new CustomEvent("rollcall-unlock-request-updated"));
      window.dispatchEvent(new CustomEvent("rollcall-attendance-updated"));
      await loadData();
    } catch (err: unknown) {
      setFeedbackMessage({
        type: "error",
        text: err instanceof Error ? err.message : "Failed to review unlock request.",
      });
    } finally {
      setReviewingUnlockId(null);
    }
  };

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

  // Handle Add New Teacher
  const handleAddTeacher = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!addTeacherForm.user_id.trim() || !addTeacherForm.name.trim() || !addTeacherForm.email.trim() || !addTeacherForm.password.trim()) return;
    setIsSubmittingAddTeacher(true);
    setAddTeacherError(null);
    try {
      await createTeacherAccount({
        user_id: addTeacherForm.user_id.trim(),
        name: addTeacherForm.name.trim(),
        email: addTeacherForm.email.trim(),
        password: addTeacherForm.password,
        branch: addTeacherForm.branch.trim() || undefined,
        designation: addTeacherForm.designation.trim() || undefined,
        department: addTeacherForm.department.trim() || undefined,
      });
      setFeedbackMessage({
        type: "success",
        text: `Faculty account '${addTeacherForm.name.trim()}' (${addTeacherForm.user_id.trim()}) created successfully.`,
      });
      setIsAddTeacherOpen(false);
      setAddTeacherForm({ user_id: "", name: "", email: "", password: "", branch: "", designation: "", department: "" });
      await loadData();
    } catch (err: unknown) {
      setAddTeacherError(err instanceof Error ? err.message : "Failed to create teacher account.");
    } finally {
      setIsSubmittingAddTeacher(false);
    }
  };

  // Handle Toggle Active
  const handleToggleActive = async (t: AdminTeacherItem) => {
    const action = t.is_active ? "deactivate" : "activate";
    if (!window.confirm(`Are you sure you want to ${action} ${t.name || t.user_id}?`)) return;
    setTogglingActiveId(t.user_id);
    try {
      const res = await toggleTeacherActive(t.user_id);
      setTeachers((prev) =>
        prev.map((item) =>
          item.user_id === t.user_id ? { ...item, is_active: res.is_active } : item
        )
      );
      setFeedbackMessage({
        type: "success",
        text: res.message || `Teacher ${t.user_id} ${res.is_active ? "activated" : "deactivated"}.`,
      });
    } catch (err: unknown) {
      setFeedbackMessage({
        type: "error",
        text: err instanceof Error ? err.message : "Failed to toggle teacher status.",
      });
    } finally {
      setTogglingActiveId(null);
    }
  };

  return (
    <div className="space-y-6 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-2">
        <div>
          <div className="flex items-center space-x-2.5 flex-wrap">
            <h1 className="text-2xl sm:text-3xl font-extrabold text-[#24251C] tracking-tight">
              {isAdmin ? "Admin Command Center" : "Faculty & Academic Directory"}
            </h1>
            <span className="px-2.5 py-0.5 rounded-full text-xs font-bold bg-[#EDE8D8] text-[#6C5119] border border-[#E4DDCA]">
              {isAdmin ? "Institutional Governance" : "Faculty Workspace"}
            </span>
            {totalPendingCount > 0 && (
              <span className="px-2.5 py-0.5 rounded-full text-xs font-black bg-amber-100 text-amber-900 border border-amber-300 animate-pulse">
                {totalPendingCount} Action Item{totalPendingCount > 1 ? "s" : ""} Requiring Review
              </span>
            )}
          </div>
          <p className="text-xs sm:text-sm text-[#77735F] mt-1">
            {isAdmin
              ? "Centralized administrative cockpit for faculty profiles, 24-hour attendance unlocks, subject allocations, and institutional oversight."
              : "Faculty accounts, assigned subjects, and administrative permission requests."}
          </p>
        </div>

        <div className="flex items-center gap-2">
          {isAdmin ? (
            <>
              <button
                onClick={() => setIsAddTeacherOpen(true)}
                className="inline-flex items-center gap-1.5 px-4 py-2 bg-[#6C5119] text-[#FBF8F0] text-xs font-bold rounded-xl hover:bg-[#594214] transition-all shadow-2xs cursor-pointer"
              >
                <span>+ Add New Faculty</span>
              </button>
              <button
                onClick={() => setIsAssignOpen(true)}
                className="inline-flex items-center gap-1.5 px-4 py-2 bg-[#3F451F] text-[#FBF8F0] text-xs font-bold rounded-xl hover:bg-[#323719] transition-all shadow-2xs cursor-pointer"
              >
                <span>+ Assign Subject</span>
              </button>
            </>
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

      {/* Admin KPI & Intelligence Overview Strip */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3.5">
        <div className="p-4 rounded-2xl bg-[#FBF8F0] border border-[#E4DDCA] shadow-2xs">
          <div className="flex items-center justify-between text-xs font-bold text-[#77735F]">
            <span>FACULTY ROSTER</span>
            <span className="text-base">👨‍🏫</span>
          </div>
          <div className="mt-2 flex items-baseline gap-2">
            <span className="text-2xl font-black text-[#24251C]">{teachers.length}</span>
            <span className="text-xs font-bold text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded-full border border-emerald-200">
              {activeTeachersCount} Active
            </span>
          </div>
          <p className="text-[11px] text-[#77735F] mt-1">Verified institutional teaching staff</p>
        </div>

        <div
          onClick={() => setActiveTab("APPROVALS")}
          className={`p-4 rounded-2xl border shadow-2xs cursor-pointer transition-all ${
            totalPendingCount > 0
              ? "bg-amber-50/90 border-amber-300 hover:bg-amber-100/80"
              : "bg-[#FBF8F0] border-[#E4DDCA] hover:bg-[#EDE8D8]/30"
          }`}
        >
          <div className="flex items-center justify-between text-xs font-bold text-[#77735F]">
            <span>PENDING APPROVALS</span>
            <span className="text-base">📥</span>
          </div>
          <div className="mt-2 flex items-baseline gap-2">
            <span className={`text-2xl font-black ${totalPendingCount > 0 ? "text-amber-900" : "text-[#24251C]"}`}>
              {totalPendingCount}
            </span>
            {totalPendingCount > 0 ? (
              <span className="text-xs font-bold text-amber-900 bg-amber-200/80 px-2 py-0.5 rounded-full animate-pulse border border-amber-300">
                Action Needed
              </span>
            ) : (
              <span className="text-xs font-semibold text-stone-500">All Clear</span>
            )}
          </div>
          <p className="text-[11px] text-[#77735F] mt-1">
            {pendingUnlockRequests.length} edit unlock{pendingUnlockRequests.length === 1 ? "" : "s"} • {pendingSubjectRequests.length} subject request{pendingSubjectRequests.length === 1 ? "" : "s"}
          </p>
        </div>

        <div className="p-4 rounded-2xl bg-[#FBF8F0] border border-[#E4DDCA] shadow-2xs">
          <div className="flex items-center justify-between text-xs font-bold text-[#77735F]">
            <span>COURSE ALLOCATIONS</span>
            <span className="text-base">📚</span>
          </div>
          <div className="mt-2 flex items-baseline gap-2">
            <span className="text-2xl font-black text-[#24251C]">{mappings.length}</span>
            <span className="text-xs font-semibold text-[#77735F]">Active mappings</span>
          </div>
          <p className="text-[11px] text-[#77735F] mt-1">Across {DEPARTMENTS.length} academic departments</p>
        </div>

        <div className="p-4 rounded-2xl bg-[#FBF8F0] border border-[#E4DDCA] shadow-2xs">
          <div className="flex items-center justify-between text-xs font-bold text-[#77735F]">
            <span>SESSIONS CONDUCTED</span>
            <span className="text-base">⏱️</span>
          </div>
          <div className="mt-2 flex items-baseline gap-2">
            <span className="text-2xl font-black text-[#24251C]">{totalSessionCount}</span>
            <span className="text-xs font-semibold text-emerald-700">Verified logs</span>
          </div>
          <p className="text-[11px] text-[#77735F] mt-1">Total recorded classroom roll calls</p>
        </div>
      </div>

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
          👨‍🏫 Faculty Directory ({teachers.length})
        </button>

        <button
          onClick={() => setActiveTab("APPROVALS")}
          className={`px-4 py-2 rounded-xl text-xs font-bold transition-all cursor-pointer relative ${
            activeTab === "APPROVALS"
              ? "bg-[#3F451F] text-[#FBF8F0] shadow-xs"
              : "text-[#77735F] hover:bg-[#EDE8D8]/50"
          }`}
        >
          📥 Approvals & Action Items ({totalPendingCount})
          {totalPendingCount > 0 && (
            <span className="ml-1.5 px-1.5 py-0.2 bg-amber-500 text-white rounded-full text-[10px] animate-pulse">
              {totalPendingCount}
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
          📚 Subject Allocations ({mappings.length})
        </button>

        <button
          onClick={() => setActiveTab("DEPARTMENTS")}
          className={`px-4 py-2 rounded-xl text-xs font-bold transition-all cursor-pointer ${
            activeTab === "DEPARTMENTS"
              ? "bg-[#3F451F] text-[#FBF8F0] shadow-xs"
              : "text-[#77735F] hover:bg-[#EDE8D8]/50"
          }`}
        >
          🏛️ Departments ({DEPARTMENTS.length})
        </button>
      </div>

      {/* TAB 1: TEACHERS DIRECTORY (With Pending Request Badges and Integrated Action) */}
      {activeTab === "TEACHERS" && (
        <div className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl shadow-2xs overflow-hidden">
          <div className="p-4 border-b border-[#E4DDCA] flex flex-col sm:flex-row sm:items-center justify-between gap-2 bg-[#EDE8D8]/20">
            <div>
              <h2 className="text-sm font-bold text-[#24251C]">Institutional Faculty Members</h2>
              <p className="text-xs text-[#77735F]">
                {isAdmin
                  ? "View faculty details, pending requests, proctored students, or toggle active status."
                  : "Institutional faculty roster."}
              </p>
            </div>
            <button
              onClick={() => void loadData()}
              className="text-xs font-bold text-[#6C5119] hover:underline cursor-pointer self-start sm:self-auto"
            >
              🔄 Refresh Directory
            </button>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs sm:text-sm">
              <thead>
                <tr className="border-b border-[#E4DDCA] bg-[#EDE8D8]/40 text-[#77735F] font-semibold text-[11px] uppercase tracking-wider">
                  <th className="py-3 px-4">Faculty Member</th>
                  <th className="py-3 px-4">User ID & Contact</th>
                  <th className="py-3 px-4">Assigned Subjects</th>
                  <th className="py-3 px-4 text-center">Requests</th>
                  <th className="py-3 px-4 text-center">Status</th>
                  <th className="py-3 px-4 text-center">Sessions</th>
                  <th className="py-3 px-4 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#E4DDCA]/60 text-[#24251C]">
                {isLoading ? (
                  <tr>
                    <td colSpan={7} className="py-12 text-center text-[#77735F]">
                      <div className="w-6 h-6 border-2 border-[#6C5119] border-t-transparent rounded-full animate-spin mx-auto mb-2" />
                      Loading faculty directory...
                    </td>
                  </tr>
                ) : teachers.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="py-12 text-center text-[#77735F]">
                      No faculty records registered.
                    </td>
                  </tr>
                ) : (
                  teachers.map((t) => {
                    const teacherUnlocks = unlockRequests.filter(
                      (u) => (u.teacher_id === t.user_id || u.teacher_name === t.name) && u.status === "PENDING"
                    );
                    const teacherSubjectsReq = requests.filter(
                      (r) => r.user_id === t.user_id && r.status === "PENDING"
                    );
                    const pendingForThisTeacher = teacherUnlocks.length + teacherSubjectsReq.length;

                    return (
                      <tr key={t.user_id} className="hover:bg-[#EDE8D8]/20 transition-colors">
                        <td className="py-3 px-4 font-bold text-[#24251C]">
                          <div className="flex items-center space-x-2.5">
                            <div className="w-8 h-8 rounded-lg bg-[#3F451F] text-[#EDE8D8] flex items-center justify-center font-bold text-xs uppercase shrink-0">
                              {t.name ? t.name.charAt(0) : t.user_id.charAt(0)}
                            </div>
                            <div>
                              <div className="flex items-center gap-1.5 flex-wrap">
                                <span>{t.name || t.user_id}</span>
                                {pendingForThisTeacher > 0 && (
                                  <span className="px-1.5 py-0.5 rounded text-[10px] font-black bg-amber-100 text-amber-900 border border-amber-300 animate-pulse">
                                    {pendingForThisTeacher} Pending
                                  </span>
                                )}
                              </div>
                              <span className="text-[11px] text-[#77735F] font-normal block">
                                {t.designation || "Faculty"} • {t.branch || "General"}
                              </span>
                            </div>
                          </div>
                        </td>
                        <td className="py-3 px-4">
                          <p className="font-mono text-xs font-semibold text-[#24251C]">{t.user_id}</p>
                          <p className="text-xs text-[#77735F]">{t.email || "—"}</p>
                          {t.mobile && <p className="text-[10px] text-[#77735F]">{t.mobile}</p>}
                        </td>
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
                        <td className="py-3 px-4 text-center">
                          {pendingForThisTeacher > 0 ? (
                            <button
                              onClick={() => setViewingProfileTeacher(t)}
                              className="px-2 py-1 rounded-full text-[10px] font-bold bg-amber-100 text-amber-900 border border-amber-300 hover:bg-amber-200 transition-colors cursor-pointer"
                              title="Click to review pending requests for this teacher"
                            >
                              ⏳ {pendingForThisTeacher} Action Needed
                            </button>
                          ) : (
                            <span className="text-xs text-stone-400 font-medium">None</span>
                          )}
                        </td>
                        <td className="py-3 px-4 text-center">
                          {isAdmin ? (
                            <button
                              type="button"
                              disabled={togglingActiveId === t.user_id}
                              onClick={() => handleToggleActive(t)}
                              title="Click to toggle teacher active/inactive status"
                              className={`px-2.5 py-1 rounded-full text-[10px] font-bold transition-all shadow-2xs cursor-pointer disabled:opacity-50 ${
                                t.is_active
                                  ? "bg-emerald-100 text-emerald-800 border border-emerald-300 hover:bg-emerald-200"
                                  : "bg-rose-100 text-rose-800 border border-rose-300 hover:bg-rose-200"
                              }`}
                            >
                              {togglingActiveId === t.user_id ? "..." : t.is_active ? "● Active" : "○ Inactive"}
                            </button>
                          ) : (
                            <span
                              className={`px-2 py-0.5 rounded-full text-[10px] font-bold ${
                                t.is_active
                                  ? "bg-emerald-50 text-emerald-700 border border-emerald-200"
                                  : "bg-rose-50 text-rose-700 border border-rose-200"
                              }`}
                            >
                              {t.is_active ? "Active" : "Inactive"}
                            </span>
                          )}
                        </td>
                        <td className="py-3 px-4 text-center font-semibold text-xs">
                          {t.session_count || 0}
                        </td>
                        <td className="py-3 px-4 text-right">
                          <div className="flex items-center justify-end gap-1.5">
                            <button
                              onClick={() => setViewingProfileTeacher(t)}
                              className={`px-3 py-1.5 rounded-xl text-xs font-bold transition-colors cursor-pointer ${
                                pendingForThisTeacher > 0
                                  ? "bg-amber-600 text-white hover:bg-amber-700 shadow-xs"
                                  : "bg-[#EDE8D8] text-[#24251C] hover:bg-[#E4DDCA]"
                              }`}
                              title="View complete faculty profile, contact, proctored students, and review pending approvals"
                            >
                              {pendingForThisTeacher > 0 ? "Review & Details" : "Details"}
                            </button>
                            {isAdmin && (
                              <button
                                onClick={() => {
                                  setEditNameTarget(t);
                                  setNewNameInput(t.name || "");
                                  setNameModalError(null);
                                }}
                                className="px-2.5 py-1.5 rounded-xl bg-white border border-[#E4DDCA] text-xs font-bold text-[#6C5119] hover:bg-[#EDE8D8]/50 shadow-2xs transition-colors cursor-pointer"
                              >
                                Edit Name
                              </button>
                            )}
                          </div>
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

      {/* TAB 2: UNIFIED APPROVALS & ACTION ITEMS INBOX */}
      {activeTab === "APPROVALS" && (
        <div className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl shadow-2xs overflow-hidden space-y-4 p-5">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-[#E4DDCA]">
            <div>
              <h2 className="text-base font-bold text-[#24251C]">Unified Approvals & Permissions Hub</h2>
              <p className="text-xs text-[#77735F]">
                {isAdmin
                  ? "Review 24-hour attendance edit unlock requests and subject allocation permissions in one unified inbox."
                  : "Your submitted attendance unlock and permission requests."}
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

          {/* Sub-Filters for Approvals */}
          <div className="flex items-center gap-2 flex-wrap">
            <button
              onClick={() => setApprovalFilter("ALL")}
              className={`px-3 py-1 rounded-xl text-xs font-bold transition-all cursor-pointer ${
                approvalFilter === "ALL"
                  ? "bg-[#3F451F] text-[#FBF8F0]"
                  : "bg-white border border-[#E4DDCA] text-[#77735F] hover:bg-[#EDE8D8]/40"
              }`}
            >
              All Action Items ({totalPendingCount})
            </button>
            <button
              onClick={() => setApprovalFilter("UNLOCKS")}
              className={`px-3 py-1 rounded-xl text-xs font-bold transition-all cursor-pointer ${
                approvalFilter === "UNLOCKS"
                  ? "bg-[#3F451F] text-[#FBF8F0]"
                  : "bg-white border border-[#E4DDCA] text-[#77735F] hover:bg-[#EDE8D8]/40"
              }`}
            >
              Attendance 24h Unlocks ({pendingUnlockRequests.length})
            </button>
            <button
              onClick={() => setApprovalFilter("SUBJECTS")}
              className={`px-3 py-1 rounded-xl text-xs font-bold transition-all cursor-pointer ${
                approvalFilter === "SUBJECTS"
                  ? "bg-[#3F451F] text-[#FBF8F0]"
                  : "bg-white border border-[#E4DDCA] text-[#77735F] hover:bg-[#EDE8D8]/40"
              }`}
            >
              Subject Allocations ({pendingSubjectRequests.length})
            </button>
            <button
              onClick={() => setApprovalFilter("RESOLVED")}
              className={`px-3 py-1 rounded-xl text-xs font-bold transition-all cursor-pointer ${
                approvalFilter === "RESOLVED"
                  ? "bg-[#3F451F] text-[#FBF8F0]"
                  : "bg-white border border-[#E4DDCA] text-[#77735F] hover:bg-[#EDE8D8]/40"
              }`}
            >
              Resolved History ({requests.length + unlockRequests.length - totalPendingCount})
            </button>
          </div>

          {/* Display Attendance Unlock Requests */}
          {(approvalFilter === "ALL" || approvalFilter === "UNLOCKS" || approvalFilter === "RESOLVED") && (
            <div className="space-y-3">
              {approvalFilter !== "ALL" && (
                <h3 className="text-xs font-black uppercase tracking-wider text-[#6C5119]">
                  Attendance Edit Window (24h Lock) Requests
                </h3>
              )}
              {unlockRequests
                .filter((u) => (approvalFilter === "RESOLVED" ? u.status !== "PENDING" : u.status === "PENDING"))
                .map((req) => {
                  const isPending = req.status === "PENDING";
                  const isApproved = req.status === "APPROVED";
                  const matchingTeacher = teachers.find(
                    (t) => t.user_id === req.teacher_id || t.name === req.teacher_name
                  );

                  return (
                    <div
                      key={req.request_id}
                      className="p-4 rounded-xl bg-white border border-[#E4DDCA] flex flex-col md:flex-row md:items-center justify-between gap-4 shadow-2xs hover:border-[#6C5119]/40 transition-colors"
                    >
                      <div className="space-y-1.5">
                        <div className="flex items-center space-x-2 flex-wrap">
                          <span className="px-2 py-0.5 rounded text-[10px] font-black uppercase tracking-wider bg-purple-100 text-purple-900 border border-purple-300">
                            Attendance Unlock
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
                          <span className="text-xs text-[#77735F] font-mono">Session ID: {req.session_id}</span>
                        </div>

                        <p className="text-xs font-semibold text-[#24251C]">
                          Faculty:{" "}
                          <span className="font-bold text-[#6C5119]">
                            {req.teacher_name || req.teacher_id}
                          </span>{" "}
                          <span className="text-[#77735F]">({req.teacher_id})</span>
                          {matchingTeacher && (
                            <button
                              onClick={() => setViewingProfileTeacher(matchingTeacher)}
                              className="ml-2 text-[11px] text-[#6C5119] underline font-bold cursor-pointer"
                            >
                              [View Teacher Profile]
                            </button>
                          )}
                        </p>

                        <div className="p-2.5 rounded-lg bg-[#FBF8F0] border border-[#E4DDCA] text-xs">
                          <span className="font-bold text-[#24251C]">Teacher's Justification: </span>
                          <span className="italic font-medium text-[#6C5119]">"{req.reason}"</span>
                        </div>

                        <div className="flex items-center gap-3 text-[10px] text-[#77735F]">
                          <span>Requested: {new Date(req.created_at).toLocaleString()}</span>
                          {req.reviewed_at && <span>Reviewed: {new Date(req.reviewed_at).toLocaleString()}</span>}
                          {req.expires_at && (
                            <span className="text-emerald-700 font-bold">
                              Unlocked Until: {new Date(req.expires_at).toLocaleString()}
                            </span>
                          )}
                        </div>
                      </div>

                      {/* Admin Actions on Pending Attendance Unlock */}
                      {isAdmin && isPending && (
                        <div className="flex items-center gap-2 self-start md:self-auto shrink-0">
                          <button
                            disabled={reviewingUnlockId === req.request_id}
                            onClick={() => void handleReviewUnlock(req.request_id, "APPROVED")}
                            className="px-3.5 py-1.5 rounded-xl bg-emerald-700 hover:bg-emerald-800 text-white text-xs font-bold transition-all shadow-2xs cursor-pointer disabled:opacity-50"
                          >
                            ✓ Approve (24h Unlock)
                          </button>
                          <button
                            disabled={reviewingUnlockId === req.request_id}
                            onClick={() => void handleReviewUnlock(req.request_id, "REJECTED")}
                            className="px-3 py-1.5 rounded-xl bg-rose-700 hover:bg-rose-800 text-white text-xs font-bold transition-all shadow-2xs cursor-pointer disabled:opacity-50"
                          >
                            ✕ Decline
                          </button>
                        </div>
                      )}
                    </div>
                  );
                })}
            </div>
          )}

          {/* Display Subject Allocation Permission Requests */}
          {(approvalFilter === "ALL" || approvalFilter === "SUBJECTS" || approvalFilter === "RESOLVED") && (
            <div className="space-y-3 pt-2">
              {approvalFilter !== "ALL" && (
                <h3 className="text-xs font-black uppercase tracking-wider text-[#6C5119]">
                  Subject Curriculum Permission Requests
                </h3>
              )}
              {requests
                .filter((r) => (approvalFilter === "RESOLVED" ? r.status !== "PENDING" : r.status === "PENDING"))
                .map((req) => {
                  const isPending = req.status === "PENDING";
                  const isApproved = req.status === "APPROVED";
                  const matchingTeacher = teachers.find(
                    (t) => t.user_id === req.user_id || t.name === req.teacher_name
                  );

                  return (
                    <div
                      key={req.request_id}
                      className="p-4 rounded-xl bg-white border border-[#E4DDCA] flex flex-col md:flex-row md:items-center justify-between gap-4 shadow-2xs hover:border-[#6C5119]/40 transition-colors"
                    >
                      <div className="space-y-1.5">
                        <div className="flex items-center space-x-2 flex-wrap">
                          <span className="px-2 py-0.5 rounded text-[10px] font-black uppercase tracking-wider bg-blue-100 text-blue-900 border border-blue-300">
                            Subject Allocation
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
                          <span className="font-mono text-xs text-[#77735F]">{req.request_id}</span>
                        </div>

                        <p className="text-xs font-semibold text-[#24251C]">
                          Faculty:{" "}
                          <span className="font-bold text-[#6C5119]">{req.teacher_name || req.user_id}</span>{" "}
                          <span className="text-[#77735F]">({req.user_id})</span>
                          {matchingTeacher && (
                            <button
                              onClick={() => setViewingProfileTeacher(matchingTeacher)}
                              className="ml-2 text-[11px] text-[#6C5119] underline font-bold cursor-pointer"
                            >
                              [View Teacher Profile]
                            </button>
                          )}
                        </p>

                        <div className="p-2.5 rounded-lg bg-[#FBF8F0] border border-[#E4DDCA] text-xs">
                          <span className="font-bold text-[#24251C]">Reason: </span>
                          <span className="font-medium text-[#77735F]">{req.reason}</span>
                        </div>

                        <p className="text-[10px] text-[#77735F]">Submitted: {req.created_at}</p>
                      </div>

                      {/* Actions for Admin on Pending Requests */}
                      {isAdmin && isPending && (
                        <div className="flex items-center gap-2 self-start md:self-auto shrink-0">
                          <button
                            disabled={reviewingId === req.request_id}
                            onClick={() => void handleReviewRequest(req.request_id, "APPROVE")}
                            className="px-3.5 py-1.5 rounded-xl bg-emerald-700 hover:bg-emerald-800 text-white text-xs font-bold transition-all shadow-2xs cursor-pointer disabled:opacity-50"
                          >
                            ✓ Approve & Assign
                          </button>
                          <button
                            disabled={reviewingId === req.request_id}
                            onClick={() => void handleReviewRequest(req.request_id, "REJECT")}
                            className="px-3 py-1.5 rounded-xl bg-rose-700 hover:bg-rose-800 text-white text-xs font-bold transition-all shadow-2xs cursor-pointer disabled:opacity-50"
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

          {/* Empty state when no requests matching filter */}
          {totalPendingCount === 0 && approvalFilter !== "RESOLVED" && (
            <div className="py-12 text-center text-[#77735F] space-y-2">
              <span className="text-3xl">🎉</span>
              <p className="font-bold text-[#24251C]">All Action Items Resolved</p>
              <p className="text-xs">
                {isAdmin
                  ? "No pending attendance unlocks or subject permissions requiring review."
                  : "All your requests have been reviewed."}
              </p>
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

      {/* MODAL 5: Teacher Full Details & Contact Profile Modal */}
      {viewingProfileTeacher && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40 backdrop-blur-xs animate-in fade-in duration-150">
          <div className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl max-w-lg w-full p-6 shadow-2xl space-y-5 max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between pb-3 border-b border-[#E4DDCA]">
              <div className="flex items-center space-x-3">
                <div className="w-10 h-10 rounded-xl bg-[#3F451F] text-[#EDE8D8] flex items-center justify-center font-bold text-base uppercase">
                  {viewingProfileTeacher.name ? viewingProfileTeacher.name.charAt(0) : viewingProfileTeacher.user_id.charAt(0)}
                </div>
                <div>
                  <h3 className="text-base font-bold text-[#24251C]">{viewingProfileTeacher.name || viewingProfileTeacher.user_id}</h3>
                  <p className="text-xs text-[#77735F] font-mono">{viewingProfileTeacher.user_id} • {viewingProfileTeacher.designation || "Faculty Member"}</p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setViewingProfileTeacher(null)}
                className="text-[#77735F] hover:text-[#24251C] text-sm font-bold cursor-pointer"
              >
                ✕
              </button>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
              <div className="p-3 rounded-xl bg-white border border-[#E4DDCA] space-y-1">
                <span className="font-bold text-[#77735F] uppercase text-[10px]">Official Account Email</span>
                <p className="font-semibold text-[#24251C] break-all">{viewingProfileTeacher.email || "—"}</p>
              </div>

              <div className="p-3 rounded-xl bg-white border border-[#E4DDCA] space-y-1">
                <span className="font-bold text-[#77735F] uppercase text-[10px]">Mobile / Phone</span>
                <p className="font-semibold text-[#24251C]">{viewingProfileTeacher.mobile || "Not specified"}</p>
              </div>

              <div className="p-3 rounded-xl bg-white border border-[#E4DDCA] space-y-1">
                <span className="font-bold text-[#77735F] uppercase text-[10px]">Department / Branch</span>
                <p className="font-semibold text-[#24251C]">{viewingProfileTeacher.branch || "General / Inter-departmental"}</p>
              </div>

              <div className="p-3 rounded-xl bg-white border border-[#E4DDCA] space-y-1">
                <span className="font-bold text-[#77735F] uppercase text-[10px]">Experience</span>
                <p className="font-semibold text-[#24251C]">{viewingProfileTeacher.experience_years ? `${viewingProfileTeacher.experience_years} Years` : "—"}</p>
              </div>

              <div className="p-3 rounded-xl bg-white border border-[#E4DDCA] space-y-1 col-span-1 sm:col-span-2">
                <span className="font-bold text-[#77735F] uppercase text-[10px]">Qualifications & Specialization</span>
                <p className="font-semibold text-[#24251C]">
                  {viewingProfileTeacher.qualifications || "—"}
                  {viewingProfileTeacher.specialization ? ` (${viewingProfileTeacher.specialization})` : ""}
                </p>
              </div>
            </div>

            {/* Expertise Areas */}
            {viewingProfileTeacher.expertise && viewingProfileTeacher.expertise.length > 0 && (
              <div className="space-y-1.5">
                <span className="text-[11px] font-bold text-[#77735F] uppercase tracking-wider">Expertise & Research Areas</span>
                <div className="flex flex-wrap gap-1.5">
                  {viewingProfileTeacher.expertise.map((exp, idx) => (
                    <span key={idx} className="px-2.5 py-0.5 rounded-full text-[11px] font-semibold bg-[#EDE8D8] text-[#24251C] border border-[#E4DDCA]">
                      {exp}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {/* Assigned Subjects & Session Activity */}
            <div className="space-y-2 pt-2 border-t border-[#E4DDCA]">
              <div className="flex items-center justify-between text-xs">
                <span className="font-bold text-[#77735F] uppercase text-[10px]">Assigned Teaching Subjects</span>
                <span className="font-bold text-[#6C5119]">{viewingProfileTeacher.session_count} Total Sessions</span>
              </div>
              <div className="flex flex-wrap gap-1.5">
                {viewingProfileTeacher.subject_codes && viewingProfileTeacher.subject_codes.length > 0 ? (
                  viewingProfileTeacher.subject_codes.map((sc) => (
                    <span key={sc} className="px-2.5 py-1 rounded-xl text-xs font-bold bg-[#3F451F] text-[#EDE8D8]">
                      {sc} {KNOWN_SUBJECTS[sc]?.name ? `• ${KNOWN_SUBJECTS[sc].name}` : ""}
                    </span>
                  ))
                ) : (
                  <span className="text-xs text-[#77735F] italic">No active subject assignments</span>
                )}
              </div>
            </div>

            {/* Active Requests & Approvals for this Teacher (Direct Action) */}
            {isAdmin && (() => {
              const teacherUnlocks = unlockRequests.filter(
                (u) => u.teacher_id === viewingProfileTeacher.user_id || u.teacher_name === viewingProfileTeacher.name
              );
              const teacherSubjectReqs = requests.filter(
                (r) => r.user_id === viewingProfileTeacher.user_id
              );
              const hasAny = teacherUnlocks.length > 0 || teacherSubjectReqs.length > 0;

              return (
                <div className="space-y-3 pt-3 border-t border-[#E4DDCA]">
                  <div className="flex items-center justify-between text-xs">
                    <span className="font-bold text-[#6C5119] uppercase text-[10px] tracking-wider">
                      Pending Approvals & Edit Requests for {viewingProfileTeacher.name || viewingProfileTeacher.user_id}
                    </span>
                    <span className="text-[11px] font-semibold text-[#77735F]">
                      {teacherUnlocks.filter((u) => u.status === "PENDING").length +
                        teacherSubjectReqs.filter((r) => r.status === "PENDING").length}{" "}
                      Pending
                    </span>
                  </div>

                  {!hasAny ? (
                    <div className="p-3 rounded-xl bg-emerald-50 border border-emerald-200 text-xs text-emerald-800 flex items-center gap-2">
                      <span>✓</span>
                      <span>No pending edit unlocks or permission requests for this faculty member.</span>
                    </div>
                  ) : (
                    <div className="space-y-2.5">
                      {/* Attendance Unlocks */}
                      {teacherUnlocks.map((u) => {
                        const isPending = u.status === "PENDING";
                        return (
                          <div
                            key={u.request_id}
                            className={`p-3 rounded-xl border text-xs space-y-2 ${
                              isPending
                                ? "bg-amber-50/90 border-amber-300"
                                : u.status === "APPROVED"
                                ? "bg-emerald-50 border-emerald-200"
                                : "bg-stone-50 border-stone-200"
                            }`}
                          >
                            <div className="flex items-center justify-between flex-wrap gap-1">
                              <span className="font-bold text-[#24251C]">
                                🕒 Attendance 24h Edit Unlock • {u.subject_code || "Session"}
                              </span>
                              <span
                                className={`px-2 py-0.5 rounded text-[10px] font-black uppercase ${
                                  isPending
                                    ? "bg-amber-200 text-amber-900 border border-amber-300 animate-pulse"
                                    : u.status === "APPROVED"
                                    ? "bg-emerald-200 text-emerald-900"
                                    : "bg-rose-200 text-rose-900"
                                }`}
                              >
                                {u.status}
                              </span>
                            </div>

                            <p className="text-xs text-[#24251C]">
                              <span className="font-semibold">Reason / Justification:</span>{" "}
                              <span className="italic font-medium text-[#6C5119]">"{u.reason}"</span>
                            </p>

                            <p className="text-[10px] text-[#77735F] font-mono">
                              Session ID: {u.session_id} • Requested: {new Date(u.created_at).toLocaleString()}
                            </p>

                            {isPending && (
                              <div className="flex items-center gap-2 pt-1">
                                <button
                                  type="button"
                                  disabled={reviewingUnlockId === u.request_id}
                                  onClick={() => void handleReviewUnlock(u.request_id, "APPROVED")}
                                  className="px-3 py-1 bg-emerald-700 hover:bg-emerald-800 text-white rounded-lg text-xs font-bold transition-all cursor-pointer disabled:opacity-50"
                                >
                                  ✓ Approve 24h Window
                                </button>
                                <button
                                  type="button"
                                  disabled={reviewingUnlockId === u.request_id}
                                  onClick={() => void handleReviewUnlock(u.request_id, "REJECTED")}
                                  className="px-3 py-1 bg-rose-700 hover:bg-rose-800 text-white rounded-lg text-xs font-bold transition-all cursor-pointer disabled:opacity-50"
                                >
                                  ✕ Reject
                                </button>
                              </div>
                            )}
                          </div>
                        );
                      })}

                      {/* Subject Requests */}
                      {teacherSubjectReqs.map((r) => {
                        const isPending = r.status === "PENDING";
                        return (
                          <div
                            key={r.request_id}
                            className={`p-3 rounded-xl border text-xs space-y-2 ${
                              isPending
                                ? "bg-amber-50/90 border-amber-300"
                                : r.status === "APPROVED"
                                ? "bg-emerald-50 border-emerald-200"
                                : "bg-stone-50 border-stone-200"
                            }`}
                          >
                            <div className="flex items-center justify-between flex-wrap gap-1">
                              <span className="font-bold text-[#24251C]">
                                📚 Subject Permission • {r.subject_code}
                              </span>
                              <span
                                className={`px-2 py-0.5 rounded text-[10px] font-black uppercase ${
                                  isPending
                                    ? "bg-amber-200 text-amber-900 border border-amber-300 animate-pulse"
                                    : r.status === "APPROVED"
                                    ? "bg-emerald-200 text-emerald-900"
                                    : "bg-rose-200 text-rose-900"
                                }`}
                              >
                                {r.status}
                              </span>
                            </div>

                            <p className="text-xs text-[#24251C]">
                              <span className="font-semibold">Reason:</span> {r.reason}
                            </p>

                            <p className="text-[10px] text-[#77735F] font-mono">
                              Request ID: {r.request_id} • Submitted: {r.created_at}
                            </p>

                            {isPending && (
                              <div className="flex items-center gap-2 pt-1">
                                <button
                                  type="button"
                                  disabled={reviewingId === r.request_id}
                                  onClick={() => void handleReviewRequest(r.request_id, "APPROVE")}
                                  className="px-3 py-1 bg-emerald-700 hover:bg-emerald-800 text-white rounded-lg text-xs font-bold transition-all cursor-pointer disabled:opacity-50"
                                >
                                  ✓ Approve & Assign
                                </button>
                                <button
                                  type="button"
                                  disabled={reviewingId === r.request_id}
                                  onClick={() => void handleReviewRequest(r.request_id, "REJECT")}
                                  className="px-3 py-1 bg-rose-700 hover:bg-rose-800 text-white rounded-lg text-xs font-bold transition-all cursor-pointer disabled:opacity-50"
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
              );
            })()}

            <div className="flex justify-end pt-3 border-t border-[#E4DDCA]">
              <button
                type="button"
                onClick={() => setViewingProfileTeacher(null)}
                className="px-4 py-2 rounded-xl bg-[#3F451F] text-[#FBF8F0] text-xs font-bold hover:bg-[#323719] transition-all cursor-pointer"
              >
                Close Profile
              </button>
            </div>
          </div>
        </div>
      )}
      {/* MODAL 6: Add New Faculty Account Modal (Admin Only) */}
      {isAddTeacherOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40 backdrop-blur-xs animate-in fade-in duration-150">
          <div className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl max-w-md w-full p-6 shadow-2xl space-y-4">
            <div className="flex items-center justify-between pb-3 border-b border-[#E4DDCA]">
              <div className="flex items-center space-x-2.5">
                <div className="w-8 h-8 rounded-xl bg-[#6C5119] text-white flex items-center justify-center font-bold text-sm">
                  +
                </div>
                <div>
                  <h3 className="text-base font-bold text-[#24251C]">Add New Faculty Member</h3>
                  <p className="text-xs text-[#77735F]">Create an institutional teacher account</p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setIsAddTeacherOpen(false)}
                className="text-[#77735F] hover:text-[#24251C] text-sm font-bold cursor-pointer"
              >
                ✕
              </button>
            </div>

            {addTeacherError && (
              <div className="p-3 rounded-xl bg-rose-50 border border-rose-200 text-xs text-rose-800 font-semibold">
                {addTeacherError}
              </div>
            )}

            <form onSubmit={handleAddTeacher} className="space-y-3.5">
              <div>
                <label className="block text-xs font-bold text-[#24251C] mb-1">
                  Faculty User ID <span className="text-rose-600">*</span>
                </label>
                <input
                  type="text"
                  required
                  placeholder="e.g. faculty_ai, faculty_math"
                  value={addTeacherForm.user_id}
                  onChange={(e) => setAddTeacherForm({ ...addTeacherForm, user_id: e.target.value })}
                  className="w-full px-3.5 py-2 rounded-xl bg-white border border-[#E4DDCA] text-xs font-mono focus:outline-none focus:ring-2 focus:ring-[#6C5119]"
                />
              </div>

              <div>
                <label className="block text-xs font-bold text-[#24251C] mb-1">
                  Full Official Name <span className="text-rose-600">*</span>
                </label>
                <input
                  type="text"
                  required
                  placeholder="e.g. Dr. Ramesh Kumar"
                  value={addTeacherForm.name}
                  onChange={(e) => setAddTeacherForm({ ...addTeacherForm, name: e.target.value })}
                  className="w-full px-3.5 py-2 rounded-xl bg-white border border-[#E4DDCA] text-xs focus:outline-none focus:ring-2 focus:ring-[#6C5119]"
                />
              </div>

              <div>
                <label className="block text-xs font-bold text-[#24251C] mb-1">
                  Institutional Email <span className="text-rose-600">*</span>
                </label>
                <input
                  type="email"
                  required
                  placeholder="e.g. ramesh.kumar@institution.edu"
                  value={addTeacherForm.email}
                  onChange={(e) => setAddTeacherForm({ ...addTeacherForm, email: e.target.value })}
                  className="w-full px-3.5 py-2 rounded-xl bg-white border border-[#E4DDCA] text-xs focus:outline-none focus:ring-2 focus:ring-[#6C5119]"
                />
              </div>

              <div>
                <label className="block text-xs font-bold text-[#24251C] mb-1">
                  Temporary Password <span className="text-rose-600">*</span>
                </label>
                <div className="relative">
                  <input
                    type={showAddPassword ? "text" : "password"}
                    required
                    placeholder="Min 8 chars, 1 uppercase, 1 symbol"
                    value={addTeacherForm.password}
                    onChange={(e) => setAddTeacherForm({ ...addTeacherForm, password: e.target.value })}
                    className="w-full px-3.5 py-2 rounded-xl bg-white border border-[#E4DDCA] text-xs focus:outline-none focus:ring-2 focus:ring-[#6C5119] pr-10"
                  />
                  <button
                    type="button"
                    onClick={() => setShowAddPassword(!showAddPassword)}
                    className="absolute right-3 top-2.5 text-xs text-[#77735F] hover:text-[#24251C]"
                  >
                    {showAddPassword ? "Hide" : "Show"}
                  </button>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-bold text-[#24251C] mb-1">Department / Branch</label>
                  <input
                    type="text"
                    placeholder="e.g. CSE, AI, ECE"
                    value={addTeacherForm.branch}
                    onChange={(e) => setAddTeacherForm({ ...addTeacherForm, branch: e.target.value })}
                    className="w-full px-3.5 py-2 rounded-xl bg-white border border-[#E4DDCA] text-xs focus:outline-none focus:ring-2 focus:ring-[#6C5119]"
                  />
                </div>
                <div>
                  <label className="block text-xs font-bold text-[#24251C] mb-1">Designation</label>
                  <input
                    type="text"
                    placeholder="e.g. Asst. Professor"
                    value={addTeacherForm.designation}
                    onChange={(e) => setAddTeacherForm({ ...addTeacherForm, designation: e.target.value })}
                    className="w-full px-3.5 py-2 rounded-xl bg-white border border-[#E4DDCA] text-xs focus:outline-none focus:ring-2 focus:ring-[#6C5119]"
                  />
                </div>
              </div>

              <div className="flex items-center justify-end gap-2 pt-3 border-t border-[#E4DDCA]">
                <button
                  type="button"
                  onClick={() => setIsAddTeacherOpen(false)}
                  className="px-4 py-2 rounded-xl bg-white border border-[#E4DDCA] text-xs font-bold text-[#77735F] hover:bg-[#EDE8D8]/50"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isSubmittingAddTeacher}
                  className="px-4 py-2 rounded-xl bg-[#6C5119] text-white text-xs font-bold hover:bg-[#594214] disabled:opacity-50 transition-all shadow-xs"
                >
                  {isSubmittingAddTeacher ? "Creating..." : "Create Teacher Account"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
