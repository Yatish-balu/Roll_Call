"use client";

import React, { useEffect, useState, useCallback } from "react";
import { fetchDashboardData, type DashboardData } from "@/services/api/dashboard";
import { TopStats } from "./components/TopStats";
import { TodaysClasses } from "./components/TodaysClasses";
import { AiAssistantCard } from "./components/AiAssistantCard";
import { RecentSessionsTable } from "./components/RecentSessionsTable";
import { TodaysSummary } from "./components/TodaysSummary";
import { InstitutionalBreakdownTables } from "./components/InstitutionalBreakdownTables";
import { FacultyUploadActivityTable } from "./components/FacultyUploadActivityTable";
import { useAuth } from "@/hooks/useAuth";
import { todayIso } from "@/lib/schedule";

export function DashboardView() {
  const { isAdmin } = useAuth();
  const [data, setData] = useState<DashboardData | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const reloadData = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const result = await fetchDashboardData(todayIso(), { includeTeacherMappings: isAdmin });
      setData(result);
    } catch (err: unknown) {
      if (err instanceof Error) {
        setError(err.message);
      } else {
        setError("Unable to retrieve dashboard metrics from server.");
      }
    } finally {
      setIsLoading(false);
    }
  }, [isAdmin]);

  useEffect(() => {
    let isMounted = true;
    fetchDashboardData(todayIso(), { includeTeacherMappings: isAdmin })
      .then((result) => {
        if (isMounted) {
          setData(result);
          setIsLoading(false);
        }
      })
      .catch((err: unknown) => {
        if (isMounted) {
          if (err instanceof Error) {
            setError(err.message);
          } else {
            setError("Unable to retrieve dashboard metrics from server.");
          }
          setIsLoading(false);
        }
      });

    return () => {
      isMounted = false;
    };
  }, [isAdmin]);

  return (
    <div className="space-y-6 max-w-7xl mx-auto">
      {/* Non-intrusive alert when API errors occur */}
      {error && (
        <div className="bg-[#FFF8E1] border border-[#FFE082] rounded-xl p-4 flex items-center justify-between text-xs text-[#6C5119]">
          <div className="flex items-center space-x-2.5">
            <svg className="w-5 h-5 text-[#F57F17] shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
            <span>{error}</span>
          </div>
          <button
            onClick={() => {
              void reloadData();
            }}
            className="font-bold underline hover:text-[#24251C] transition-colors ml-4 cursor-pointer"
          >
            Retry
          </button>
        </div>
      )}

      {/* Row 1: Today's Attendance & Overall Attendance Stat Cards */}
      <TopStats
        sessions={data?.sessions ?? null}
        overallReport={data?.overallAnalytics ?? null}
        todayReport={data?.todayAnalytics ?? null}
        isLoading={isLoading}
      />

      {/* Row 2: Today's Classes (~62%) and AI Assistant (~38%) */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
        <div className="lg:col-span-7 xl:col-span-8">
          <TodaysClasses
            sessions={data?.sessions?.items ?? []}
            isLoading={isLoading}
          />
        </div>
        <div className="lg:col-span-5 xl:col-span-4">
          <AiAssistantCard />
        </div>
      </div>

      {/* Row 3: Recent Sessions Table (~60%) and Today's Summary (~40%) */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
        <div className="lg:col-span-7 xl:col-span-7">
          <RecentSessionsTable
            sessions={data?.sessions?.items ?? []}
            isLoading={isLoading}
          />
        </div>
        <div className="lg:col-span-5 xl:col-span-5">
          <TodaysSummary
            summary={data?.todayAnalytics?.overall ?? data?.overallAnalytics?.overall ?? null}
            isLoading={isLoading}
          />
        </div>
      </div>

      {/* Row 4: Institutional KPIs, Branch Breakdown, and Room Breakdown (N8 - F5) */}
      <InstitutionalBreakdownTables
        overviewReport={data?.overallAnalytics ?? null}
        isLoading={isLoading}
      />

      {/* Row 5: Faculty Session Generation & Upload Activity Table (N8 - F5) */}
      <FacultyUploadActivityTable
        sessions={data?.sessions?.items ?? []}
        teacherMappings={data?.teacherMappings ?? null}
        isLoading={isLoading}
      />
    </div>
  );
}
