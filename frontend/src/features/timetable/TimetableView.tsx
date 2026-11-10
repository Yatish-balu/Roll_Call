"use client";

import React, { useState } from "react";

interface TimetableSlot {
  id: string;
  day: "Monday" | "Tuesday" | "Wednesday" | "Thursday" | "Friday" | "Saturday";
  period: number;
  time: string;
  subjectCode: string;
  subjectTitle: string;
  rooms: string[];
  faculty: string;
  batches: string[];
  hasConflict?: boolean;
}

export function TimetableView() {
  const [selectedDay, setSelectedDay] = useState<string>("Monday");
  const [selectedBranch, setSelectedBranch] = useState<string>("CSE");

  const days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"] as const;
  const periods = [
    { num: 1, time: "09:00 - 10:00 AM" },
    { num: 2, time: "10:00 - 11:00 AM" },
    { num: 3, time: "11:15 - 12:15 PM" },
    { num: 4, time: "12:15 - 01:15 PM" },
    { num: 5, time: "02:00 - 03:00 PM" },
    { num: 6, time: "03:00 - 04:00 PM" },
  ];

  // Schedule allocation dataset (representing academic structural data)
  const scheduleData: TimetableSlot[] = [
    // Monday
    {
      id: "tt-mon-1",
      day: "Monday",
      period: 1,
      time: "09:00 - 10:00 AM",
      subjectCode: "CS-501",
      subjectTitle: "Cyber Security & Cryptography",
      rooms: ["A-201", "Lab-2"],
      faculty: "Dr. Sharma",
      batches: ["Batch A1", "Batch A2"],
    },
    {
      id: "tt-mon-2",
      day: "Monday",
      period: 2,
      time: "10:00 - 11:00 AM",
      subjectCode: "CS-502",
      subjectTitle: "Distributed Systems Architecture",
      rooms: ["A-202"],
      faculty: "Prof. DS",
      batches: ["All Batches"],
    },
    {
      id: "tt-mon-3",
      day: "Monday",
      period: 3,
      time: "11:15 - 12:15 PM",
      subjectCode: "CS-503",
      subjectTitle: "Database Management Systems",
      rooms: ["B-105", "Lab-1"],
      faculty: "Dr. Rajesh",
      batches: ["Batch B1"],
    },
    // Tuesday
    {
      id: "tt-tue-1",
      day: "Tuesday",
      period: 1,
      time: "09:00 - 10:00 AM",
      subjectCode: "CS-504",
      subjectTitle: "Machine Learning Foundations",
      rooms: ["LH-301"],
      faculty: "Prof. ML",
      batches: ["Batch C1", "Batch C2"],
    },
    {
      id: "tt-tue-3",
      day: "Tuesday",
      period: 3,
      time: "11:15 - 12:15 PM",
      subjectCode: "CS-505",
      subjectTitle: "Computer Networks & Protocols",
      rooms: ["B-106"],
      faculty: "Prof. CN",
      batches: ["All Batches"],
    },
    // Wednesday
    {
      id: "tt-wed-2",
      day: "Wednesday",
      period: 2,
      time: "10:00 - 11:00 AM",
      subjectCode: "CS-501",
      subjectTitle: "Cyber Security & Cryptography",
      rooms: ["A-201"],
      faculty: "Dr. Sharma",
      batches: ["Batch A1"],
    },
    {
      id: "tt-wed-4",
      day: "Wednesday",
      period: 4,
      time: "12:15 - 01:15 PM",
      subjectCode: "CS-502",
      subjectTitle: "Distributed Systems Architecture",
      rooms: ["Lab-2", "Lab-3"],
      faculty: "Prof. DS",
      batches: ["Batch B1", "Batch B2"],
    },
    // Thursday
    {
      id: "tt-thu-1",
      day: "Thursday",
      period: 1,
      time: "09:00 - 10:00 AM",
      subjectCode: "CS-503",
      subjectTitle: "Database Management Systems",
      rooms: ["LH-201"],
      faculty: "Dr. Rajesh",
      batches: ["All Batches"],
    },
    // Friday
    {
      id: "tt-fri-2",
      day: "Friday",
      period: 2,
      time: "10:00 - 11:00 AM",
      subjectCode: "CS-504",
      subjectTitle: "Machine Learning Foundations",
      rooms: ["A-201", "Lab-4"],
      faculty: "Prof. ML",
      batches: ["Batch C1"],
    },
    {
      id: "tt-fri-5",
      day: "Friday",
      period: 5,
      time: "02:00 - 03:00 PM",
      subjectCode: "CS-505",
      subjectTitle: "Computer Networks & Protocols",
      rooms: ["B-105"],
      faculty: "Prof. CN",
      batches: ["All Batches"],
    },
  ];

  const getSlot = (day: string, periodNum: number) => {
    return scheduleData.find((s) => s.day === day && s.period === periodNum) || null;
  };

  return (
    <div className="space-y-6 max-w-7xl mx-auto">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 pb-2">
        <div>
          <h1 className="text-2xl sm:text-3xl font-extrabold text-[#24251C] tracking-tight">
            Academic Timetable
          </h1>
          <p className="text-xs sm:text-sm text-[#77735F] mt-1">
            Weekly multi-room timetable allocations, periods, and faculty assignments.
          </p>
        </div>

        {/* Branch / Department Switcher */}
        <div className="flex items-center space-x-2">
          <label className="text-xs font-semibold text-[#77735F]">Branch:</label>
          <select
            value={selectedBranch}
            onChange={(e) => setSelectedBranch(e.target.value)}
            className="px-3.5 py-2 rounded-xl bg-white border border-[#E4DDCA] text-xs font-bold text-[#24251C] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#6C5119] cursor-pointer"
          >
            <option value="CSE">Computer Science & Engineering</option>
            <option value="CYBER">Cyber Security</option>
            <option value="AIML">Artificial Intelligence & ML</option>
            <option value="ECE">Electronics & Communication</option>
          </select>
        </div>
      </div>

      {/* Mobile Day Selector Tabs */}
      <div className="flex lg:hidden overflow-x-auto space-x-2 pb-2 scrollbar-none">
        {days.map((d) => (
          <button
            key={d}
            onClick={() => setSelectedDay(d)}
            className={`px-4 py-2 rounded-xl text-xs font-bold whitespace-nowrap transition-all cursor-pointer ${
              selectedDay === d
                ? "bg-[#6C5119] text-white shadow-2xs"
                : "bg-[#FBF8F0] border border-[#E4DDCA] text-[#77735F]"
            }`}
          >
            {d}
          </button>
        ))}
      </div>

      {/* Desktop Weekly Matrix Grid */}
      <div className="hidden lg:block bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl shadow-2xs overflow-hidden">
        <div className="grid grid-cols-7 border-b border-[#E4DDCA] bg-[#EDE8D8]/50 text-xs font-bold text-[#77735F]">
          <div className="p-3.5 border-r border-[#E4DDCA] text-center">Period / Day</div>
          {days.map((d) => (
            <div key={d} className="p-3.5 text-center border-r border-[#E4DDCA] last:border-r-0 text-[#24251C]">
              {d}
            </div>
          ))}
        </div>

        <div className="divide-y divide-[#E4DDCA]/60">
          {periods.map((p) => (
            <div key={p.num} className="grid grid-cols-7 min-h-[110px]">
              {/* Period Header */}
              <div className="p-3 border-r border-[#E4DDCA] bg-[#EDE8D8]/20 flex flex-col justify-center items-center text-center">
                <span className="font-extrabold text-[#24251C] text-sm">P{p.num}</span>
                <span className="text-[10px] text-[#77735F] mt-0.5 font-medium">{p.time}</span>
              </div>

              {/* Day Slots */}
              {days.map((d) => {
                const slot = getSlot(d, p.num);
                return (
                  <div
                    key={`${d}-${p.num}`}
                    className="p-2.5 border-r border-[#E4DDCA] last:border-r-0 hover:bg-[#EDE8D8]/20 transition-colors flex flex-col justify-between"
                  >
                    {slot ? (
                      <div className="h-full p-2.5 rounded-xl bg-white border border-[#E4DDCA] shadow-2xs flex flex-col justify-between space-y-1.5 hover:border-[#6C5119]/40 transition-all">
                        <div>
                          <div className="flex items-center justify-between">
                            <span className="font-extrabold text-xs text-[#6C5119]">
                              {slot.subjectCode}
                            </span>
                            <span className="text-[10px] text-[#77735F] font-semibold">
                              {slot.faculty}
                            </span>
                          </div>
                          <p className="text-[11px] font-bold text-[#24251C] line-clamp-1 mt-0.5">
                            {slot.subjectTitle}
                          </p>
                        </div>

                        <div className="flex flex-wrap items-center gap-1 pt-1">
                          {slot.rooms.map((rm) => (
                            <span
                              key={rm}
                              className="px-1.5 py-0.5 rounded-md bg-[#EDE8D8] text-[10px] font-semibold text-[#24251C]"
                            >
                              {rm}
                            </span>
                          ))}
                          {slot.batches.map((b) => (
                            <span
                              key={b}
                              className="px-1.5 py-0.5 rounded-md bg-[#F2EDE0] text-[10px] text-[#77735F]"
                            >
                              {b}
                            </span>
                          ))}
                        </div>
                      </div>
                    ) : (
                      <div className="h-full rounded-xl border border-dashed border-[#E4DDCA]/50 flex items-center justify-center text-[10px] text-[#77735F]/60">
                        — Empty —
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          ))}
        </div>
      </div>

      {/* Mobile Day-by-Day Card List */}
      <div className="lg:hidden space-y-3">
        {periods.map((p) => {
          const slot = getSlot(selectedDay, p.num);
          return (
            <div
              key={p.num}
              className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl p-4 shadow-2xs space-y-2"
            >
              <div className="flex items-center justify-between border-b border-[#E4DDCA]/60 pb-2">
                <span className="text-xs font-bold text-[#6C5119]">
                  Period {p.num} ({p.time})
                </span>
                <span className="text-xs font-semibold text-[#77735F]">
                  {selectedDay}
                </span>
              </div>

              {slot ? (
                <div className="space-y-2 pt-1">
                  <div>
                    <h3 className="font-extrabold text-sm text-[#24251C]">
                      [{slot.subjectCode}] {slot.subjectTitle}
                    </h3>
                    <p className="text-xs text-[#77735F] mt-0.5">Faculty: {slot.faculty}</p>
                  </div>

                  <div className="flex flex-wrap gap-1.5 pt-1">
                    <span className="px-2 py-0.5 rounded-md bg-[#EDE8D8] text-xs font-semibold text-[#24251C]">
                      Rooms: {slot.rooms.join(", ")}
                    </span>
                    <span className="px-2 py-0.5 rounded-md bg-[#EDE8D8] text-xs font-semibold text-[#77735F]">
                      Batches: {slot.batches.join(", ")}
                    </span>
                  </div>
                </div>
              ) : (
                <p className="text-xs text-[#77735F] italic py-3 text-center">
                  No academic session scheduled for this period.
                </p>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

