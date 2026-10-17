"use client";

// FinancingSection.tsx — "Financing" in the company panel (2026-10-17).
//
// Bond / note issues, convertibles, equity raises, credit facilities, ABS, lease
// financing and rating actions from the last 365 days, collected every night by a
// script (market/*.py → graph/financing/<company>.json → /data/financing/; only this
// company's file is fetched, found through /data/financing_index.json). Not a signal:
// it lives in its own file and its own section, never in quarterly_data.
// Renders nothing when the company has no rows (or the file does not exist yet).

import { useCallback, useEffect, useMemo, useState } from "react";
import { t, useLang } from "@/lib/i18n";
import { sourceType } from "@/lib/sourceKind";
import { fmtMoney, loadCompanyFinancing, useFeed, type FinancingItem, type FinancingType } from "@/lib/companyFeeds";
import { SignalBody, SourceBadge } from "./SignalText";
import { DayChip, FeedHead, ShowAllToggle, SourceLink, SourcesLine, previewRows } from "./FeedParts";

// The type chip's English text (shown through t()).
const TYPE_LABEL: Record<FinancingType, string> = {
  debt: "Debt",
  convertible: "Convertible",
  equity: "Equity",
  credit_facility: "Credit facility",
  abs: "ABS",
  lease_financing: "Lease financing",
  rating: "Rating",
  other: "Other",
};

// "$2.5B", or "¥300B ≈ $2.0B" when the amount is in another currency.
function amountText(r: FinancingItem): string {
  const own = fmtMoney(r.amount, r.currency);
  const cur = (r.currency || "USD").toUpperCase();
  if (cur !== "USD" && r.amount_usd != null) {
    const usd = fmtMoney(r.amount_usd, "USD");
    return own ? `${own} ≈ ${usd}` : `≈ ${usd}`;
  }
  return own || fmtMoney(r.amount_usd, "USD");
}

// The detail line without what the title already says: nothing when it repeats the title, the rest when it
// starts with it ("$1.25B 9.625% Senior Notes due 2032" is often both the title and the detail).
function detailText(r: FinancingItem): string {
  const detail = (r.detail || "").trim();
  const title = (r.title || "").trim();
  if (!detail || detail === title) return "";
  if (title && detail.startsWith(title)) return detail.slice(title.length).replace(/^[\s;,:.–—-]+/, "");
  return detail;
}

function FinancingRow({ r }: { r: FinancingItem }) {
  const type = TYPE_LABEL[r.type] ? r.type : "other";
  const amount = amountText(r);
  const detail = detailText(r);
  return (
    <div className="np-fd-row">
      <div className="np-sig-head">
        <span className={"np-fd-type np-fx-" + type}>{t(TYPE_LABEL[type])}</span>
        <DayChip iso={r.date} />
        {/* An SEC form gets the same badge as the signals; anything else a plain tag. */}
        {r.form && (sourceType(r.form).kind === "filing" ? <SourceBadge label={r.form} /> : <span className="np-tag">{r.form}</span>)}
        <SourceLink source={r.source} url={r.url} />
      </div>
      <div className="np-fd-line">
        <span className="np-fd-title">{r.title}</span>
        {amount && <b className="np-fd-amt">{amount}</b>}
      </div>
      {detail && <SignalBody text={detail} />}
    </div>
  );
}

export default function FinancingSection({ companyId }: { companyId: string }) {
  useLang(); // re-render on a language change
  const load = useCallback(() => loadCompanyFinancing(companyId), [companyId]);
  const loaded = useFeed(load);
  const file = loaded && loaded.company === companyId ? loaded : null; // never show the previous company's rows
  const [open, setOpen] = useState(false);
  useEffect(() => setOpen(false), [companyId]);

  // Newest first (the file is already sorted; sorting again costs nothing).
  const rows = useMemo(
    () => [...(file?.rows || [])].sort((a, b) => (b.date || "").localeCompare(a.date || "")),
    [file]
  );
  if (!file || rows.length === 0) return null;

  return (
    <section className="np-feed" aria-label={t("Financing")}>
      <FeedHead title={t("Financing")} hint={t("last 365 days")} updated={file.updated} />
      {previewRows(rows, open).map((r, i) => (
        <FinancingRow r={r} key={r.url + "|" + r.title + "|" + i} />
      ))}
      <ShowAllToggle total={rows.length} open={open} onToggle={() => setOpen((o) => !o)} />
      <SourcesLine sources={file.sources} />
    </section>
  );
}
