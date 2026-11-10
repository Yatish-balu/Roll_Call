"use client";

import React from "react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/Card";
import { API_BASE_URL } from "@/config/api";
import { useBackendHealth } from "@/hooks/useBackendHealth";
import { formatDate } from "@/lib/utils";

export function BackendStatus() {
  const { data, isLoading, isOnline, error, lastChecked, refetch } = useBackendHealth();

  return (
    <Card className="w-full max-w-2xl border-slate-200 dark:border-slate-800">
      <CardHeader>
        <div className="flex items-center justify-between">
          <div className="space-y-1">
            <CardTitle>FastAPI Backend Connectivity</CardTitle>
            <CardDescription>
              Real-time connection probe to the Python REST service
            </CardDescription>
          </div>
          <div>
            {isLoading ? (
              <Badge variant="neutral" size="sm">
                Probing...
              </Badge>
            ) : isOnline ? (
              <Badge variant="success" size="sm">
                ● Live & Operational
              </Badge>
            ) : (
              <Badge variant="error" size="sm">
                ✕ Disconnected
              </Badge>
            )}
          </div>
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        {/* Connection Details Grid */}
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 rounded-lg bg-slate-50 p-4 text-xs dark:bg-slate-800/50">
          <div>
            <span className="text-slate-400">Target Endpoint</span>
            <p className="font-mono font-medium text-slate-800 dark:text-slate-200 truncate">
              {API_BASE_URL}/health
            </p>
          </div>

          <div>
            <span className="text-slate-400">Last Verified</span>
            <p className="font-medium text-slate-800 dark:text-slate-200">
              {formatDate(lastChecked)}
            </p>
          </div>

          <div>
            <span className="text-slate-400">Reported Status</span>
            <p className="font-medium text-slate-800 dark:text-slate-200 capitalize">
              {data?.status || (isLoading ? "Checking..." : "Offline")}
            </p>
          </div>

          <div>
            <span className="text-slate-400">Backend Version / Env</span>
            <p className="font-medium text-slate-800 dark:text-slate-200">
              {data ? `v${data.version} (${data.environment})` : "-"}
            </p>
          </div>
        </div>

        {/* Error State Banner */}
        {error && !isLoading && (
          <div className="rounded-lg border border-rose-200 bg-rose-50 p-4 text-xs text-rose-800 dark:border-rose-900/50 dark:bg-rose-950/30 dark:text-rose-300">
            <div className="flex items-start gap-2">
              <svg
                className="h-4 w-4 shrink-0 text-rose-600 mt-0.5"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth="2"
                  d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"
                />
              </svg>
              <div className="space-y-1">
                <p className="font-semibold">Backend Unreachable</p>
                <p>{error}</p>
                <p className="text-[11px] text-rose-600 dark:text-rose-400 pt-1">
                  Ensure FastAPI is running: <code className="bg-rose-100 px-1 py-0.5 rounded font-mono dark:bg-rose-900/50">python -m uvicorn app.main:app --reload</code> in the <code className="bg-rose-100 px-1 py-0.5 rounded font-mono dark:bg-rose-900/50">backend/</code> directory.
                </p>
              </div>
            </div>
          </div>
        )}

        {/* Success State Banner */}
        {isOnline && !isLoading && (
          <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-xs text-emerald-800 dark:border-emerald-900/50 dark:bg-emerald-950/30 dark:text-emerald-300">
            <div className="flex items-center gap-2">
              <svg
                className="h-4 w-4 shrink-0 text-emerald-600"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth="2"
                  d="M5 13l4 4L19 7"
                />
              </svg>
              <p>
                Backend is responding normally. FastAPI services and CORS headers are correctly configured.
              </p>
            </div>
          </div>
        )}

        {/* Action Controls */}
        <div className="flex items-center justify-between pt-2">
          <p className="text-[11px] text-slate-400">
            Frontend is configured via <code className="font-mono">NEXT_PUBLIC_API_URL</code>
          </p>

          <Button
            size="sm"
            variant="outline"
            isLoading={isLoading}
            onClick={() => refetch()}
          >
            Probe Connection
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

