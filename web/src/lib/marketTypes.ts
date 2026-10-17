// marketTypes.ts — shapes of the daily market-data files (2026-10-17).
//
// The Python collectors in market/*.py write these to graph/*.json every night;
// scripts/sync-data.mjs copies them to /data/*.json. Nothing here is a "signal":
// these files never touch quarterly_data or the chains.
//
// Every file is OPTIONAL: a collector may not have run yet, or a source may be
// down. loadMarketJson() therefore resolves to null on a 404 / bad JSON instead
// of throwing, and each view renders nothing for a missing file.

/** A link back to where a row came from. */
export interface SourceRef {
  name: string;
  url: string;
}

// ── graph/memory_prices.json and graph/gpu_prices.json ─────────────────────

/** One daily reading: ["YYYY-MM-DD", value]. */
export type SeriesPoint = [string, number];

export interface MarketSeries {
  id: string;
  label: string;
  group: string;
  unit: string;
  source: string;
  source_url: string | null;
  points: SeriesPoint[];
  latest: { date: string; value: number; change_pct: number | null } | null;
}

export interface MarketTable {
  id: string;
  title: string;
  columns: string[];
  rows: (string | number | null)[][];
  source: string;
  /** null when every row carries its own page in a "URL" column (provider list prices). */
  source_url: string | null;
  asof: string;
}

export interface SeriesFile {
  updated: string;
  title: string;
  attribution: string;
  /** Sources switched off in market/config.json (omitted from this file). */
  hidden_sources: string[];
  series: MarketSeries[];
  tables: MarketTable[];
  notes: string[];
}

// ── graph/hyperscaler_cash.json ─────────────────────────────────────────────

export interface CashQuarter {
  /** Calendar quarter of the period end, e.g. "2026Q2". */
  period: string;
  /** The company's own fiscal label, e.g. "FY2027 Q1". */
  fiscal: string;
  /** Period end date. */
  end: string;
  capex_usd: number | null;
  ocf_usd: number | null;
  fcf_usd: number | null;
  lease_principal_usd: number | null;
  fcf_after_leases_usd: number | null;
  form: string;
  filed: string;
  accn: string;
  url: string;
}

export interface CashCompany {
  /** Graph node id ("Microsoft", "Google", ...). */
  id: string;
  ticker: string;
  quarters: CashQuarter[];
}

export interface EarningsDate {
  /** Graph node id. */
  id: string;
  ticker: string;
  date: string;
  time: "bmo" | "amc" | "unknown";
  confirmed: boolean;
  sources: SourceRef[];
}

export interface HyperscalerCash {
  updated: string;
  note: string;
  companies: CashCompany[];
  calendar: EarningsDate[];
}

// ── graph/ai_labs.json ──────────────────────────────────────────────────────

export interface LabRevenue {
  date: string;
  annualized_usd: number | null;
  type: string;
  source: string;
  url: string;
}

export interface LabFunding {
  date: string;
  round: string;
  amount_usd: number | null;
  post_money_usd: number | null;
  source: string;
  url: string;
}

export interface LabDeal {
  date: string;
  counterparty: string;
  what: string;
  gw: number | null;
  value_usd: number | null;
  source: string;
  /** The public link (SEC filing, or the company's investor-relations events page for a call). */
  url: string | null;
  /** Nodus42's saved copy of the source, when the quote was checked there (not linkable). */
  local_file?: string | null;
}

export interface AiLab {
  id: string;
  /** Graph node id when the lab is on the map, else null. */
  node_id: string | null;
  revenue: LabRevenue[];
  funding: LabFunding[];
  deals: LabDeal[];
}

export interface ModelScores {
  model: string;
  lab: string;
  release_date: string;
  scores: Record<string, number>;
  source: string;
  url: string;
}

export interface Benchmark {
  id: string;
  label: string;
  higher_is_better: boolean;
}

export interface AiLabsFile {
  updated: string;
  attribution: string;
  labs: AiLab[];
  models: ModelScores[];
  benchmarks: Benchmark[];
}

// ── Loader ──────────────────────────────────────────────────────────────────

// One fetch per file per page load: the promise itself is cached at module
// level, so the Markets tab, the Capex tab and the company panel
// (lib/companyFeeds.ts loads through here too) share the same request for
// hyperscaler_cash.json / ai_labs.json, and switching tabs never refetches.
const cache = new Map<string, Promise<unknown>>();

/** Load /data/<file>; resolves to null when the file is missing (404) or broken. */
export function loadMarketJson<T>(file: string): Promise<T | null> {
  let p = cache.get(file);
  if (!p) {
    p = fetch(`/data/${file}`)
      .then((r) => (r.ok ? r.json() : null))
      .catch(() => null);
    cache.set(file, p);
  }
  return p as Promise<T | null>;
}
