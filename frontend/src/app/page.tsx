"use client";

import React from "react";
import { BackendStatus } from "@/components/common/BackendStatus";
import { Footer } from "@/components/layout/Footer";
import { Navbar } from "@/components/layout/Navbar";
import { Badge } from "@/components/ui/Badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/Card";
import { useBackendHealth } from "@/hooks/useBackendHealth";

export default function WelcomePage() {
  const { isOnline } = useBackendHealth();

  const coreModules = [
    {
      title: "Master Data Management",
      description: "Manage and query Students, Rooms, and Academic Sessions with pagination and search.",
      tag: "Phase 5.3",
      endpoints: "GET /api/v1/{students,rooms,sessions}",
    },
    {
      title: "Attendance & Reconciliation",
      description: "Dual-source multi-modal ingestion (CSV sheets + Camera photos) with anomaly detection.",
      tag: "Phase 5.4",
      endpoints: "POST /api/v1/attendance/sessions/{id}/reconcile",
    },
    {
      title: "Analytics & Export Engine",
      description: "Room-wise and branch-wise attendance metrics with automated Excel and PDF reports.",
      tag: "Phase 5.5",
      endpoints: "GET /api/v1/analytics & /reports",
    },
    {
      title: "AI Attendance Assistant",
      description: "Natural-language query reasoning, automated tool routing, and document parsing.",
      tag: "Phase 5.6",
      endpoints: "POST /api/v1/agent/chat",
    },
  ];

  return (
    <div className="flex min-h-screen flex-col">
      <Navbar isBackendOnline={isOnline} />

      <main className="flex-1 py-10 px-4 sm:px-6 lg:px-8 max-w-7xl mx-auto w-full space-y-10">
        {/* Hero Section */}
        <div className="space-y-4 text-center sm:text-left">
          <div className="flex flex-wrap items-center justify-center sm:justify-start gap-2">
            <Badge variant="info" size="md">
              Phase 7.1 Complete
            </Badge>
            <Badge variant="neutral" size="md">
              Next.js 16 + React 19
            </Badge>
            <Badge variant="neutral" size="md">
              TypeScript + Tailwind CSS
            </Badge>
          </div>

          <h1 className="text-3xl sm:text-4xl font-extrabold tracking-tight text-slate-900 dark:text-slate-100">
            RollCall AI Dashboard
          </h1>

          <p className="max-w-3xl text-sm sm:text-base text-slate-600 dark:text-slate-400">
            Welcome to the Next.js frontend for RollCall AI. The frontend architecture is decoupled, 
            communicating with the FastAPI backend REST API over HTTP with centralized error handling.
          </p>
        </div>

        {/* Live Backend Connection Card */}
        <section className="space-y-4">
          <h2 className="text-lg font-bold text-slate-900 dark:text-slate-100">
            System Connectivity Status
          </h2>
          <BackendStatus />
        </section>

        {/* Monorepo Architecture Overview */}
        <section className="space-y-4">
          <h2 className="text-lg font-bold text-slate-900 dark:text-slate-100">
            Backend REST Capabilities
          </h2>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {coreModules.map((module) => (
              <Card key={module.title} className="flex flex-col justify-between">
                <CardHeader>
                  <div className="flex items-center justify-between gap-2 pb-1">
                    <Badge variant="neutral" size="sm" className="font-mono text-[10px]">
                      {module.tag}
                    </Badge>
                  </div>
                  <CardTitle className="text-base font-semibold">{module.title}</CardTitle>
                  <CardDescription className="text-xs pt-1">
                    {module.description}
                  </CardDescription>
                </CardHeader>
                <CardContent className="pt-2">
                  <div className="rounded bg-slate-100 p-2 text-[11px] font-mono text-slate-700 dark:bg-slate-800 dark:text-slate-300 truncate">
                    {module.endpoints}
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        </section>

        {/* Architecture Specs */}
        <section className="space-y-4">
          <h2 className="text-lg font-bold text-slate-900 dark:text-slate-100">
            Service Endpoints & Access
          </h2>

          <div className="rounded-xl border border-slate-200 bg-white p-6 dark:border-slate-800 dark:bg-slate-900/50">
            <dl className="grid grid-cols-1 gap-4 sm:grid-cols-3 text-xs">
              <div className="space-y-1">
                <dt className="text-slate-400 font-medium">Next.js Web Client</dt>
                <dd className="font-mono font-semibold text-slate-900 dark:text-slate-100">
                  http://localhost:3000
                </dd>
                <dd className="text-slate-500">App Router, TypeScript, Tailwind CSS</dd>
              </div>

              <div className="space-y-1">
                <dt className="text-slate-400 font-medium">FastAPI Backend Server</dt>
                <dd className="font-mono font-semibold text-slate-900 dark:text-slate-100">
                  http://127.0.0.1:8000
                </dd>
                <dd className="text-slate-500">SQLAlchemy 2.0, JWT RBAC, SQLite</dd>
              </div>

              <div className="space-y-1">
                <dt className="text-slate-400 font-medium">Interactive Documentation</dt>
                <dd className="font-mono font-semibold text-indigo-600 dark:text-indigo-400">
                  <a
                    href="http://127.0.0.1:8000/docs"
                    target="_blank"
                    rel="noreferrer"
                    className="hover:underline"
                  >
                    http://127.0.0.1:8000/docs
                  </a>
                </dd>
                <dd className="text-slate-500">Swagger UI & OpenAPI Specification</dd>
              </div>
            </dl>
          </div>
        </section>
      </main>

      <Footer />
    </div>
  );
}
