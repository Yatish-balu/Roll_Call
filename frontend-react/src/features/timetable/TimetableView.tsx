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

export function TimetableView() {
  const { session, isAdmin } = useAuth();
  const [selectedDay, setSelectedDay] = useState<string>("Monday");
  const [viewMode, setViewMode] = useState<"teacher" | "master">(isAdmin ? "master" : "teacher");

  const days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"] as const;

  // Real teacher schedule based on assigned subjects:
  // Requirements:
  // 1. 2 to 3 classes per day
  // 2. Regular lecture: 1 hour
  // 3. Laboratory practical: 2 hours
  const teacherSchedule: ClassSlot[] = useMemo(() => {
    return [
      // MONDAY: 2 lectures (1h each) + 1 lab (2h) = 3 classes
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
        room: "LAB-1 (Computer Science Lab)",
        batch: "CSE-5A Batch B1",
        department: "CSE",
        sessionId: "SESS-20261024-01",
      },

      // TUESDAY: 2 lectures (1h each) = 2 classes
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

      // WEDNESDAY: 1 lecture (1h) + 1 lab (2h) = 2 classes
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
        room: "LAB-1 (Computer Science Lab)",
        batch: "CSE-5B Batch B2",
        department: "CSE",
        sessionId: "SESS-20261025-02",
      },

      // THURSDAY: 2 lectures (1h each) = 2 classes
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

      // FRIDAY: 2 lectures (1h each) + 1 lab (2h) = 3 classes
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
        subjectTitle: "Systems Capstone & Microservices Lab",
        room: "LAB-2 (Electronics & Hardware Lab 2)",
        batch: "CSE-5A / CSE-5B Joint Lab",
        department: "CSE",
        sessionId: "SESS-20261024-01",
      },
    ];
  }, []);

  const daySlots = useMemo(() => {
    return teacherSchedule.filter((s) => s.day === selectedDay);
  }, [teacherSchedule, selectedDay]);

  const totalLectures = teacherSchedule.filter((s) => !s.isLab).length;
  const totalLabs = teacherSchedule.filter((s) => s.isLab).length;
  const totalWeeklyHours = totalLectures * 1 + totalLabs * 2;

  return (
    <div className="space-y-6 max-w-7xl mx-auto">
      {/* Header and Controls */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <div className="flex items-center space-x-2.5">
            <h1 className="text-2xl sm:text-3xl font-extrabold text-[#24251C] tracking-tight">
              {viewMode === "teacher" ? "Teacher Weekly Timetable" : "Master Department Timetable"}
            </h1>
            <span className="px-2.5 py-0.5 rounded-full text-[11px] font-black uppercase tracking-wider bg-[#3F451F] text-[#EDE8D8]">
              {session?.name || "faculty.ds"}
            </span>
          </div>
          <p className="text-xs sm:text-sm text-[#77735F] mt-1">
            Personal teaching schedule: 2–3 classes per day (1 hour lecture / 2 hours laboratory practical).
          </p>
        </div>

        {/* View Switcher & Settings */}
        <div className="flex items-center space-x-2">
          {isAdmin && (
            <div className="inline-flex rounded-xl border border-[#E4DDCA] bg-[#FBF8F0] p-1 shadow-2xs">
              <button
                type="button"
                onClick={() => setViewMode("teacher")}
                className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all cursor-pointer ${
                  viewMode === "teacher"
                    ? "bg-[#3F451F] text-[#EDE8D8] shadow-xs"
                    : "text-[#77735F] hover:text-[#24251C]"
                }`}
              >
                Teacher View
              </button>
              <button
                type="button"
                onClick={() => setViewMode("master")}
                className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all cursor-pointer ${
                  viewMode === "master"
                    ? "bg-[#3F451F] text-[#EDE8D8] shadow-xs"
                    : "text-[#77735F] hover:text-[#24251C]"
                }`}
              >
                Master Grid
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Teaching Load Metrics Cards */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 sm:gap-4">
        <div className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl p-4 shadow-2xs">
          <span className="text-[11px] font-bold text-[#77735F] uppercase tracking-wider">Daily Classes</span>
          <p className="text-2xl font-black text-[#24251C] mt-1">2 – 3</p>
          <p className="text-[11px] text-[#77735F] mt-0.5 font-medium">Per academic working day</p>
        </div>

        <div className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl p-4 shadow-2xs">
          <span className="text-[11px] font-bold text-[#77735F] uppercase tracking-wider">Theory Lectures</span>
          <p className="text-2xl font-black text-[#6C5119] mt-1">{totalLectures} Classes</p>
          <p className="text-[11px] text-[#77735F] mt-0.5 font-medium">Standard 1 Hour each</p>
        </div>

        <div className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl p-4 shadow-2xs">
          <span className="text-[11px] font-bold text-[#77735F] uppercase tracking-wider">Practical Labs</span>
          <p className="text-2xl font-black text-[#1B5E20] mt-1">{totalLabs} Labs</p>
          <p className="text-[11px] text-[#77735F] mt-0.5 font-medium">Standard 2 Hours each</p>
        </div>

        <div className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl p-4 shadow-2xs">
          <span className="text-[11px] font-bold text-[#77735F] uppercase tracking-wider">Weekly Workload</span>
          <p className="text-2xl font-black text-[#3F451F] mt-1">{totalWeeklyHours} Hours</p>
          <p className="text-[11px] text-[#77735F] mt-0.5 font-medium">Curriculum credits active</p>
        </div>
      </div>

      {/* Day Selector Tabs */}
      <div className="flex items-center space-x-2 border-b border-[#E4DDCA] pb-3 overflow-x-auto scrollbar-none">
        {days.map((d) => {
          const count = teacherSchedule.filter((s) => s.day === d).length;
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
              <span className={`px-1.5 py-0.2 rounded-full text-[10px] font-black ${
                isSelected ? "bg-black/20 text-white" : "bg-[#EDE8D8] text-[#6C5119]"
              }`}>
                {count} classes
              </span>
            </button>
          );
        })}
      </div>

      {/* Selected Day Class Timeline */}
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-base font-bold text-[#24251C]">
            Classes Scheduled for {selectedDay} ({daySlots.length} Classes)
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
                {/* Time & Duration Pill */}
                <div className="flex items-center space-x-3">
                  <div className={`p-3 rounded-xl flex flex-col items-center justify-center min-w-[70px] text-center border ${
                    slot.isLab
                      ? "bg-[#1B5E20]/10 border-[#1B5E20]/20 text-[#1B5E20]"
                      : "bg-[#6C5119]/10 border-[#6C5119]/20 text-[#6C5119]"
                  }`}>
                    <span className="text-xs font-black tracking-wider uppercase">
                      Period {slot.periodNum}
                    </span>
                    <span className="text-[10px] font-bold mt-0.5">
                      {slot.durationHours === 2 ? "2 HOURS" : "1 HOUR"}
                    </span>
                  </div>

                  {/* Class Info */}
                  <div className="space-y-1">
                    <div className="flex items-center space-x-2 flex-wrap">
                      <span className="text-xs font-black px-2 py-0.5 rounded-md bg-[#EDE8D8] text-[#6C5119] border border-[#E4DDCA]">
                        {slot.subjectCode}
                      </span>
                      <span className={`text-[11px] font-extrabold px-2 py-0.5 rounded-md ${
                        slot.isLab
                          ? "bg-emerald-100 text-emerald-800 border border-emerald-300"
                          : "bg-amber-100 text-amber-800 border border-amber-300"
                      }`}>
                        {slot.isLab ? "2-HOUR PRACTICAL LAB" : "1-HOUR THEORY LECTURE"}
                      </span>
                      <span className="text-xs font-semibold text-[#77735F]">
                        {slot.startTime} – {slot.endTime}
                      </span>
                    </div>

                    <h3 className="text-base font-bold text-[#24251C]">
                      {slot.subjectTitle}
                    </h3>

                    <div className="flex items-center space-x-4 text-xs text-[#77735F] pt-1 flex-wrap">
                      <span className="flex items-center space-x-1">
                        <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4" />
                        </svg>
                        <span className="font-semibold text-[#24251C]">Room: {slot.room}</span>
                      </span>
                      <span className="flex items-center space-x-1">
                        <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0zm6 3a2 2 0 11-4 0 2 2 0 014 0zM7 10a2 2 0 11-4 0 2 2 0 014 0z" />
                        </svg>
                        <span>Batch: {slot.batch}</span>
                      </span>
                    </div>
                  </div>
                </div>

                {/* Direct Action */}
                <div className="flex items-center space-x-2 shrink-0">
                  <Link
                    to={slot.sessionId ? `/attendance?session=${slot.sessionId}` : "/attendance"}
                    className="w-full sm:w-auto px-4 py-2 rounded-xl bg-[#3F451F] text-[#EDE8D8] text-xs font-bold hover:bg-[#343919] transition-all shadow-2xs flex items-center justify-center space-x-1.5"
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
  );
}
