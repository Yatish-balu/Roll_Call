"use client";

import React from "react";
import { AppShell } from "@/components/layout";
import { AttendanceView } from "@/features/attendance";

export default function AttendancePage() {
  return (
    <AppShell title="Attendance">
      <AttendanceView />
    </AppShell>
  );
}

