import React from "react";
import type { RoomSummary, RoomExamStatus } from "@/services/api/exams";

export interface RoomCardProps {
  room: RoomSummary;
  onClick?: (room: RoomSummary) => void;
  className?: string;
}

const STATUS_CONFIG: Record<
  RoomExamStatus,
  { label: string; badgeClass: string; dotClass: string; progressColor: string }
> = {
  SUBMITTED: {
    label: "SUBMITTED",
    badgeClass: "bg-emerald-100 text-emerald-800 border-emerald-200 dark:bg-emerald-950/50 dark:text-emerald-300 dark:border-emerald-800",
    dotClass: "bg-emerald-500",
    progressColor: "bg-emerald-600 dark:bg-emerald-500",
  },
  OPEN: {
    label: "OPEN",
    badgeClass: "bg-amber-100 text-amber-800 border-amber-200 dark:bg-amber-950/50 dark:text-amber-300 dark:border-amber-800",
    dotClass: "bg-amber-500 animate-pulse",
    progressColor: "bg-amber-600 dark:bg-amber-500",
  },
  SCHEDULED: {
    label: "SCHEDULED",
    badgeClass: "bg-[#EDE8D8] text-[#77735F] border-[#E4DDCA] dark:bg-[#1A1C15] dark:text-[#A9AE8C] dark:border-[#2C3022]",
    dotClass: "bg-slate-400",
    progressColor: "bg-[#72785E]",
  },
};

export const RoomCard: React.FC<RoomCardProps> = ({ room, onClick, className = "" }) => {
  const percentage = room.total > 0 ? Math.round((room.present / room.total) * 100) : 0;
  const config = STATUS_CONFIG[room.status] || STATUS_CONFIG.SCHEDULED;

  return (
    <div
      onClick={() => onClick && onClick(room)}
      className={`bg-[#FBF8F0] dark:bg-[#181913] border border-[#E4DDCA] dark:border-[#2C3022] rounded-2xl p-5 shadow-sm hover:shadow-md transition-all duration-200 ${
        onClick ? "cursor-pointer hover:border-[#3F451F]/40" : ""
      } ${className}`}
    >
      {/* Top Header: Room Name & Status Badge */}
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-mono text-xs font-bold text-[#6C5119] dark:text-[#D2A847] bg-[#EDE8D8] dark:bg-[#2C3117] px-2 py-0.5 rounded-md border border-[#E4DDCA] dark:border-[#2C3022]">
              {room.room_id}
            </span>
            <h3 className="text-base font-bold text-[#24251C] dark:text-[#EDE8D8] truncate">
              {room.room_name}
            </h3>
          </div>
          {room.invigilator_name && (
            <p className="text-xs text-[#77735F] dark:text-[#A9AE8C] mt-1 flex items-center gap-1.5 truncate">
              <svg className="w-3.5 h-3.5 shrink-0 opacity-75" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
              </svg>
              <span>Invigilator: <strong className="font-semibold text-[#24251C] dark:text-[#EDE8D8]">{room.invigilator_name}</strong></span>
            </p>
          )}
        </div>

        {/* Color-Coded Status Badge */}
        <span
          className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[10px] font-black uppercase tracking-wider border shrink-0 ${config.badgeClass}`}
        >
          <span className={`w-1.5 h-1.5 rounded-full ${config.dotClass}`} />
          {config.label}
        </span>
      </div>

      {/* Metric Counters: Present / Total & Percentage */}
      <div className="mt-4 pt-3 border-t border-[#E4DDCA]/60 dark:border-[#2C3022] flex items-baseline justify-between">
        <div>
          <span className="text-2xl font-black text-[#24251C] dark:text-[#EDE8D8] font-mono">
            {room.present}
          </span>
          <span className="text-sm font-semibold text-[#77735F] dark:text-[#A9AE8C] ml-1">
            / {room.total} Present
          </span>
        </div>
        <div className="text-right">
          <span className="text-base font-bold text-[#3F451F] dark:text-[#D2A847]">
            {percentage}%
          </span>
          <p className="text-[10px] uppercase font-bold tracking-wider text-[#77735F] dark:text-[#A9AE8C]">
            Reported
          </p>
        </div>
      </div>

      {/* Progress Bar */}
      <div className="mt-2.5">
        <div className="h-2 w-full bg-[#EDE8D8] dark:bg-[#2C3117] rounded-full overflow-hidden">
          <div
            className={`h-full rounded-full transition-all duration-500 ${config.progressColor}`}
            style={{ width: `${Math.min(100, Math.max(0, percentage))}%` }}
          />
        </div>
      </div>

      {/* Footer Details */}
      <div className="mt-3 flex items-center justify-between text-[11px] text-[#77735F] dark:text-[#A9AE8C]">
        <span>Absentees: <strong className="text-rose-600 dark:text-rose-400 font-bold">{Math.max(0, room.total - room.present)}</strong></span>
        {room.status === "SUBMITTED" ? (
          <span className="text-emerald-700 dark:text-emerald-400 font-semibold flex items-center gap-1">
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" />
            </svg>
            Form-B Locked
          </span>
        ) : room.status === "OPEN" ? (
          <span className="text-amber-700 dark:text-amber-400 font-semibold">Active In-Progress</span>
        ) : (
          <span>Awaiting Session Start</span>
        )}
      </div>
    </div>
  );
};
