"use client";

// FinancialsSection.tsx — "Financials" in the company panel (2026-10-17).
//
// A basic income-statement table, laid out like Naver Finance's 재무제표: one column per
// fiscal period (oldest → newest, left to right), then the analysts' consensus for the next
// periods as "(E)" columns. A "Quarterly" (default) | "Annual" toggle switches the periods.
// Every column header is the company's OWN period end date with its OWN fiscal label under
// it ("05-28-2026" / "Q3 26", "09-03-2026" / "FY26"): the user chose fiscal labels, not
// calendar quarters, and the dates are the real ones (a 52/53-week year ends on a weekday).
// The rows follow the user's screenshot (매출액, PER, PBR, EBITDA, EBIT, 세전손익, 세후손익,
// 당기순이익, 배당수익률, ROA), with growth rows, 영업이익, EPS and the gross margin added.
// Under them, set off as their own "Cash flow" group: operating cash flow, capex, free cash
// flow (red when negative, with QoQ / YoY) and FCF after finance leases (only when the
// company files those). The user merged the separate "Cash flow" panel section into this one
// table on 2026-10-17; for the 8 companies of /data/hyperscaler_cash.json (SEC figures) the
// collector draws the same numbers.
//
// The header also shows the next earnings date (date · BMO / AMC / time not announced ·
// confirmed / not confirmed) from /data/hyperscaler_cash.json's "calendar", which covers every
// public company. A company with a date but no financials file gets only that line.
//
// The numbers come from Yahoo Finance and the companies' own filings (SEC XBRL, DART),
// collected every night by a script into graph/financials/<company>.json → /data/financials/
// (only this company's file is fetched, found through /data/financials_index.json). Not a
// signal: own file, own section, never quarterly_data. Renders nothing when the company has
// neither a file nor an upcoming earnings date.
//
// EPS (user, 2026-10-17: "조정, GAAP, net income 다 볼 수 있게"): net income, "EPS (GAAP,
// diluted)" (the reported figure) and "EPS (adjusted)" (Yahoo's EPS on the analysts' basis:
// for US companies usually the company's adjusted / non-GAAP EPS, elsewhere usually the
// reported one) are always separate rows, each with its own QoQ / YoY. The "(E)" consensus is
// on the adjusted basis, so it sits only in the adjusted row: a GAAP figure is never compared
// with an adjusted one. The adjusted row is left out when it has no value at all. Its older
// quarters come from the collector's history (Yahoo itself lists only the last ~4).
//
// A Korean quarter whose preliminary results are filed (DART 잠정실적) but not its statements
// gets a "(P)" column with what the filing gives (revenue, operating income, ...).
//
// Money is shown in millions of the reporting currency, or in 억원 (100 million KRW) for a
// company that reports in KRW, as Naver does. Other companies get a "Convert to KRW (100M)"
// checkbox: it converts every money cell (and EPS) at TODAY's rate, read from /api/quotes
// (Yahoo's "KRW=X" / "<CUR>KRW=X" pair) only when the box is ticked. No fixed fallback rate:
// a stale constant would quietly give wrong figures, so when the rate cannot be read the
// table stays in the reporting currency and says so.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { t, useLang } from "@/lib/i18n";
import {
  fmtDay,
  loadCompanyFinancials,
  loadHyperscalerCash,
  todayIso,
  useFeed,
  type EarningsDate,
  type FeedSource,
  type FinancialsFile,
  type FinEstimate,
  type FinPeriod,
  type FinPreliminary,
} from "@/lib/companyFeeds";
import { DayChip, FeedHead, SourcesLine } from "./FeedParts";

type Tab = "quarterly" | "annual";

// What a cell holds, which decides how it is formatted:
//   money  → in display units (millions, or 100M KRW)   eps   → per share, full currency units
//   pct    → a percentage (margin, yield, ROA)           ratio → PER / PBR ("x")
//   growth → a % change, coloured green / red
type Kind = "money" | "eps" | "pct" | "ratio" | "growth";

type Num = number | null | undefined;

