/**
 * Utility functions for RollCall AI Frontend
 */

export function cn(...classes: Array<string | undefined | null | false | 0>): string {
  return classes.filter(Boolean).join(" ");
}

export function formatDate(date: Date | string | null | undefined): string {
  if (!date) return "-";
  const d = typeof date === "string" ? new Date(date) : date;
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}
