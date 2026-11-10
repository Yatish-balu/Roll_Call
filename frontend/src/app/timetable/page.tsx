"use client";

import React from "react";
import { AppShell } from "@/components/layout";
import { TimetableView } from "@/features/timetable";

export default function TimetablePage() {
  return (
    <AppShell title="Timetable">
      <TimetableView />
    </AppShell>
  );
}

