// table.ts — small helpers shared by the three table views (Screener,
// Timelines, Capex & Backlog): date parsing, freshness buckets, sorting,
// text search, CSV building, clipboard copy, file download, and remembering
// a user's view preferences.
//
// Everything is plain TypeScript with no dependencies (plus one tiny React
// hook at the very bottom), so any future view can reuse it without dragging
// a component along, and each function can be reasoned about on its own.

import { useCallback, useEffect, useRef, useState } from "react";
import { t } from "./i18n";

// ── Dates ──────────────────────────────────────────────────────────────
// The data carries dates in two spellings:
//   • source labels end in the DOCUMENT date, US order, in parentheses:
//       "NVIDIA Q2 FY2027 (08-26-2026)"
//   • generated columns (the screener's `asof`, the timeline "Date" column)
//     use ISO order: "2026-08-26"
// Both parsers build the Date at LOCAL midnight (new Date(y, m, d)) so a
// date never shifts by a day because of the viewer's timezone.

/** "(MM-DD-YYYY)" inside a source label → Date, or null when absent. */
export function parseLabelDate(label: string | null | undefined): Date | null {
  const m = /\((\d{2})-(\d{2})-(\d{4})\)/.exec(label || "");
  if (!m) return null;
  const d = new Date(+m[3], +m[1] - 1, +m[2]); // JS months are 0-based
  return isNaN(d.getTime()) ? null : d;
}

/** "YYYY-MM-DD" (anything after the 10th character is ignored) → Date, or null. */
export function parseIsoDate(s: string | null | undefined): Date | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec((s || "").trim());
  if (!m) return null;
  const d = new Date(+m[1], +m[2] - 1, +m[3]);
  return isNaN(d.getTime()) ? null : d;
}

/** Accepts either spelling — handy when a cell may hold a label or a plain date. */
export function parseDate(s: string | null | undefined): Date | null {
  return parseIsoDate(s) ?? parseLabelDate(s);
}

