import React from "react";
import type { RoomSummaryItem, RoomStatus } from "@/services/api/exams";

interface RoomCardProps {
  room: RoomSummaryItem;
  examId?: string;
  onSelect?: (roomNo: string) => void;
  onAdminOverride?: (roomNo: string) => void;
  isAdmin?: boolean;
}

export function RoomCard({
  room,
  onSelect,
  onAdminOverride,
  isAdmin = false,
}: RoomCardProps) {
  const getStatusBadge = (status: RoomStatus) => {
    switch (status) {
      case "SUBMITTED":
        return <span className="px-2.5 py-0.5 text-xs font-semibold rounded-full bg-emerald-100 text-emerald-800">Submitted ✅</span>;
      case "OPEN":
        return <span className="px-2.5 py-0.5 text-xs font-semibold rounded-full bg-amber-100 text-amber-800">Open ⏳</span>;
      case "LATE_LOCKED":
        return <span className="px-2.5 py-0.5 text-xs font-semibold rounded-full bg-red-100 text-red-800">Late Locked 🔒</span>;
      case "SCHEDULED":
      default:
        return <span className="px-2.5 py-0.5 text-xs font-semibold rounded-full bg-gray-100 text-gray-700">Scheduled 🔒</span>;
    }
  };

  const pct = room.total_students > 0
    ? Math.round((room.present_count / room.total_students) * 100)
    : 0;

  return (
    <div className="bg-white rounded-2xl border border-gray-200/80 p-5 shadow-sm hover:shadow transition-shadow">
      <div className="flex items-start justify-between mb-3">
        <div>
          <h4 className="text-lg font-bold text-gray-900">{room.room_no}</h4>
          <p className="text-xs text-gray-500">{room.block_name || "Main Block"}</p>
        </div>
        {getStatusBadge(room.status)}
      </div>

      <div className="space-y-2 mb-4">
        <div className="flex justify-between text-xs text-gray-600">
          <span>Invigilator:</span>
          <span className="font-medium text-gray-900">{room.invigilator_name || room.invigilator_id || "Unassigned"}</span>
        </div>
        <div className="flex justify-between text-xs text-gray-600">
          <span>Candidates:</span>
          <span className="font-semibold text-gray-900">{room.present_count} / {room.total_students}</span>
        </div>
        {room.absent_count > 0 && (
          <div className="flex justify-between text-xs text-red-600">
            <span>Absentees:</span>
            <span className="font-semibold">{room.absent_count}</span>
          </div>
        )}

        <div className="w-full bg-gray-100 rounded-full h-2 mt-2 overflow-hidden">
          <div
            className={`h-2 rounded-full transition-all duration-500 ${
              room.status === "SUBMITTED" ? "bg-emerald-600" : "bg-[#3F451F]"
            }`}
            style={{ width: `${pct}%` }}
          />
        </div>
      </div>

      <div className="flex items-center gap-2 pt-2 border-t border-gray-100">
        {onSelect && (
          <button
            onClick={() => onSelect(room.room_no)}
            className="flex-1 py-1.5 px-3 rounded-xl bg-[#3F451F] text-white text-xs font-medium hover:bg-[#343919] transition-colors"
          >
            Form-B Roster
          </button>
        )}
        {isAdmin && (room.status === "LATE_LOCKED" || room.status === "SUBMITTED") && onAdminOverride && (
          <button
            onClick={() => onAdminOverride(room.room_no)}
            title="Admin Override / Unlock"
            className="p-1.5 rounded-xl border border-amber-300 text-amber-700 hover:bg-amber-50 text-xs font-medium transition-colors"
          >
            🔓 Unlock
          </button>
        )}
      </div>
    </div>
  );
}
