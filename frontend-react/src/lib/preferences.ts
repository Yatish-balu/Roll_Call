/**
 * Local (device scoped) preference store.
 *
 * The RollCall AI backend does not expose an endpoint for user interface
 * preferences. Every value stored here is therefore clearly labelled in the
 * Settings page as "stored on this device" - the UI never claims a server side
 * persistence that does not exist.
 */

import { useCallback, useEffect, useState } from "react";

const STORAGE_PREFIX = "rollcall.pref.";

export type ThemePreference = "light" | "warm" | "dark" | "system";
export type SidebarDensity = "comfortable" | "compact";

export interface AppPreferences {
  theme: ThemePreference;
  sidebarCollapsed: boolean;
  sidebarDensity: SidebarDensity;
  calendarWeekStartsMonday: boolean;
  calendarShowHeatmap: boolean;
  calendarDefaultView: "month" | "week" | "day";
  notificationsEmailDigest: boolean;
  notificationsLowAttendanceAlert: boolean;
  notificationsLowAttendanceThreshold: number;
  notificationsSessionReminders: boolean;
  academicDefaultRosterStatus: "UNREVIEWED" | "PRESENT";
  aiAutoConfirmHighConfidence: boolean;
  aiShowToolCalls: boolean;
  aiExtractionConfidenceHint: boolean;
}

export const DEFAULT_PREFERENCES: AppPreferences = {
  theme: "warm",
  sidebarCollapsed: false,
  sidebarDensity: "comfortable",
  calendarWeekStartsMonday: true,
  calendarShowHeatmap: true,
  calendarDefaultView: "month",
  notificationsEmailDigest: false,
  notificationsLowAttendanceAlert: true,
  notificationsLowAttendanceThreshold: 75,
  notificationsSessionReminders: true,
  academicDefaultRosterStatus: "UNREVIEWED",
  aiAutoConfirmHighConfidence: false,
  aiShowToolCalls: true,
  aiExtractionConfidenceHint: true,
};

function readAll(): AppPreferences {
  if (typeof window === "undefined") return { ...DEFAULT_PREFERENCES };
  try {
    const raw = window.localStorage.getItem(`${STORAGE_PREFIX}all`);
    if (!raw) return { ...DEFAULT_PREFERENCES };
    const parsed = JSON.parse(raw) as Partial<AppPreferences>;
    return { ...DEFAULT_PREFERENCES, ...parsed };
  } catch {
    return { ...DEFAULT_PREFERENCES };
  }
}

function writeAll(preferences: AppPreferences): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(`${STORAGE_PREFIX}all`, JSON.stringify(preferences));
  } catch {
    // Storage can be unavailable (private mode / quota). The UI keeps working
    // with the in-memory state for the current session.
  }
}

export function getPreferences(): AppPreferences {
  return readAll();
}

export function savePreferences(preferences: AppPreferences): void {
  writeAll(preferences);
}

export function updatePreference<K extends keyof AppPreferences>(
  key: K,
  value: AppPreferences[K]
): AppPreferences {
  const next = { ...readAll(), [key]: value };
  writeAll(next);
  if (key === "theme") {
    applyTheme(value as ThemePreference);
  }
  return next;
}

/** React binding for a single preference value. */
export function usePreference<K extends keyof AppPreferences>(
  key: K
): [AppPreferences[K], (value: AppPreferences[K]) => void] {
  const [value, setValue] = useState<AppPreferences[K]>(() => readAll()[key]);

  const update = useCallback(
    (next: AppPreferences[K]) => {
      setValue(next);
      updatePreference(key, next);
    },
    [key]
  );

  useEffect(() => {
    setValue(readAll()[key]);
  }, [key]);

  return [value, update];
}

/** Apply the selected theme to the document root and persist. */
export function applyTheme(theme: ThemePreference): void {
  if (typeof document === "undefined") return;
  const root = document.documentElement;
  root.dataset.theme = theme;

  let isDark = false;
  if (theme === "dark") {
    isDark = true;
  } else if (theme === "system") {
    isDark =
      typeof window !== "undefined" &&
      window.matchMedia &&
      window.matchMedia("(prefers-color-scheme: dark)").matches;
  } else {
    isDark = false;
  }

  if (isDark) {
    root.classList.add("dark");
    root.classList.add("rollcall-dark");
  } else {
    root.classList.remove("dark");
    root.classList.remove("rollcall-dark");
  }

  try {
    localStorage.setItem("theme", theme);
    localStorage.setItem(`${STORAGE_PREFIX}theme`, theme);
  } catch {
    // Storage quota or private browsing safety
  }
}

if (typeof window !== "undefined" && window.matchMedia) {
  const mediaQuery = window.matchMedia("(prefers-color-scheme: dark)");
  const handleSystemThemeChange = (e: MediaQueryListEvent) => {
    const currentTheme = readAll().theme;
    if (currentTheme === "system") {
      const root = document.documentElement;
      if (e.matches) {
        root.classList.add("dark");
        root.classList.add("rollcall-dark");
      } else {
        root.classList.remove("dark");
        root.classList.remove("rollcall-dark");
      }
    }
  };
  try {
    mediaQuery.addEventListener("change", handleSystemThemeChange);
  } catch {
    try {
      mediaQuery.addListener(handleSystemThemeChange);
    } catch {
      // Ignored
    }
  }
}