interface RowDef {
  key: string; // stable React key
  label: string; // English text, shown through t()
  tip?: string; // tooltip on the row label, through t()
  kind: Kind;
  sub?: boolean; // an indented growth row that belongs to the row above
  quarterlyOnly?: boolean; // QoQ rows: not on the Annual tab
  redIfNegative?: boolean; // free cash flow: a negative value is shown in red
  value: (p: FinPeriod) => Num;
  derivedFrom?: string[]; // the cell is computed when the period lists one of these in `derived`
  est?: (e: FinEstimate) => Num; // the "(E)" column's value; no `est` → "—"
  estRange?: (e: FinEstimate) => [Num, Num, Num]; // low, high, number of analysts
  prelim?: (r: FinPreliminary) => Num; // the "(P)" column's value; no `prelim` → "—"
}

// Gross margin % = gross profit / revenue (computed here, the file has both).
function grossMargin(p: FinPeriod): number | null {
  if (p.gross_profit == null || p.revenue == null || p.revenue === 0) return null;
  return (p.gross_profit / p.revenue) * 100;
}

const isNum = (v: Num): v is number => typeof v === "number" && Number.isFinite(v);

// The rows: the order of the user's Naver screenshot, plus growth rows, operating income, EPS and the gross margin.
// Net income, GAAP EPS and adjusted EPS each carry their own QoQ / YoY; only the adjusted row has the (E) consensus.
function rowsFor(): RowDef[] {
  const rows: RowDef[] = [
    {
      key: "revenue",
      label: "Total revenue",
      kind: "money",
      value: (p) => p.revenue,
      derivedFrom: ["revenue"],
      est: (e) => e.revenue_avg,
      estRange: (e) => [e.revenue_low, e.revenue_high, e.revenue_analysts],
      prelim: (r) => r.revenue,
    },
    { key: "rev-qoq", label: "QoQ %", kind: "growth", sub: true, quarterlyOnly: true, value: (p) => p.qoq?.revenue, prelim: (r) => r.qoq?.revenue },
    { key: "rev-yoy", label: "YoY %", kind: "growth", sub: true, value: (p) => p.yoy?.revenue, est: (e) => e.revenue_growth_pct, prelim: (r) => r.yoy?.revenue },
    {
      key: "per",
      label: "PER",
      tip: "Price at the period end / diluted EPS of the last four quarters (annual: of that fiscal year)",
      kind: "ratio",
      value: (p) => p.per,
      derivedFrom: ["per"],
    },
    { key: "pbr", label: "PBR", tip: "Price / book value per share, at the period end", kind: "ratio", value: (p) => p.pbr, derivedFrom: ["pbr"] },
    { key: "ebitda", label: "EBITDA", kind: "money", value: (p) => p.ebitda, derivedFrom: ["ebitda"] },
    { key: "ebit", label: "EBIT", kind: "money", value: (p) => p.ebit, derivedFrom: ["ebit"] },
    {
      key: "op",
      label: "Operating income",
      kind: "money",
      value: (p) => p.operating_income,
      derivedFrom: ["operating_income"],
      prelim: (r) => r.operating_income,
    },
    { key: "op-qoq", label: "QoQ %", kind: "growth", sub: true, quarterlyOnly: true, value: () => null, prelim: (r) => r.qoq?.operating_income },
    { key: "pretax", label: "Pre-tax income", kind: "money", value: (p) => p.pretax_income, derivedFrom: ["pretax_income"], prelim: (r) => r.pretax_income },
    {
      key: "after-tax",
      label: "Income after tax",
      tip: "Net income after tax, including minority interests",
      kind: "money",
      value: (p) => p.net_income_after_tax,
      derivedFrom: ["net_income_after_tax"],
      prelim: (r) => r.net_income_after_tax,
    },
    {
      key: "ni",
      label: "Net income",
      tip: "Net income attributable to the company's shareholders",
      kind: "money",
      value: (p) => p.net_income,
      derivedFrom: ["net_income"],
      prelim: (r) => r.net_income,
    },
    { key: "ni-qoq", label: "QoQ %", kind: "growth", sub: true, quarterlyOnly: true, value: (p) => p.qoq?.net_income },
    { key: "ni-yoy", label: "YoY %", kind: "growth", sub: true, value: (p) => p.yoy?.net_income },
    {
      key: "eps",
      label: "EPS (GAAP, diluted)",
      tip: "Reported diluted EPS, as in the financial statements (US GAAP; outside the US the company's own standard, e.g. IFRS)",
      kind: "eps",
      value: (p) => p.eps_diluted,
      derivedFrom: ["eps_diluted"],
    },
    { key: "eps-qoq", label: "QoQ %", kind: "growth", sub: true, quarterlyOnly: true, value: (p) => p.qoq?.eps_diluted },
    { key: "eps-yoy", label: "YoY %", kind: "growth", sub: true, value: (p) => p.yoy?.eps_diluted },
    {
      key: "eps-adj",
      label: "EPS (adjusted)",
      tip: "The company's adjusted (non-GAAP) EPS on the analysts' basis, as reported by Yahoo Finance; where Yahoo has no separate adjusted figure (mostly outside the US) it equals the reported EPS. The (E) consensus is on this basis",
      kind: "eps",
      value: (p) => p.eps_adjusted,
      derivedFrom: ["eps_adjusted"],
      est: (e) => e.eps_avg,
      estRange: (e) => [e.eps_low, e.eps_high, e.eps_analysts],
    },
    { key: "eps-adj-qoq", label: "QoQ %", kind: "growth", sub: true, quarterlyOnly: true, value: (p) => p.qoq?.eps_adjusted },
    { key: "eps-adj-yoy", label: "YoY %", kind: "growth", sub: true, value: (p) => p.yoy?.eps_adjusted, est: (e) => e.eps_growth_pct },
  ];
  rows.push(
    {
      key: "dy",
      label: "Dividend yield %",
      tip: "Dividends per share of the last twelve months / price at the period end",
      kind: "pct",
      value: (p) => p.dividend_yield_pct,
      derivedFrom: ["dividend_yield_pct"],
    },
    {
      key: "roa",
      label: "ROA %",
      tip: "Net income of the last four quarters (annual: of that fiscal year) / average total assets",
      kind: "pct",
      value: (p) => p.roa_pct,
      derivedFrom: ["roa_pct"],
    },
    { key: "gm", label: "Gross margin %", kind: "pct", value: grossMargin, derivedFrom: ["gross_profit", "revenue"] }
  );
  return rows;
}

