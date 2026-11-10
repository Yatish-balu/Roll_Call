import React, { useState, useMemo } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "@/hooks/useAuth";

export interface ClassSlot {
  id: string;
  day: "Monday" | "Tuesday" | "Wednesday" | "Thursday" | "Friday";
  startTime: string;
  endTime: string;
  periodNum: number;
  durationHours: 1 | 2;
  isLab: boolean;
  subjectCode: string;
  subjectTitle: string;
  room: string;
  batch: string;
  department: string;
  sessionId?: string;
}

const PERIOD_DEFINITIONS = [
  { num: 1, label: "Period 1", time: "09:00 - 10:00 AM", isLunch: false },
  { num: 2, label: "Period 2", time: "10:00 - 11:00 AM", isLunch: false },
  { num: 3, label: "Period 3", time: "11:15 - 12:15 PM", isLunch: false },
  { num: 4, label: "Period 4", time: "12:15 - 01:15 PM", isLunch: false },
  { num: 0, label: "Break", time: "01:15 - 02:00 PM", isLunch: true },
  { num: 5, label: "Period 5 & 6", time: "02:00 - 04:00 PM (Lab / Electives)", isLunch: false },
];

export function TimetableView() {
  const { session } = useAuth();
  const [selectedDay, setSelectedDay] = useState<string>("Monday");
  const [viewType, setViewType] = useState<"day" | "grid">("day");

  const days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"] as const;

  // Institutional timetable schedule (2-3 classes per day; 1h theory lectures; 2h practical labs)
  const schedule: ClassSlot[] = useMemo(() => {
    return [
      // MONDAY: 2 lectures + 1 lab
      {
        id: "mon-1",
        day: "Monday",
        startTime: "09:00 AM",
        endTime: "10:00 AM",
        periodNum: 1,
        durationHours: 1,
        isLab: false,
        subjectCode: "DIST-SYS",
        subjectTitle: "Distributed Systems Architecture",
        room: "LH-101",
        batch: "CSE-5A",
        department: "CSE",
        sessionId: "SESS-20261024-01",
      },
      {
        id: "mon-2",
        day: "Monday",
        startTime: "11:15 AM",
        endTime: "12:15 PM",
        periodNum: 3,
        durationHours: 1,
        isLab: false,
        subjectCode: "DB-SYS",
        subjectTitle: "Database Management Systems",
        room: "LH-102",
        batch: "CSE-5B",
        department: "CSE",
        sessionId: "SESS-20261025-02",
      },
      {
        id: "mon-3",
        day: "Monday",
        startTime: "02:00 PM",
        endTime: "04:00 PM",
        periodNum: 5,
        durationHours: 2,
        isLab: true,
        subjectCode: "DIST-SYS",
        subjectTitle: "Distributed Systems & Cloud Computing Lab",
        room: "LAB-1",
        batch: "CSE-5A (Batch 1)",
        department: "CSE",
        sessionId: "SESS-20261024-01",
      },

      // TUESDAY: 2 lectures
      {
        id: "tue-1",
        day: "Tuesday",
        startTime: "10:00 AM",
        endTime: "11:00 AM",
        periodNum: 2,
        durationHours: 1,
        isLab: false,
        subjectCode: "DB-SYS",
        subjectTitle: "Database Management Systems",
        room: "LH-101",
        batch: "CSE-5B",
        department: "CSE",
        sessionId: "SESS-20261025-02",
      },
      {
        id: "tue-2",
        day: "Tuesday",
        startTime: "12:15 PM",
        endTime: "01:15 PM",
        periodNum: 4,
        durationHours: 1,
        isLab: false,
        subjectCode: "DIST-SYS",
        subjectTitle: "Distributed Systems Architecture",
        room: "LH-201",
        batch: "CSE-5A",
        department: "CSE",
        sessionId: "SESS-20261024-01",
      },

      // WEDNESDAY: 1 lecture + 1 lab
      {
        id: "wed-1",
        day: "Wednesday",
        startTime: "09:00 AM",
        endTime: "10:00 AM",
        periodNum: 1,
        durationHours: 1,
        isLab: false,
        subjectCode: "DIST-SYS",
        subjectTitle: "Distributed Systems Architecture",
        room: "LH-101",
        batch: "CSE-5A",
        department: "CSE",
        sessionId: "SESS-20261024-01",
      },
      {
        id: "wed-2",
        day: "Wednesday",
        startTime: "02:00 PM",
        endTime: "04:00 PM",
        periodNum: 5,
        durationHours: 2,
        isLab: true,
        subjectCode: "DB-SYS",
        subjectTitle: "Advanced SQL & Database Systems Lab",
        room: "LAB-1",
        batch: "CSE-5B (Batch 2)",
        department: "CSE",
        sessionId: "SESS-20261025-02",
      },

      // THURSDAY: 2 lectures
      {
        id: "thu-1",
        day: "Thursday",
        startTime: "10:00 AM",
        endTime: "11:00 AM",
        periodNum: 2,
        durationHours: 1,
        isLab: false,
        subjectCode: "DB-SYS",
        subjectTitle: "Database Management Systems",
        room: "LH-102",
        batch: "CSE-5B",
        department: "CSE",
        sessionId: "SESS-20261025-02",
      },
      {
        id: "thu-2",
        day: "Thursday",
        startTime: "11:15 AM",
        endTime: "12:15 PM",
        periodNum: 3,
        durationHours: 1,
        isLab: false,
        subjectCode: "DIST-SYS",
        subjectTitle: "Distributed Systems Architecture",
        room: "LH-101",
        batch: "CSE-5A",
        department: "CSE",
        sessionId: "SESS-20261024-01",
      },

      // FRIDAY: 2 lectures + 1 lab
      {
        id: "fri-1",
        day: "Friday",
        startTime: "09:00 AM",
        endTime: "10:00 AM",
        periodNum: 1,
        durationHours: 1,
        isLab: false,
        subjectCode: "DIST-SYS",
        subjectTitle: "Distributed Systems Architecture",
        room: "LH-101",
        batch: "CSE-5A",
        department: "CSE",
        sessionId: "SESS-20261024-01",
      },
      {
        id: "fri-2",
        day: "Friday",
        startTime: "11:15 AM",
        endTime: "12:15 PM",
        periodNum: 3,
        durationHours: 1,
        isLab: false,
        subjectCode: "DB-SYS",
        subjectTitle: "Database Management Systems",
        room: "LH-102",
        batch: "CSE-5B",
        department: "CSE",
        sessionId: "SESS-20261025-02",
      },
      {
        id: "fri-3",
        day: "Friday",
        startTime: "02:00 PM",
        endTime: "04:00 PM",
        periodNum: 5,
        durationHours: 2,
        isLab: true,
        subjectCode: "DIST-SYS",
        subjectTitle: "Microservices & Distributed Systems Lab",
        room: "LAB-2",
        batch: "CSE-5A (Batch 1)",
        department: "CSE",
        sessionId: "SESS-20261024-01",
      },
    ];
  }, []);

  const daySlots = useMemo(() => {
    return schedule.filter((s) => s.day === selectedDay);
  }, [schedule, selectedDay]);

  const getSlot = (day: string, periodNum: number) => {
    return schedule.find((s) => s.day === day && s.periodNum === periodNum);
  };

  return (
    <div className="space-y-6 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <div className="flex items-center space-x-2.5">
            <h1 className="text-2xl sm:text-3xl font-extrabold text-[#24251C] tracking-tight">
              Timetable
            </h1>
            <span className="px-2.5 py-0.5 rounded-full text-[11px] font-black uppercase tracking-wider bg-[#3F451F] text-[#EDE8D8]">
              {session?.userId || "faculty_ds"}
            </span>
          </div>
          <p className="text-xs sm:text-sm text-[#77735F] mt-1">
            Weekly academic schedule and classroom allocations.
          </p>
        </div>

        {/* View Toggle */}
        <div className="inline-flex rounded-xl border border-[#E4DDCA] bg-[#FBF8F0] p-1 shadow-2xs self-start sm:self-auto">
          <button
            type="button"
            onClick={() => setViewType("day")}
            className={`px-3.5 py-1.5 rounded-lg text-xs font-bold transition-all cursor-pointer ${
              viewType === "day"
                ? "bg-[#3F451F] text-[#EDE8D8] shadow-xs"
                : "text-[#77735F] hover:text-[#24251C]"
            }`}
          >
            Day View
          </button>
          <button
            type="button"
            onClick={() => setViewType("grid")}
            className={`px-3.5 py-1.5 rounded-lg text-xs font-bold transition-all cursor-pointer ${
              viewType === "grid"
                ? "bg-[#3F451F] text-[#EDE8D8] shadow-xs"
                : "text-[#77735F] hover:text-[#24251C]"
            }`}
          >
            Weekly Grid
          </button>
        </div>
      </div>

      {/* DAY VIEW */}
      {viewType === "day" && (
        <div className="space-y-5">
          {/* Day Selector Tabs */}
          <div className="flex items-center space-x-2 border-b border-[#E4DDCA] pb-3 overflow-x-auto scrollbar-none">
            {days.map((d) => {
              const count = schedule.filter((s) => s.day === d).length;
              const isSelected = selectedDay === d;
              return (
                <button
                  key={d}
                  onClick={() => setSelectedDay(d)}
                  className={`px-4 py-2 rounded-xl text-xs sm:text-sm font-bold flex items-center space-x-2 transition-all cursor-pointer whitespace-nowrap ${
                    isSelected
                      ? "bg-[#6C5119] text-white shadow-sm"
                      : "bg-[#FBF8F0] border border-[#E4DDCA] text-[#77735F] hover:bg-[#EDE8D8]/50 hover:text-[#24251C]"
                  }`}
                >
                  <span>{d}</span>
                  <span
                    className={`px-1.5 py-0.2 rounded-full text-[10px] font-black ${
                      isSelected ? "bg-black/20 text-white" : "bg-[#EDE8D8] text-[#6C5119]"
                    }`}
                  >
                    {count}
                  </span>
                </button>
              );
            })}
          </div>

          {/* Timeline Cards */}
          <div className="space-y-3.5">
            <div className="flex items-center justify-between">
              <h2 className="text-base font-bold text-[#24251C]">
                {selectedDay} Schedule ({daySlots.length} Classes)
              </h2>
              <span className="text-xs text-[#77735F] font-medium">
                Standard: 1 Hr Theory • 2 Hrs Laboratory
              </span>
            </div>

            <div className="grid grid-cols-1 gap-3.5">
              {daySlots.map((slot) => (
                <div
                  key={slot.id}
                  className={`p-5 rounded-2xl border transition-all shadow-2xs ${
                    slot.isLab
                      ? "bg-[#F9F7EE] border-[#DCD5BE] hover:border-[#6C5119]"
                      : "bg-[#FBF8F0] border-[#E4DDCA] hover:border-[#6C5119]/60"
                  }`}
                >
                  <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
                    {/* Period & Info */}
                    <div className="flex items-center space-x-3.5">
                      <div
                        className={`p-3 rounded-xl flex flex-col items-center justify-center min-w-[75px] text-center border ${
                          slot.isLab
                            ? "bg-[#1B5E20]/10 border-[#1B5E20]/20 text-[#1B5E20]"
                            : "bg-[#6C5119]/10 border-[#6C5119]/20 text-[#6C5119]"
                        }`}
                      >
                        <span className="text-xs font-black tracking-wider uppercase">
                          Period {slot.periodNum}
                        </span>
                        <span className="text-[10px] font-bold mt-0.5">
                          {slot.durationHours === 2 ? "2 HOURS" : "1 HOUR"}
                        </span>
                      </div>

                      <div className="space-y-1">
                        <div className="flex items-center space-x-2 flex-wrap">
                          <span className="text-xs font-black px-2 py-0.5 rounded-md bg-[#EDE8D8] text-[#6C5119] border border-[#E4DDCA]">
                            {slot.subjectCode}
                          </span>
                          <span
                            className={`text-[11px] font-extrabold px-2 py-0.5 rounded-md ${
                              slot.isLab
                                ? "bg-emerald-100 text-emerald-800 border border-emerald-300"
                                : "bg-amber-100 text-amber-800 border border-amber-300"
                            }`}
                          >
                            {slot.isLab ? "2-HOUR PRACTICAL LAB" : "1-HOUR THEORY"}
                          </span>
                          <span className="text-xs font-semibold text-[#77735F]">
                            {slot.startTime} – {slot.endTime}
                          </span>
                        </div>

                        <h3 className="text-base font-bold text-[#24251C]">
                          {slot.subjectTitle}
                        </h3>

                        <div className="flex items-center space-x-4 text-xs text-[#77735F] pt-1 flex-wrap">
                          <span className="font-semibold text-[#24251C]">Room: {slot.room}</span>
                          <span>•</span>
                          <span>Batch: {slot.batch}</span>
                          <span>•</span>
                          <span>Dept: {slot.department}</span>
                        </div>
                      </div>
                    </div>

                    {/* Action Button */}
                    <div className="shrink-0">
                      <Link
                        to={slot.sessionId ? `/attendance?session=${slot.sessionId}` : "/attendance"}
                        className="w-full sm:w-auto px-4 py-2.5 rounded-xl bg-[#3F451F] text-[#EDE8D8] text-xs font-bold hover:bg-[#343919] transition-all shadow-2xs flex items-center justify-center space-x-1.5"
                      >
                        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4" />
                        </svg>
                        <span>Take Attendance</span>
                      </Link>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* WEEKLY GRID TABLE VIEW */}
      {viewType === "grid" && (
        <div className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl shadow-sm overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse min-w-[850px]">
              <thead>
                <tr className="bg-[#EDE8D8]/70 border-b border-[#E4DDCA] text-[#24251C]">
                  <th className="py-3.5 px-4 text-xs font-black uppercase tracking-wider w-36 border-r border-[#E4DDCA]">
                    Period & Time
                  </th>
                  {days.map((day) => (
                    <th key={day} className="py-3.5 px-4 text-xs font-black uppercase tracking-wider text-center border-r border-[#E4DDCA] last:border-r-0">
                      {day}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-[#E4DDCA] text-xs text-[#24251C]">
                {PERIOD_DEFINITIONS.map((p) => {
                  if (p.isLunch) {
                    return (
                      <tr key="lunch" className="bg-[#EDE8D8]/30">
                        <td className="py-2.5 px-4 font-bold text-[#77735F] border-r border-[#E4DDCA] text-[11px]">
                          {p.label}
                          <span className="block text-[10px] font-normal text-[#77735F]/70">{p.time}</span>
                        </td>
                        <td colSpan={5} className="py-2.5 px-4 text-center font-bold text-[#77735F] italic tracking-wider text-[11px]">
                          Academic Recess & Lunch Break (01:15 – 02:00 PM)
                        </td>
                      </tr>
                    );
                  }

                  return (
                    <tr key={p.num} className="hover:bg-[#EDE8D8]/20 transition-colors">
                      <td className="py-3 px-4 font-bold border-r border-[#E4DDCA] bg-[#EDE8D8]/15">
                        <span className="block text-xs font-black text-[#24251C]">{p.label}</span>
                        <span className="block text-[10px] text-[#77735F] mt-0.5">{p.time}</span>
                      </td>

                      {days.map((day) => {
                        const slot = getSlot(day, p.num);
                        return (
                          <td
                            key={day}
                            className="py-3 px-3 border-r border-[#E4DDCA] last:border-r-0 align-top"
                          >
                            {slot ? (
                              <div
                                className={`p-2.5 rounded-xl border space-y-1 transition-all ${
                                  slot.isLab
                                    ? "bg-emerald-50/70 border-emerald-200"
                                    : "bg-amber-50/70 border-amber-200"
                                }`}
                              >
                                <div className="flex items-center justify-between gap-1">
                                  <span className="font-black text-[10px] px-1.5 py-0.2 rounded bg-black/10 text-[#24251C]">
                                    {slot.subjectCode}
                                  </span>
                                  <span className={`text-[9px] font-extrabold px-1.5 py-0.2 rounded ${
                                    slot.isLab ? "bg-emerald-700 text-white" : "bg-[#6C5119] text-white"
                                  }`}>
                                    {slot.isLab ? "2H LAB" : "1H"}
                                  </span>
                                </div>

                                <p className="font-bold text-[#24251C] text-[11px] leading-tight line-clamp-2">
                                  {slot.subjectTitle}
                                </p>

                                <div className="text-[10px] text-[#77735F] flex items-center justify-between pt-0.5">
                                  <span className="font-semibold text-[#24251C]">{slot.room}</span>
                                  <span className="truncate">{slot.batch}</span>
                                </div>

                                <Link
                                  to={slot.sessionId ? `/attendance?session=${slot.sessionId}` : "/attendance"}
                                  className="block text-center mt-1 py-1 rounded-lg bg-[#3F451F] text-[#EDE8D8] text-[10px] font-bold hover:bg-[#343919] transition-colors"
                                >
                                  Attendance
                                </Link>
                              </div>
                            ) : (
                              <div className="h-full flex items-center justify-center py-4 text-[#77735F]/40 text-xs font-mono">
                                —
                              </div>
                            )}
                          </td>
                        );
                      })}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
