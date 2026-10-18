"use client";

// FeedParts.tsx — small pieces shared by the company panel's market-data sections
// (FinancingSection, InsiderTrades, LabMetricsSection, FinancialsSection; 2026-10-17).
//
// ShowAllToggle / LIST_PREVIEW repeat the ones inside NodePanel.tsx (same classes,
// same strings) so these sections can live in their own files without importing
// NodePanel back (that would be a circular import).

import { t } from "@/lib/i18n";
import { fmtDay, type FeedSource } from "@/lib/companyFeeds";

/** Rows shown before "Show all (N)" — same number as NodePanel's long lists. */
export const LIST_PREVIEW = 5;

export function ShowAllToggle({ total, open, onToggle }: { total: number; open: boolean; onToggle: () => void }) {
  if (total <= LIST_PREVIEW) return null;
  return (
    <button className="np-linkbtn np-showall" onClick={onToggle} aria-expanded={open}>
      {open ? t("Show less") : t("Show all ({n})", { n: total })}
    </button>
  );
}

/** The newest LIST_PREVIEW rows, or all of them once opened. */
export function previewRows<T>(rows: T[], open: boolean): T[] {
  return open ? rows : rows.slice(0, LIST_PREVIEW);
}

/** "Source name ↗" linking to the row's source; plain text when there is no URL. */
export function SourceLink({ source, url }: { source: string; url?: string | null }) {
  const label = source || t("Source");
  if (!url) return <span className="np-fd-src">{label}</span>;
  return (
    <a className="np-fd-src" href={url} target="_blank" rel="noopener noreferrer" title={url}>
      {label} ↗
    </a>
  );
}

/** A date chip in the panel's MM-DD-YYYY form; `title` adds a tooltip (e.g. the filing date). */
export function DayChip({ iso, title }: { iso: string | null | undefined; title?: string }) {
  if (!iso) return null;
  return (
    <span className="np-date" title={title}>
      {fmtDay(iso)}
    </span>
  );
}

/** Section heading in the panel's .pcol-head style, with a hint and the file's update date. */
export function FeedHead({ title, hint, updated }: { title: string; hint?: string; updated?: string }) {
  return (
    <div className="pcol-head np-fd-head">
      <span>{title}</span>
      {hint && <span className="np-of-hint"> — {hint}</span>}
      {updated && <span className="np-fd-upd">{t("updated {date}", { date: fmtDay(updated) })}</span>}
    </div>
  );
}

/** "Sources: A ↗ · B ↗" under a section (the file-level source list). */
export function SourcesLine({ sources }: { sources: FeedSource[] }) {
  if (!sources || sources.length === 0) return null;
  return (
    <div className="np-fd-note">
      {t("Sources")}:{" "}
      {sources.map((s, i) => (
        <span key={s.name + "|" + i}>
          {i > 0 && " · "}
          <SourceLink source={s.name} url={s.url} />
        </span>
      ))}
    </div>
  );
}
