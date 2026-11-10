"use client";

import React from "react";
import { AppShell } from "@/components/layout";
import { SessionsView } from "@/features/sessions";

export default function SessionsPage() {
  return (
    <AppShell title="Sessions">
      <SessionsView />
    </AppShell>
  );
}

