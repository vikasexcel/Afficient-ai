import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/**
 * Parse an ISO datetime string from the backend as UTC.
 * The backend stores naive UTC datetimes without a timezone suffix.
 * Without the 'Z' suffix, browsers interpret the string as local time,
 * causing timestamps to appear offset by the local UTC offset.
 */
export function parseUtcDate(iso: string): Date {
  if (!iso) return new Date(NaN);
  // If already has timezone info, parse as-is
  if (iso.endsWith("Z") || iso.includes("+")) return new Date(iso);
  return new Date(iso + "Z");
}