// The "Cash flow" group under the income statement (2026-10-17). No (E) / (P) values: "—" there.
const CASH_ROWS: RowDef[] = [
  { key: "ocf", label: "Operating cash flow", tip: "Net cash from operating activities", kind: "money", value: (p) => p.ocf, derivedFrom: ["ocf"] },
  { key: "capex", label: "Capex", tip: "Purchases of property and equipment", kind: "money", value: (p) => p.capex, derivedFrom: ["capex"] },
  {
    key: "fcf",
    label: "Free cash flow",
    tip: "Operating cash flow minus capex",
    kind: "money",
    redIfNegative: true,
    value: (p) => p.fcf,
    derivedFrom: ["fcf"],
  },
  { key: "fcf-qoq", label: "QoQ %", kind: "growth", sub: true, quarterlyOnly: true, value: (p) => p.qoq?.fcf },
  { key: "fcf-yoy", label: "YoY %", kind: "growth", sub: true, value: (p) => p.yoy?.fcf },
  {
    key: "fcf-leases",
    label: "FCF after leases",
    tip: "Free cash flow minus finance-lease principal repayments",
    kind: "money",
    redIfNegative: true,
    value: (p) => p.fcf_after_leases,
    derivedFrom: ["fcf_after_leases"],
  },
];

// ── Next earnings (from /data/hyperscaler_cash.json "calendar") ─────────────

const TIME_SHORT: Record<EarningsDate["time"], string> = { bmo: "BMO", amc: "AMC", unknown: "time not announced" };
const TIME_LONG: Record<EarningsDate["time"], string> = {
  bmo: "before market open",
  amc: "after market close",
  unknown: "time not announced",
};

/** "Next earnings 10-28-2026 · AMC · confirmed"; the date's sources are in the tag's tooltip (and the Sources line). */
function NextEarnings({ e }: { e: EarningsDate }) {
  const time = TIME_SHORT[e.time] ? e.time : "unknown";
  const sources = (e.sources || []).map((s) => s.name).join(" · ");
  return (
    <div className="np-fin-next">
      <span className="np-fin-next-k">{t("Next earnings")}</span>
      <DayChip iso={e.date} />
      <span className="np-fin-next-sep" aria-hidden="true">
        ·
      </span>
      <span title={time === "unknown" ? undefined : t(TIME_LONG[time])}>{t(TIME_SHORT[time])}</span>
      <span className="np-fin-next-sep" aria-hidden="true">
        ·
      </span>
      <span className={"np-tag" + (e.confirmed ? " np-fin-ok" : "")} title={sources ? `${t("Sources")}: ${sources}` : undefined}>
        {e.confirmed ? t("confirmed") : t("not confirmed")}
      </span>
    </div>
  );
}

