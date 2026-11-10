"use client";

import React from "react";
import { AppShell } from "@/components/layout";
import { RoomsView } from "@/features/rooms";

export default function RoomsPage() {
  return (
    <AppShell title="Rooms & Facilities">
      <RoomsView />
    </AppShell>
  );
}

