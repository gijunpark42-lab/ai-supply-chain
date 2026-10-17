// companyFeeds.ts — the daily market-data files shown in the company panel (2026-10-17).
//
// The nightly routine runs script-only collectors (market/*.py, no model tokens) that
// write four files into graph/, copied to /data/ by web/scripts/sync-data.mjs:
//
//   /data/financing.json          debt / equity / credit-facility / rating events per company
//   /data/insiders_index.json     node id → /data/insiders/<company>.json (insider buys, sells,
//                                 option exercises …), split per company so a panel loads only its own
//   /data/hyperscaler_cash.json   capex, operating cash flow, FCF per quarter + earnings dates
//   /data/ai_labs.json            AI-lab revenue run-rate, funding, deals, model benchmarks
//
// These are NOT signals: they never enter quarterly_data, badges, freshness or timelines.
// Every row carries the name and URL of the source it came from.
//
// Each file is fetched at most once per page load: every load goes through
// loadMarketJson() of lib/marketTypes.ts, whose module-level promise cache the Markets and
// Capex tabs share, so hyperscaler_cash.json / ai_labs.json are requested once for the
// whole page. A missing file (404 — the collector has not run yet) or a network error
// yields an EMPTY file, so the panel works before the data exists: a section with no rows
// for the company simply does not render. The shapes of hyperscaler_cash.json and
// ai_labs.json are defined once, in lib/marketTypes.ts, and re-exported here.

import { useEffect, useState } from "react";
import {
  loadMarketJson,
  type AiLab,
  type AiLabsFile,
  type Benchmark,
  type CashCompany,
  type CashQuarter,
  type EarningsDate,
  type HyperscalerCash,
  type LabDeal,
  type LabFunding,
  type LabRevenue,
  type ModelScores,
} from "./marketTypes";

// ── Shared ──────────────────────────────────────────────────────────────────

export interface FeedSource {
  name: string;
  url: string;
}

// ── /data/insiders_index.json + /data/insiders/<company>.json ───────────────

export type InsiderType = "buy" | "sell" | "option_exercise" | "tax_withholding" | "grant" | "gift" | "other";

export interface InsiderTrade {
  date: string; // trade date, YYYY-MM-DD
  filed: string | null; // filing date, YYYY-MM-DD
  insider: string; // the person / entity that traded
  role: string | null; // "Director", "CEO", "10% owner" …
  code: string | null; // the regulator's transaction code (SEC Form 4: P, S, M, F, A, G …)
  type: InsiderType;
  shares: number | null;
  price: number | null; // per share, in `currency`
  value: number | null; // shares × price, in `currency`
  currency: string | null; // "USD", "KRW", "JPY" …
  owned_after: number | null; // shares held after the trade
  plan_10b5_1: boolean | null; // made under a pre-arranged Rule 10b5-1 plan (US only)
  market: string | null; // "US", "KR" …
  source: string; // source name, e.g. "SEC EDGAR Form 4"
  url: string; // the filing
}

// Split per company on 2026-10-17 (one 10 MB file was downloaded the first time any panel opened):
// /data/insiders_index.json maps node id → file, and /data/insiders/<file> holds that company's rows.
export interface InsidersIndex {
  updated: string;
  sources: FeedSource[];
  companies: Record<string, { file: string; count: number; latest: string | null }>;
}

/** One company's insider trades, as the panel uses them. */
export interface CompanyInsiders {
  company: string; // node id these rows belong to
  updated: string;
  sources: FeedSource[];
  rows: InsiderTrade[]; // newest first, last 365 days
}

// ── /data/financing.json ────────────────────────────────────────────────────

export type FinancingType =
  | "debt"
  | "convertible"
  | "equity"
  | "credit_facility"
  | "abs"
  | "lease_financing"
  | "rating"
  | "other";

export interface FinancingItem {
  date: string; // YYYY-MM-DD
  type: FinancingType;
  title: string;
  amount: number | null; // in `currency`
  currency: string | null;
  amount_usd: number | null;
  detail: string | null;
  form: string | null; // "8-K", "424B2", "S-3" …
  market: string | null;
  source: string;
  url: string;
}

export interface FinancingFile {
  updated: string;
  sources: FeedSource[];
  companies: Record<string, FinancingItem[]>; // node id → newest first, last 365 days
}

// ── /data/hyperscaler_cash.json and /data/ai_labs.json (shapes in lib/marketTypes.ts) ──

export type { AiLabsFile, Benchmark, CashCompany, CashQuarter, EarningsDate, LabDeal, LabFunding, LabRevenue };
export type HyperscalerCashFile = HyperscalerCash;
export type Lab = AiLab;
export type LabModel = ModelScores;

/** A revenue point that is an annualized snapshot ("run rate", "ARR", "annualized from period revenue"),
 *  not a calendar-year total ("full-year revenue"): the only kind a run-rate figure or line may use. */
export function isRunRate(type: string | null | undefined): boolean {
  return /run[- ]?rate|\barr\b|annuali[sz]ed/i.test(type || "");
}

// ── Loaders (one fetch per file per page load) ──────────────────────────────

const cache = new Map<string, Promise<unknown>>();

