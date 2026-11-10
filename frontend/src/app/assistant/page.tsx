"use client";

import React from "react";
import { AppShell } from "@/components/layout";
import { AssistantView } from "@/features/assistant";

export default function AssistantPage() {
  return (
    <AppShell title="AI Assistant">
      <AssistantView />
    </AppShell>
  );
}

