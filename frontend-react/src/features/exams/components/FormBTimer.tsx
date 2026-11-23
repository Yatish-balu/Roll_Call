import React, { useEffect, useState } from "react";

interface FormBTimerProps {
  cutoffAt?: string;
  status: "SCHEDULED" | "OPEN" | "SUBMITTED" | "LATE_LOCKED";
  onExpire?: () => void;
}

export function FormBTimer({ cutoffAt, status, onExpire }: FormBTimerProps) {
  const [timeLeft, setTimeLeft] = useState<{
    minutes: number;
    seconds: number;
    isExpired: boolean;
    percentLeft: number;
  }>({ minutes: 0, seconds: 0, isExpired: false, percentLeft: 100 });

  useEffect(() => {
    if (!cutoffAt || status === "SUBMITTED" || status === "LATE_LOCKED") return;

    const targetTime = new Date(cutoffAt).getTime();

    const interval = setInterval(() => {
      const now = Date.now();
      const diff = targetTime - now;

      if (diff <= 0) {
        setTimeLeft({ minutes: 0, seconds: 0, isExpired: true, percentLeft: 0 });
        clearInterval(interval);
        if (onExpire) onExpire();
      } else {
        const minutes = Math.floor(diff / 60000);
        const seconds = Math.floor((diff % 60000) / 1000);
        // Assume default cutoff window is 30 mins
        const totalDuration = 30 * 60 * 1000;
        const percentLeft = Math.min(100, Math.max(0, (diff / totalDuration) * 100));
        setTimeLeft({ minutes, seconds, isExpired: false, percentLeft });
      }
    }, 1000);

    return () => clearInterval(interval);
  }, [cutoffAt, status, onExpire]);

  if (status === "SUBMITTED") {
    return (
      <div className="flex items-center gap-2 rounded-xl bg-emerald-50 px-4 py-2.5 text-emerald-800 border border-emerald-200">
        <svg className="w-5 h-5 text-emerald-600 shrink-0" fill="currentColor" viewBox="0 0 20 20">
          <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
        </svg>
        <span className="text-sm font-semibold">Form-B Attendance Submitted & Locked</span>
      </div>
    );
  }

  if (status === "LATE_LOCKED" || timeLeft.isExpired) {
    return (
      <div className="flex items-center gap-2 rounded-xl bg-red-50 px-4 py-2.5 text-red-800 border border-red-200">
        <svg className="w-5 h-5 text-red-600 shrink-0" fill="currentColor" viewBox="0 0 20 20">
          <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
        </svg>
        <span className="text-sm font-semibold">Form-B Cutoff Window Expired (Late-Locked)</span>
      </div>
    );
  }

  const isUrgent = timeLeft.minutes < 5;

  return (
    <div className={`rounded-xl border p-4 ${isUrgent ? "bg-amber-50 border-amber-300" : "bg-[#FBF8F0] border-[#3F451F]/15"}`}>
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <span className="text-lg">⏱️</span>
          <span className="text-xs font-bold uppercase tracking-wider text-[#3F451F]/70">
            Form-B Submission Window
          </span>
        </div>
        <span className={`text-base font-mono font-bold ${isUrgent ? "text-amber-800" : "text-[#3F451F]"}`}>
          {String(timeLeft.minutes).padStart(2, "0")}:{String(timeLeft.seconds).padStart(2, "0")} remaining
        </span>
      </div>
      <div className="w-full bg-[#EDE8D8] rounded-full h-2 overflow-hidden">
        <div
          className={`h-2 rounded-full transition-all duration-1000 ${
            isUrgent ? "bg-amber-500" : "bg-[#3F451F]"
          }`}
          style={{ width: `${timeLeft.percentLeft}%` }}
        />
      </div>
      <p className="text-[11px] text-gray-500 mt-1.5">
        Form-B must be submitted within cutoff time. After cutoff, room automatically locks.
      </p>
    </div>
  );
}
