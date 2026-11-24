"use client";

import React, { useEffect, useState } from "react";
import {
  createClassDelegation,
  fetchFacultyColleagues,
  type FacultyColleague,
  type ClassDelegationInput,
} from "@/services/api/sessions";

interface DelegateClassModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess?: () => void;
  sessionId: string;
  subjectCode?: string;
  subjectName?: string;
  classDate?: string;
  timeSlot?: string;
}

export function DelegateClassModal({
  isOpen,
  onClose,
  onSuccess,
  sessionId,
  subjectCode,
  subjectName,
  classDate,
  timeSlot,
}: DelegateClassModalProps) {
  const [colleagues, setColleagues] = useState<FacultyColleague[]>([]);
  const [isLoadingColleagues, setIsLoadingColleagues] = useState(false);
  const [substituteId, setSubstituteId] = useState("");
  const [delegationType, setDelegationType] = useState<"PROXY" | "EXCHANGE">("PROXY");
  const [exchangeSessionId, setExchangeSessionId] = useState("");
  const [reason, setReason] = useState("On Medical Leave");
  const [customReason, setCustomReason] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!isOpen) return;
    setIsLoadingColleagues(true);
    fetchFacultyColleagues()
      .then((data) => {
        setColleagues(data);
        if (data.length > 0) {
          setSubstituteId((prev) => prev || data[0].user_id);
        }
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : "Failed to load faculty list.");
      })
      .finally(() => setIsLoadingColleagues(false));
  }, [isOpen]);

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (!substituteId) {
      setError("Please select a colleague to substitute this class.");
      return;
    }

    if (delegationType === "EXCHANGE" && !exchangeSessionId.trim()) {
      setError("Please specify the colleague's session ID to swap with, or select 'Proxy Substitution' for a standard one-way handover.");
      return;
    }

    const finalReason = reason === "CUSTOM" ? customReason.trim() : reason;
    if (!finalReason) {
      setError("Please provide a reason for class substitution/handover.");
      return;
    }

    setIsSubmitting(true);
    try {
      const payload: ClassDelegationInput = {
        session_id: sessionId,
        substitute_faculty_id: substituteId,
        delegation_type: delegationType,
        exchange_session_id: delegationType === "EXCHANGE" ? exchangeSessionId.trim() : undefined,
        reason: finalReason,
      };

      await createClassDelegation(payload);
      if (onSuccess) onSuccess();
      window.dispatchEvent(new CustomEvent("rollcall-delegations-updated"));
      onClose();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to delegate class.");
    } finally {
      setIsSubmitting(false);
    }
  };

  const selectedColleague = colleagues.find((c) => c.user_id === substituteId);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-xs">
      <div className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl w-full max-w-lg shadow-xl overflow-hidden animate-in fade-in zoom-in-95 duration-150">
        {/* Header */}
        <div className="p-5 border-b border-[#E4DDCA] flex items-center justify-between bg-white">
          <div className="flex items-center space-x-2.5">
            <span className="p-2 rounded-xl bg-[#EDE8D8] text-base">🤝</span>
            <div>
              <h3 className="font-extrabold text-base text-[#24251C]">
                Class Handover / Proxy Delegation
              </h3>
              <p className="text-xs text-[#77735F]">
                Delegate attendance authorization & teaching slot to a faculty colleague
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            type="button"
            className="p-1 rounded-lg text-[#77735F] hover:bg-[#EDE8D8] transition-colors cursor-pointer"
          >
            ✕
          </button>
        </div>

        {/* Selected Class Banner */}
        <div className="px-5 py-3 bg-[#EDE8D8]/50 border-b border-[#E4DDCA] flex items-center justify-between text-xs">
          <div>
            <span className="font-extrabold text-[#24251C]">
              {subjectCode || sessionId}
            </span>{" "}
            <span className="text-[#77735F]">({subjectName || "Subject"})</span>
          </div>
          <div className="text-[11px] font-bold text-[#6C5119]">
            {classDate} {timeSlot && `· ${timeSlot}`}
          </div>
        </div>

        {/* Form Body */}
        <form onSubmit={handleSubmit} className="p-5 space-y-4">
          {error && (
            <div className="p-3 rounded-xl bg-rose-50 border border-rose-200 text-xs text-rose-800">
              {error}
            </div>
          )}

          {/* Colleague Select */}
          <div>
            <label className="block text-xs font-bold text-[#24251C] mb-1">
              Select Colleague (Proxy Faculty) *
            </label>
            {isLoadingColleagues ? (
              <div className="p-2 text-xs text-[#77735F]">Loading faculty list…</div>
            ) : colleagues.length === 0 ? (
              <div className="p-3 rounded-xl bg-amber-50 border border-amber-200 text-xs text-amber-800">
                No other faculty members found in the directory.
              </div>
            ) : (
              <select
                value={substituteId}
                onChange={(e) => setSubstituteId(e.target.value)}
                className="w-full px-3.5 py-2.5 rounded-xl bg-white border border-[#E4DDCA] text-xs font-bold text-[#24251C] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#6C5119]"
                required
              >
                {colleagues.map((col) => (
                  <option key={col.user_id} value={col.user_id}>
                    {col.name} ({col.email}) — Subjects: {col.assigned_subjects.join(", ") || "General"}
                  </option>
                ))}
              </select>
            )}

            {selectedColleague && (
              <p className="text-[11px] text-[#77735F] mt-1">
                {selectedColleague.name} will receive full authorization to mark attendance and verify rosters for this class.
              </p>
            )}
          </div>

          {/* Delegation Type */}
          <div>
            <label className="block text-xs font-bold text-[#24251C] mb-1.5">
              Delegation Type
            </label>
            <div className="grid grid-cols-2 gap-2">
              <button
                type="button"
                onClick={() => setDelegationType("PROXY")}
                className={`p-3 rounded-xl border text-left cursor-pointer transition-all ${
                  delegationType === "PROXY"
                    ? "border-[#6C5119] bg-[#EDE8D8]/70 text-[#24251C]"
                    : "border-[#E4DDCA] bg-white text-[#77735F] hover:bg-[#F2EDE0]/30"
                }`}
              >
                <div className="font-extrabold text-xs">Proxy Substitution</div>
                <div className="text-[10px] mt-0.5 opacity-80">
                  Colleague covers class while you are on leave
                </div>
              </button>

              <button
                type="button"
                onClick={() => setDelegationType("EXCHANGE")}
                className={`p-3 rounded-xl border text-left cursor-pointer transition-all ${
                  delegationType === "EXCHANGE"
                    ? "border-[#6C5119] bg-[#EDE8D8]/70 text-[#24251C]"
                    : "border-[#E4DDCA] bg-white text-[#77735F] hover:bg-[#F2EDE0]/30"
                }`}
              >
                <div className="font-extrabold text-xs">Period Exchange</div>
                <div className="text-[10px] mt-0.5 opacity-80">
                  Mutual swap of teaching slots with colleague
                </div>
              </button>
            </div>

            {delegationType === "EXCHANGE" && (
              <div className="mt-2.5 p-3 rounded-xl bg-amber-50/70 border border-amber-200/80 space-y-1.5 animate-in fade-in duration-150">
                <label className="block text-[11px] font-bold text-[#24251C]">
                  Colleague's Exchange Session ID *
                </label>
                <input
                  type="text"
                  value={exchangeSessionId}
                  onChange={(e) => setExchangeSessionId(e.target.value)}
                  placeholder="e.g. SESS-2026-11-28-02 (Session you will teach in return)"
                  className="w-full px-3 py-2 rounded-xl bg-white border border-[#E4DDCA] text-xs font-mono text-[#24251C] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#6C5119]"
                  required={delegationType === "EXCHANGE"}
                />
                <p className="text-[10px] text-[#77735F]">
                  Enter the session ID belonging to {selectedColleague?.name || "the selected colleague"} that you will take in return.
                </p>
              </div>
            )}
          </div>

          {/* Reason */}
          <div>
            <label className="block text-xs font-bold text-[#24251C] mb-1">
              Reason for Handover *
            </label>
            <select
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              className="w-full px-3.5 py-2.5 rounded-xl bg-white border border-[#E4DDCA] text-xs text-[#24251C] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#6C5119]"
            >
              <option value="On Medical Leave">On Medical Leave</option>
              <option value="Attending Academic Conference / Workshop">
                Attending Academic Conference / Workshop
              </option>
              <option value="On Official Institutional Duty">
                On Official Institutional Duty
              </option>
              <option value="Personal Emergency">Personal Emergency</option>
              <option value="CUSTOM">Other (Specify below)</option>
            </select>

            {reason === "CUSTOM" && (
              <input
                type="text"
                value={customReason}
                onChange={(e) => setCustomReason(e.target.value)}
                placeholder="Enter specific reason…"
                className="mt-2 w-full px-3.5 py-2 rounded-xl bg-white border border-[#E4DDCA] text-xs text-[#24251C] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#6C5119]"
                required
              />
            )}
          </div>

          {/* Footer actions */}
          <div className="pt-3 border-t border-[#E4DDCA] flex items-center justify-end space-x-2">
            <button
              type="button"
              onClick={onClose}
              disabled={isSubmitting}
              className="px-4 py-2 rounded-xl text-xs font-bold text-[#77735F] hover:bg-[#EDE8D8] transition-colors cursor-pointer"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isSubmitting || colleagues.length === 0}
              className="px-4 py-2 rounded-xl text-xs font-bold bg-[#6C5119] hover:bg-[#594214] text-white transition-colors cursor-pointer disabled:opacity-50 flex items-center space-x-1.5"
            >
              {isSubmitting ? (
                <>
                  <div className="w-3.5 h-3.5 border-2 border-white border-t-transparent rounded-full animate-spin" />
                  <span>Delegating…</span>
                </>
              ) : (
                <>
                  <span>Confirm Handover</span>
                  <span>→</span>
                </>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
