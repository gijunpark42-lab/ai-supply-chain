"use client";

// CashFlowSection.tsx — "Cash flow" in the company panel (2026-10-17).
//
// Quarterly capex, operating cash flow and free cash flow (also after finance-lease
// principal repayments) for the hyperscalers, read every night by a script from
// their SEC filings (graph/hyperscaler_cash.json → /data/hyperscaler_cash.json),
// plus the next earnings date. Only companies listed in that file get the section.
// Not a signal: own file, own section.

import { useEffect, useMemo, useState } from "react";
import { t, useLang } from "@/lib/i18n";
import {
  fmtDay,
  fmtMoney,
  fmtPeriod,
  loadHyperscalerCash,
  todayIso,
  useFeed,
  type CashQuarter,
  type EarningsDate,
} from "@/lib/companyFeeds";
import { DayChip, FeedHead, ShowAllToggle, SourceLink, previewRows } from "./FeedParts";

const TIME_LABEL: Record<EarningsDate["time"], string> = {
  bmo: "before market open",
  amc: "after market close",
  unknown: "time not announced",
};

// The money columns: [field, header, tooltip].
const COLUMNS: [keyof CashQuarter, string, string][] = [
  ["capex_usd", "Capex", "Purchases of property and equipment"],
  ["ocf_usd", "Operating cash flow", "Net cash from operating activities"],
  ["fcf_usd", "Free cash flow", "Operating cash flow minus capex"],
  ["lease_principal_usd", "Lease principal", "Principal repaid on finance leases"],
  ["fcf_after_leases_usd", "FCF after leases", "Free cash flow minus finance-lease principal repayments"],
];

function Money({ v }: { v: unknown }) {
  if (typeof v !== "number") return <span className="np-cf-na">—</span>;
  return <span className={v < 0 ? "np-cf-neg" : undefined}>{fmtMoney(v, "USD")}</span>;
}

function NextEarnings({ e, label = true }: { e: EarningsDate; label?: boolean }) {
  return (
    <div className="np-cf-next">
      {label && <span className="np-cf-next-k">{t("Next earnings")}</span>}
      <DayChip iso={e.date} />
      <span className="np-src">{t(TIME_LABEL[e.time] || TIME_LABEL.unknown)}</span>
      <span className={"np-tag" + (e.confirmed ? " np-cf-ok" : "")}>{e.confirmed ? t("confirmed") : t("not confirmed")}</span>
      {(e.sources || []).map((s, i) => (
        <SourceLink key={s.name + "|" + i} source={s.name} url={s.url} />
      ))}
    </div>
  );
}

export default function CashFlowSection({ companyId }: { companyId: string }) {
  useLang(); // re-render on a language change
  const file = useFeed(loadHyperscalerCash);
  const [open, setOpen] = useState(false);
  const [showNote, setShowNote] = useState(false); // the methodology note, behind a toggle
  useEffect(() => {
    setOpen(false);
    setShowNote(false);
  }, [companyId]);

  // Newest quarter first.
  const quarters = useMemo(() => {
    const co = (file?.companies || []).find((c) => c.id === companyId);
    return [...(co?.quarters || [])].sort((a, b) => (b.end || "").localeCompare(a.end || ""));
  }, [file, companyId]);
  // The soonest earnings date from today on.
  const next = useMemo(() => {
    const today = todayIso();
    return (file?.calendar || [])
      .filter((c) => c.id === companyId && c.date >= today)
      .sort((a, b) => a.date.localeCompare(b.date))[0];
  }, [file, companyId]);
  if (!file || (quarters.length === 0 && !next)) return null;

  // A company with only an earnings date (no cash-flow quarters in the file) gets a small "Next earnings"
  // section: no "quarterly, from filings" hint and no methodology note, which are about the quarters.
  if (quarters.length === 0 && next) {
    return (
      <section className="np-feed" aria-label={t("Next earnings")}>
        <FeedHead title={t("Next earnings")} updated={file.updated} />
        <NextEarnings e={next} label={false} />
      </section>
    );
  }

  return (
    <section className="np-feed" aria-label={t("Cash flow")}>
      <FeedHead title={t("Cash flow")} hint={t("quarterly, from filings")} updated={file.updated} />
      {next && <NextEarnings e={next} />}
      {quarters.length > 0 && (
        <>
          <div className="np-tbl-wrap">
            <table className="np-tbl">
              <thead>
                <tr>
                  <th>{t("Quarter")}</th>
                  {COLUMNS.map(([k, label, tip]) => (
                    <th key={k} className="num" title={t(tip)}>
                      {t(label)}
                    </th>
                  ))}
                  <th>{t("Filing")}</th>
                </tr>
              </thead>
              <tbody>
                {previewRows(quarters, open).map((q) => (
                  <tr key={q.period + "|" + q.end}>
                    <td>
                      <div className="np-tbl-main">{fmtPeriod(q.period)}</div>
                      {q.fiscal && <div className="np-tbl-sub">{q.fiscal}</div>}
                    </td>
                    {COLUMNS.map(([k]) => (
                      <td key={k} className="num">
                        <Money v={q[k]} />
                      </td>
                    ))}
                    <td>
                      {q.url ? (
                        <a
                          className="np-fd-src"
                          href={q.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          title={q.filed ? t("filed {date}", { date: fmtDay(q.filed) }) : q.url}
                        >
                          {(q.form || t("Filing")) + " ↗"}
                        </a>
                      ) : (
                        <span className="np-src">{q.form || "—"}</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <ShowAllToggle total={quarters.length} open={open} onToggle={() => setOpen((o) => !o)} />
        </>
      )}
      {/* The file's note covers every company (capex tags, 20-F / IFRS filers, leases, calendar sources):
          kept behind a toggle instead of a wall of text under every table. */}
      {quarters.length > 0 && file.note && (
        <div className="np-fd-note">
          <button className="np-linkbtn" onClick={() => setShowNote((s) => !s)} aria-expanded={showNote}>
            {showNote ? "▾ " : "▸ "}
            {t("How these are computed")}
          </button>
          {showNote && <div>{file.note}</div>}
        </div>
      )}
    </section>
  );
}