/** Date → "YYYY-MM-DD" in local time (toISOString would shift to UTC). */
export function isoDate(d: Date): string {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

const DAY_MS = 86_400_000;

/** Whole days from `d` up to `now` (negative when `d` is in the future). */
export function daysSince(d: Date, now: Date = new Date()): number {
  return Math.floor((now.getTime() - d.getTime()) / DAY_MS);
}

// ── Freshness ──────────────────────────────────────────────────────────
// How old a data point is decides how much weight an investor gives it.
// Thresholds:   ≤45 days = fresh (this earnings season)
//               ≤120 days = aging (one season old)
//               older     = stale

export type Freshness = "fresh" | "aging" | "stale" | "unknown";
export const FRESH_DAYS = 45;
export const AGING_DAYS = 120;

/** Human labels for the legend / tooltips (English; the keys of freshnessLabel()). */
export const FRESHNESS_LABEL: Record<Freshness, string> = {
  fresh: `Fresh (≤${FRESH_DAYS}d)`,
  aging: `Aging (${FRESH_DAYS + 1}–${AGING_DAYS}d)`,
  stale: `Stale (>${AGING_DAYS}d)`,
  unknown: "No date",
};

/** FRESHNESS_LABEL in the current language. */
export const freshnessLabel = (f: Freshness): string => t(FRESHNESS_LABEL[f]);

/**
 * Bucket a date string ("2026-08-14" or a "(08-14-2026)" label) by its age.
 * Returns the bucket plus the age in days (null when there is no date).
 */
export function freshnessBucket(
  dateStr: string | null | undefined,
  now: Date = new Date()
): { bucket: Freshness; days: number | null } {
  const d = parseDate(dateStr);
  if (!d) return { bucket: "unknown", days: null };
  const days = daysSince(d, now);
  const bucket: Freshness = days <= FRESH_DAYS ? "fresh" : days <= AGING_DAYS ? "aging" : "stale";
  return { bucket, days };
}

/** "today" / "1d ago" / "22d ago" — the small age hint next to a date. */
export function formatAge(days: number | null): string {
  if (days === null) return "";
  if (days <= 0) return t("today");
  return t("{n}d ago", { n: days });
}

// ── Sorting ────────────────────────────────────────────────────────────

export type SortDir = 1 | -1; // 1 = ascending, -1 = descending
export type CellValue = string | number | null | undefined;

const isBlank = (v: CellValue) => v === null || v === undefined || v === "" || v === "—";

/**
 * Compare two cell values: numbers numerically, everything else as text.
 * `numeric: true` makes "Q2" < "Q10" and "2026-08-14" sort correctly;
 * `sensitivity: "base"` ignores case and accents.
 */
export function compareCells(a: CellValue, b: CellValue): number {
  if (typeof a === "number" && typeof b === "number") return a - b;
  return String(a ?? "").localeCompare(String(b ?? ""), undefined, {
    numeric: true,
    sensitivity: "base",
  });
}

/**
 * Sort a COPY of `rows` by the value `get` pulls out of each row.
 * Blank cells always sink to the bottom whichever direction is chosen —
 * nobody wants a page of "—" on top when sorting descending.
 * Array.prototype.sort is stable in modern engines, so rows that compare
 * equal keep their previous order (so a secondary order survives).
 */
export function sortRows<T>(
  rows: readonly T[],
  get: (row: T) => CellValue,
  dir: SortDir
): T[] {
  return [...rows].sort((x, y) => {
    const a = get(x);
    const b = get(y);
    const aBlank = isBlank(a);
    const bBlank = isBlank(b);
    if (aBlank && bBlank) return 0;
    if (aBlank) return 1;
    if (bBlank) return -1;
    return compareCells(a, b) * dir;
  });
}

// ── Text search ────────────────────────────────────────────────────────

/**
 * Case-insensitive "every word must appear somewhere" match.
 * `fields` are the cell texts of ONE row; a query like "hbm4 samsung" matches
 * a row that mentions both words, in any cell, in any order.
 */
export function matchesQuery(fields: readonly CellValue[], query: string): boolean {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  if (words.length === 0) return true;
  const hay = fields.map((f) => String(f ?? "")).join("  ").toLowerCase();
  return words.every((w) => hay.includes(w));
}

// ── CSV ────────────────────────────────────────────────────────────────

/** One CSV column: a header plus how to read its value out of a row. */
export interface CsvColumn<T> {
  header: string;
  get: (row: T) => CellValue;
}

/** RFC 4180 quoting: wrap in quotes when the text holds a comma, quote or line break. */
export function csvField(v: CellValue): string {
  const s = v === null || v === undefined ? "" : String(v);
  return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

/** Rows + column definitions → one CSV string (CRLF line endings, as Excel expects). */
export function toCsv<T>(rows: readonly T[], columns: readonly CsvColumn<T>[]): string {
  const head = columns.map((c) => csvField(c.header)).join(",");
  const body = rows.map((r) => columns.map((c) => csvField(c.get(r))).join(","));
  return [head, ...body].join("\r\n");
}

/** "Timeline CPO signals" → "timeline_cpo_signals_2026-09-05.csv" */
export function csvFilename(base: string, now: Date = new Date()): string {
  const safe = base
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
  return `${safe || "table"}_${isoDate(now)}.csv`;
}

// ── Clipboard & download ───────────────────────────────────────────────

/**
 * Copy text to the clipboard. Returns true on success.
 * The modern API needs a secure context (https / localhost); the hidden
 * textarea + execCommand path covers plain http and older browsers.
 */
export async function copyToClipboard(text: string): Promise<boolean> {
  try {
    if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    // fall through to the legacy path
  }
  try {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.setAttribute("readonly", "");
    ta.style.position = "fixed";
    ta.style.top = "0";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(ta);
    return ok;
  } catch {
    return false;
  }
}

/**
 * Hand the browser a CSV file to save. A temporary <a download> pointing at
 * an in-memory Blob is the standard trick; the object URL is released a
 * moment later so the memory is not held for the life of the page.
 */
export function downloadCsv(filename: string, csvText: string): void {
  // The leading BOM (U+FEFF) makes Excel open the file as UTF-8, so "—",
  // "≥" and "KRW 79,318,746M" survive the round trip.
  const blob = new Blob(["\ufeff" + csvText], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.rel = "noopener";
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

// ── Remembering view preferences ───────────────────────────────────────
// localStorage can throw (private mode, blocked storage) and is missing on
// the server, so every access is wrapped; a failure simply means "no prefs".

export function readStorage<T>(key: string): T | null {
  try {
    const raw = window.localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : null;
  } catch {
    return null;
  }
}

export function writeStorage(key: string, value: unknown): void {
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // quota exceeded / storage disabled — the view still works, it just won't remember
  }
}

// ── Button feedback hook ───────────────────────────────────────────────

/**
 * Momentary button feedback. `flash("csv")` makes `flashed === "csv"` for
 * `ms` milliseconds and then clears itself, so a button can read "Copied ✓"
 * for a moment and revert on its own. One hook serves a whole toolbar: each
 * button checks for its own key.
 */
export function useFlash(ms = 1600): [string | null, (key: string) => void] {
  const [flashed, setFlashed] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const flash = useCallback(
    (key: string) => {
      setFlashed(key);
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => setFlashed(null), ms);
    },
    [ms]
  );
  // Clear a pending timer if the component unmounts mid-flash.
  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    []
  );
  return [flashed, flash];
}
