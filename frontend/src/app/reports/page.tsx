"use client";

import React from "react";
import { AppShell } from "@/components/layout";
import { ReportsView } from "@/features/reports";

export default function ReportsPage() {
  return (
    <AppShell title="Reports & Analytics">
      <ReportsView />
    </AppShell>
  );
}

