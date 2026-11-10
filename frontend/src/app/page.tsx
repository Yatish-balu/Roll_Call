"use client";

import React from "react";
import { AppShell } from "@/components/layout";
import { DashboardView } from "@/features/dashboard";

export default function HomePage() {
  return (
    <AppShell title="Dashboard">
      <DashboardView />
    </AppShell>
  );
}