// Load /data/<file> once (through loadMarketJson's shared request); any failure (404, network,
// bad JSON) resolves to `empty`. The missing top-level fields of a partial file are filled in
// from `empty` too.
function loadOnce<T extends object>(file: string, empty: T): Promise<T> {
  let p = cache.get(file) as Promise<T> | undefined;
  if (!p) {
    p = loadMarketJson<Partial<T>>(file).then((data) => (data ? { ...empty, ...data } : empty));
    cache.set(file, p);
  }
  return p;
}

export const loadInsidersIndex = () =>
  loadOnce<InsidersIndex>("insiders_index.json", { updated: "", sources: [], companies: {} });

/** The small index first, then only this company's file (each fetched once per page load). */
export function loadCompanyInsiders(companyId: string): Promise<CompanyInsiders> {
  return loadInsidersIndex().then((idx) => {
    const entry = idx.companies?.[companyId];
    const empty: CompanyInsiders = { company: companyId, updated: idx.updated, sources: idx.sources || [], rows: [] };
    if (!entry?.file) return empty;
    return loadMarketJson<{ updated?: string; rows?: InsiderTrade[] }>(`insiders/${entry.file}`).then((f) =>
      f ? { ...empty, updated: f.updated || idx.updated, rows: f.rows || [] } : empty,
    );
  });
}

export const loadFinancing = () =>
  loadOnce<FinancingFile>("financing.json", { updated: "", sources: [], companies: {} });

export const loadHyperscalerCash = () =>
  loadOnce<HyperscalerCashFile>("hyperscaler_cash.json", { updated: "", note: "", companies: [], calendar: [] });

export const loadAiLabs = () =>
  loadOnce<AiLabsFile>("ai_labs.json", { updated: "", attribution: "", labs: [], models: [], benchmarks: [] });

/**
 * The loaded file, or null while it is loading. `load` must be one of the stable
 * loaders above (not an inline arrow), so the effect runs once per component.
 */
export function useFeed<T>(load: () => Promise<T>): T | null {
  const [data, setData] = useState<T | null>(null);
  useEffect(() => {
    let alive = true; // ignore a late answer after the component unmounted
    load().then((d) => {
      if (alive) setData(d);
    });
    return () => {
      alive = false;
    };
  }, [load]);
  return data;
}

// ── Formatting (pure functions) ─────────────────────────────────────────────

const CURRENCY_SYMBOL: Record<string, string> = {
  USD: "$", EUR: "€", GBP: "£", JPY: "¥", KRW: "₩", TWD: "NT$", HKD: "HK$", CNY: "¥",
};

/** "2026-10-15" → "10-15-2026", the MM-DD-YYYY form every date chip in the panel uses. */
export function fmtDay(iso: string | null | undefined): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || "");
  return m ? `${m[2]}-${m[3]}-${m[1]}` : iso || "";
}

/** "2026Q2" → "Q2 2026" (left as it is when it has another shape). */
export function fmtPeriod(period: string): string {
  const m = /^(\d{4})Q([1-4])$/.exec(period || "");
  return m ? `Q${m[2]} ${m[1]}` : period;
}

/** A compact money amount: 2.4e9 USD → "$2.4B", 1.25e9 → "$1.25B", −3.1e8 → "−$310M", 5.5e12 KRW → "₩5.5T". */
export function fmtMoney(v: number | null | undefined, currency: string | null | undefined = "USD"): string {
  if (v == null || !Number.isFinite(v)) return "";
  const cur = (currency || "USD").toUpperCase();
  const sym = CURRENCY_SYMBOL[cur];
  const a = Math.abs(v);
  const [n, unit] =
    a >= 1e12 ? [a / 1e12, "T"] : a >= 1e9 ? [a / 1e9, "B"] : a >= 1e6 ? [a / 1e6, "M"] : a >= 1e3 ? [a / 1e3, "K"] : [a, ""];
  // two decimals below 10 ($1.25B, as a "$1.25B notes" title says), one below 100, none above
  const digits = unit === "" ? (a < 100 && !Number.isInteger(a) ? 2 : 0) : n >= 100 ? 0 : n >= 10 ? 1 : 2;
  const num = n.toLocaleString("en-US", { minimumFractionDigits: 0, maximumFractionDigits: digits }) + unit;
  return (v < 0 ? "−" : "") + (sym ? sym + num : num + " " + cur);
}

/** A per-share price: 123.456 USD → "$123.46", 182000 KRW → "₩182,000". */
export function fmtPrice(v: number | null | undefined, currency: string | null | undefined = "USD"): string {
  if (v == null || !Number.isFinite(v)) return "";
  const cur = (currency || "USD").toUpperCase();
  const sym = CURRENCY_SYMBOL[cur];
  const digits = v >= 1000 ? 0 : 2;
  const num = v.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
  return sym ? sym + num : num + " " + cur;
}

/** A share count with thousands separators: 1234567 → "1,234,567". */
export function fmtCount(v: number | null | undefined): string {
  return v == null || !Number.isFinite(v) ? "" : Math.round(v).toLocaleString("en-US");
}

/** A benchmark score: integers stay whole, everything else gets one decimal. */
export function fmtScore(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return Number.isInteger(v) ? String(v) : v.toFixed(1);
}

/** Today's local date as YYYY-MM-DD (compared against earnings dates). */
export function todayIso(): string {
  const d = new Date();
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}