/** The file's sources, then the earnings date's (a source name already listed is not repeated). */
function withDateSources(sources: FeedSource[], next: EarningsDate | undefined): FeedSource[] {
  const out = [...sources];
  for (const s of next?.sources || []) {
    if (!out.some((o) => o.name === s.name)) out.push(s);
  }
  return out;
}

// A table column: a reported period, a quarter's preliminary results, or the analysts' estimate.
type Col = { kind: "period"; p: FinPeriod } | { kind: "prelim"; r: FinPreliminary } | { kind: "est"; e: FinEstimate };

// The tab's columns: its periods oldest → newest, the preliminary results of the next quarter (quarterly tab),
// then its estimates. An estimate whose period is already reported (same label, or it ends on / before the
// newest period) is dropped.
function columnsFor(file: FinancialsFile, tab: Tab): Col[] {
  const periods = [...(tab === "quarterly" ? file.quarterly : file.annual)].sort((a, b) =>
    (a.end || "").localeCompare(b.end || "")
  );
  const newest = periods.length ? periods[periods.length - 1].end : "";
  const labels = new Set(periods.map((p) => p.label));
  const prelim =
    tab === "quarterly" && file.preliminary && !labels.has(file.preliminary.label) && file.preliminary.end > newest
      ? [file.preliminary]
      : [];
  const ests = (tab === "quarterly" ? [file.estimates?.quarter] : [file.estimates?.fy, file.estimates?.next_fy]).filter(
    (e): e is FinEstimate => !!e && !!e.label && !labels.has(e.label) && !(e.end && newest && e.end <= newest)
  );
  return [
    ...periods.map((p): Col => ({ kind: "period", p })),
    ...prelim.map((r): Col => ({ kind: "prelim", r })),
    ...ests.map((e): Col => ({ kind: "est", e })),
  ];
}

// ── Number formatting ───────────────────────────────────────────────────────

// 1234.5 → "1,234.5" with exactly `digits` decimals; a negative gets a real minus sign.
function num(v: number, digits: number): string {
  const s = Math.abs(v).toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
  return (v < 0 ? "−" : "") + s;
}

// Money in display units: no decimals from 100 up ("251,113"), one below, two below 10.
const fmtUnits = (v: number) => num(v, Math.abs(v) >= 100 ? 0 : Math.abs(v) >= 10 ? 1 : 2);
// EPS: two decimals ("2.31"), none from 1,000 up (a KRW EPS: "4,950").
const fmtEps = (v: number) => num(v, Math.abs(v) >= 1000 ? 0 : 2);
// A % change: "+12.3", "−4.5", "+1,250".
const fmtGrowth = (v: number) => (v > 0 ? "+" : "") + num(v, Math.abs(v) >= 100 ? 0 : 1);

/** How the file's numbers turn into what the table shows. */
interface Scale {
  money: number; // display = value × money
  eps: number; // display = EPS × eps
  krw: boolean; // shown in KRW: EPS in whole won, no decimals
}

function fmtCell(v: number, kind: Kind, scale: Scale): string {
  if (kind === "money") return fmtUnits(v * scale.money);
  if (kind === "eps") return scale.krw ? num(v * scale.eps, 0) : fmtEps(v * scale.eps);
  if (kind === "growth") return fmtGrowth(v);
  return num(v, 2); // pct and ratio
}

// Growth cells are green when up, red when down.
const growthClass = (kind: Kind, v: number) =>
  kind !== "growth" ? undefined : v > 0 ? "np-fin-up" : v < 0 ? "np-fin-down" : undefined;

// ── Today's KRW rate for the conversion (fetched only when the box is ticked) ──

const krwRates = new Map<string, Promise<number | null>>();

