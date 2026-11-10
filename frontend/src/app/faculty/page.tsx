"use client";

import React from "react";
import { AppShell } from "@/components/layout";
import { FacultyView } from "@/features/faculty";

export default function FacultyPage() {
  return (
    <AppShell title="Faculty & Departments">
      <FacultyView />
    </AppShell>
  );
}

