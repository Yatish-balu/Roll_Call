"use client";

import React from "react";
import { AppShell } from "@/components/layout";
import { StudentsView } from "@/features/students";

export default function StudentsPage() {
  return (
    <AppShell title="Students">
      <StudentsView />
    </AppShell>
  );
}