/** KRW per 1 unit of `currency`, from /api/quotes (Yahoo "KRW=X" for USD, else "<CUR>KRW=X"); null when unavailable. */
function loadKrwRate(currency: string): Promise<number | null> {
  let p = krwRates.get(currency);
  if (!p) {
    const symbol = currency === "USD" ? "KRW=X" : `${currency}KRW=X`;
    // /api/quotes returns just the last price (cached for 20 s), not /api/quote's four chart ranges
    p = fetch(`/api/quotes?symbols=${encodeURIComponent(symbol)}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d: { quotes?: Record<string, { price?: unknown }> } | null) => {
        const price = d?.quotes?.[symbol]?.price;
        return typeof price === "number" && price > 0 ? price : null;
      })
      .catch(() => null);
    krwRates.set(currency, p);
    // a failed read is not kept, so ticking the box again later retries
    p.then((rate) => {
      if (rate == null) krwRates.delete(currency);
    });
  }
  return p;
}

// ── The section ─────────────────────────────────────────────────────────────

export default function FinancialsSection({ companyId }: { companyId: string }) {
  useLang(); // re-render on a language change
  // Wrapped, so "loaded, and this company has no file" (file: null) differs from "still loading" (null).
  const load = useCallback(() => loadCompanyFinancials(companyId).then((file) => ({ companyId, file })), [companyId]);
  const loaded = useFeed(load);
  const done = loaded?.companyId === companyId; // never show the previous company's numbers
  const file = done ? loaded.file : null;

  // The soonest earnings date from today on (hyperscaler_cash.json, loaded once per page for every panel / tab).
  const cash = useFeed(loadHyperscalerCash);
  const next = useMemo(() => {
    const today = todayIso();
    return (cash?.calendar || [])
      .filter((c) => c.id === companyId && c.date >= today)
      .sort((a, b) => a.date.localeCompare(b.date))[0];
  }, [cash, companyId]);

  // Both choices stay as they are when another company is opened.
  const [tabPick, setTab] = useState<Tab>("quarterly");
  const [toKrw, setToKrw] = useState(false);
  const [rate, setRate] = useState<{ currency: string; value: number | null } | null>(null);
  const [showNotes, setShowNotes] = useState(false); // the file's notes, behind a toggle
  useEffect(() => setShowNotes(false), [companyId]);

  const currency = file?.currency || "USD";
  const isKrw = currency === "KRW";

  // Read the KRW rate the first time the box is ticked for this currency.
  useEffect(() => {
    if (!toKrw || isKrw || !file) return;
    let alive = true;
    loadKrwRate(currency).then((value) => {
      if (alive) setRate({ currency, value });
    });
    return () => {
      alive = false;
    };
  }, [toKrw, isKrw, currency, file]);

  // A tab with no periods falls back to the other one.
  const tab: Tab =
    file && tabPick === "quarterly" && file.quarterly.length === 0
      ? "annual"
      : file && tabPick === "annual" && file.annual.length === 0
        ? "quarterly"
        : tabPick;
  const cols = file ? columnsFor(file, tab) : [];

  // The newest columns are on the right: on a narrow screen, start scrolled to them.
  const wrapRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = wrapRef.current;
    if (el) el.scrollLeft = el.scrollWidth;
  }, [companyId, tab, cols.length]);

  if (!file || (file.quarterly.length === 0 && file.annual.length === 0)) {
    // No statements: just the next earnings date, as a small header line (once the file lookup is done, so the
    // line does not flash before a table that is still loading).
    if (!done || !next) return null;
    return (
      <section className="np-feed np-fin np-fin-only" aria-label={t("Next earnings")}>
        <NextEarnings e={next} />
      </section>
    );
  }

  // Display units. The file holds money in `unit`s (millions) of `currency`.
  const rateReady = toKrw && !isKrw && rate?.currency === currency ? rate.value : null;
  const converted = rateReady != null;
  const scale: Scale = isKrw
    ? { money: file.unit / 1e8, eps: 1, krw: true } // 억원, as Naver shows Korean companies
    : converted
      ? { money: (file.unit * rateReady) / 1e8, eps: rateReady, krw: true }
      : { money: file.unit / 1e6, eps: 1, krw: false };
  const unitLine =
    isKrw || converted
      ? t("Unit: KRW 100 millions; %, x (EPS in KRW)")
      : t("Unit: {cur} millions; %, x (EPS in {cur})", { cur: currency });

  const shownRows = (defs: RowDef[]) =>
    defs.filter(
      (r) =>
        (tab === "quarterly" || !r.quarterlyOnly) &&
        // a row with nothing to show in any column (the QoQ under operating income without (P), FCF after leases
        // for a company without finance-lease figures) is left out
        cols.some((c) =>
          isNum(c.kind === "period" ? r.value(c.p) : c.kind === "prelim" ? r.prelim?.(c.r) : r.est?.(c.e))
        )
    );
  const rows = shownRows(rowsFor());
  const cashRows = shownRows(CASH_ROWS);
  const hasEst = cols.some((c) => c.kind === "est");
  const prelimCol = cols.find((c): c is Extract<Col, { kind: "prelim" }> => c.kind === "prelim");
  const adjShown = rows.some((r) => r.key === "eps-adj");
  let hasDerived = false; // set while the cells render, for the footnote

  function cell(r: RowDef, c: Col, i: number) {
    if (c.kind === "est") {
      const v = r.est?.(c.e);
      if (!isNum(v)) return <td key={i} className="np-fin-est"><span className="np-fin-na">—</span></td>;
      const [low, high, n] = r.estRange?.(c.e) || [null, null, null];
      const tip = [
        isNum(n) ? t("Average of {n} analysts", { n }) : "",
        isNum(low) && isNum(high) ? t("low {low} · high {high}", { low: fmtCell(low, r.kind, scale), high: fmtCell(high, r.kind, scale) }) : "",
      ]
        .filter(Boolean)
        .join(" · ");
      return (
        <td key={i} className="np-fin-est" title={tip || undefined}>
          <span className={growthClass(r.kind, v)}>{fmtCell(v, r.kind, scale)}</span>
          {isNum(low) && isNum(high) && (
            <div className="np-fin-est-r">
              {fmtCell(low, r.kind, scale)}–{fmtCell(high, r.kind, scale)}
            </div>
          )}
        </td>
      );
    }
    if (c.kind === "prelim") {
      const v = r.prelim?.(c.r);
      return (
        <td key={i} className="np-fin-pre">
          {isNum(v) ? <span className={growthClass(r.kind, v)}>{fmtCell(v, r.kind, scale)}</span> : <span className="np-fin-na">—</span>}
        </td>
      );
    }
    const v = r.value(c.p);
    if (!isNum(v)) return <td key={i}><span className="np-fin-na">—</span></td>;
    const derived = !!r.derivedFrom && (c.p.derived || []).some((f) => r.derivedFrom!.includes(f));
    if (derived) hasDerived = true;
    return (
      <td key={i}>
        <span className={growthClass(r.kind, v) ?? (r.redIfNegative && v < 0 ? "np-fin-down" : undefined)}>
          {fmtCell(v, r.kind, scale)}
        </span>
        {derived && (
          <sup className="np-fin-star" title={t("computed from other reported figures")}>
            *
          </sup>
        )}
      </td>
    );
  }

  const rowEl = (r: RowDef) => (
    <tr key={r.key} className={r.sub ? "np-fin-subrow" : undefined}>
      <th scope="row" className="np-fin-k" title={r.tip ? t(r.tip) : undefined}>
        {t(r.label)}
      </th>
      {cols.map((c, i) => cell(r, c, i))}
    </tr>
  );
  const body = rows.map(rowEl);
  const cashBody = cashRows.map(rowEl);

  return (
    <section className="np-feed np-fin" aria-label={t("Financials")}>
      <FeedHead title={t("Financials")} hint={t("company fiscal periods")} updated={file.updated} />
      {next && <NextEarnings e={next} />}

      <div className="np-fin-bar">
        <div className="np-fin-seg" role="group" aria-label={t("Period")}>
          <button
            type="button"
            aria-pressed={tab === "quarterly"}
            disabled={file.quarterly.length === 0}
            onClick={() => setTab("quarterly")}
          >
            {t("Quarterly")}
          </button>
          <button
            type="button"
            aria-pressed={tab === "annual"}
            disabled={file.annual.length === 0}
            onClick={() => setTab("annual")}
          >
            {t("Annual")}
          </button>
        </div>
        {!isKrw && (
          <label className="np-fin-krw">
            <input type="checkbox" checked={toKrw} onChange={(e) => setToKrw(e.target.checked)} />
            {t("Convert to KRW (100M)")}
          </label>
        )}
        {toKrw && !isKrw && (
          <span className="np-fin-fx">
            {rate?.currency !== currency
              ? t("Loading KRW rate…")
              : converted
                ? t("at today's rate: 1 {cur} = {rate} KRW", {
                    cur: currency,
                    rate: rateReady.toLocaleString("en-US", { maximumFractionDigits: 2 }),
                  })
                : t("KRW rate unavailable, shown in {cur}", { cur: currency })}
          </span>
        )}
      </div>

      <div className="np-fin-wrap" ref={wrapRef}>
        <table className="np-fin-tbl" aria-label={t("Financials") + " · " + (tab === "quarterly" ? t("Quarterly") : t("Annual"))}>
          <thead>
            <tr>
              <th scope="col" className="np-fin-k">
                <div>{t("Period end")}</div>
                <div className="np-fin-h-sub">{t("Fiscal period")}</div>
              </th>
              {cols.map((c, i) =>
                c.kind === "period" ? (
                  <th scope="col" key={i}>
                    <div>{fmtDay(c.p.end)}</div>
                    <div className="np-fin-h-sub">{c.p.label}</div>
                  </th>
                ) : c.kind === "prelim" ? (
                  <th
                    scope="col"
                    key={i}
                    className="np-fin-pre"
                    title={c.r.filed ? t("Preliminary results filed {date}", { date: fmtDay(c.r.filed) }) : undefined}
                  >
                    <div>{fmtDay(c.r.end)}</div>
                    <div className="np-fin-h-sub">{c.r.label} (P)</div>
                  </th>
                ) : (
                  <th scope="col" key={i} className="np-fin-est" title={t("Analyst consensus estimate")}>
                    <div>{c.e.end ? fmtDay(c.e.end) : t("estimate")}</div>
                    <div className="np-fin-h-sub">{c.e.label} (E)</div>
                  </th>
                )
              )}
            </tr>
          </thead>
          <tbody>{body}</tbody>
          {cashRows.length > 0 && (
            <tbody className="np-fin-cf">
              {/* the group's heading row: the label sits in the sticky first column, so it stays in view while the
                  numbers scroll sideways; the other cells keep their column's (E) / (P) shading */}
              <tr className="np-fin-grouprow">
                <th scope="rowgroup" className="np-fin-k">
                  {t("Cash flow")}
                </th>
                {cols.map((c, i) => (
                  <td key={i} className={c.kind === "est" ? "np-fin-est" : c.kind === "prelim" ? "np-fin-pre" : undefined} />
                ))}
              </tr>
              {cashBody}
            </tbody>
          )}
        </table>
      </div>

      <div className="np-fd-note">
        <div>{unitLine}</div>
        {prelimCol && (
          <div>
            {t("(P): preliminary results the company filed on {date}; the full statements follow", {
              date: fmtDay(prelimCol.r.filed || ""),
            })}
            {prelimCol.r.url && (
              <>
                {" "}
                <a className="np-fd-src" href={prelimCol.r.url} target="_blank" rel="noopener noreferrer">
                  DART ↗
                </a>
              </>
            )}
          </div>
        )}
        {hasEst && <div>{t("(E): analyst consensus average, with the low–high range under it")}</div>}
        {adjShown && (
          <div>
            {t("EPS (adjusted) and its (E) consensus: the company's adjusted (non-GAAP) EPS on the analysts' basis, as reported by Yahoo Finance; EPS (GAAP, diluted) is the reported figure. Each is compared only with itself")}
          </div>
        )}
        {hasDerived && <div>{t("* computed from other reported figures (e.g. a fiscal Q4 = FY minus Q1–Q3)")}</div>}
        {file.notes.length > 0 && (
          <>
            <button className="np-linkbtn" onClick={() => setShowNotes((s) => !s)} aria-expanded={showNotes}>
              {showNotes ? "▾ " : "▸ "}
              {t("How these are computed")}
            </button>
            {showNotes && (
              <ul className="np-fin-notes">
                {file.notes.map((n, i) => (
                  <li key={i}>{n}</li>
                ))}
              </ul>
            )}
          </>
        )}
      </div>
      <SourcesLine sources={withDateSources(file.sources, next)} />
    </section>
  );
}
