"use client";

import React from "react";
import { AppShell } from "@/components/layout";
import { SettingsView } from "@/features/settings";

export default function SettingsPage() {
  return (
    <AppShell title="Settings">
      <SettingsView />
    </AppShell>
  );
}

