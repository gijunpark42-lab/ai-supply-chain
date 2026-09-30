// exposure.ts — types, loader and helpers for /data/exposure.json.
//
// The file is written by derive.py (derive_exposure) on every `graph_build.py`
// run and copied into web/public/data by scripts/sync-data.mjs. It answers one
// investment question per chain: "who benefits, and how much evidence is there?"
// Nothing here recomputes the score — the Python side owns the formula; this
// module only reads the JSON and offers small pure helpers for the Exposure tab.

import { fetchJson } from "./data";
import type { GenStatus } from "./transitions";
import { t } from "./i18n";

export type ExposureSlot =
  | "revenue_growth"
  | "guidance"
  | "backlog_or_b2b"
  | "supply_status"
  | "next_catalyst";

// One role a company plays in one chain (mirrors `products[]` on a graph node).
export interface ExposureRole {
  chain: string;
  layer: string | null;
  domain: string | null;
  sector: string | null;
  sub_sector: string | null;
  product: string;
}

// A filed customer/supplier fact: "Counterparty is x% of this company's revenue".
export interface ConcentrationFact {
  counterparty: string;
  role: "customer" | "supplier" | string;
  pct: number | null; // first "%" found in the text — may be an aggregate, read `text`
  text: string;
  label: string; // source label the fact came from
  chain: string | null;
}

// The counts behind one (company, chain) score — kept so the UI can explain it.
export interface ChainStats {
  role_weight: number;
  edges: number;
  contracts: number;
  counterparties: number;
}

export interface ExposureCompany {
  ticker: string | null;
  exchange: string | null;
  country: string | null;
  status: string | null;
  chains: string[];
  primary: string | null; // first layer slug, else first domain slug
  roles: ExposureRole[];
  in_degree: number;
  out_degree: number;
  edges_with_contracts: number;
  contracts_total: number;
  counterparties: number; // distinct edge partners + folded counterparties
  signals: number; // quarterly_data entries
  latest: string | null; // "YYYY-MM-DD" of the newest source label
  days_since: number | null; // at generation time — recompute client-side for display
  freshness_bonus: number; // 0 | 1 | 2 as used in the score
  topics: Record<string, number>;
  slots: Partial<Record<ExposureSlot, string>>; // latest-dated text per screener slot
  slot_sources: Partial<Record<ExposureSlot, string>>; // and the label it came from
  generations: Record<string, GenStatus>; // transition key -> status
  concentration: ConcentrationFact[];
  score_by_chain: Record<string, number>;
  chain_stats: Record<string, ChainStats>;
}

export interface ExposureChain {
  anchor: string | null; // the company the chain file is about, when it is a node
  group: string; // chains/ sub-folder: "accelerators" | "components" | "manufacturing"
  members: string[]; // company ids, best score first
  edges: number;
  contracts: number;
}

export interface ExposureWeights {
  role: Record<string, number>;
  default_role: number;
  contract_step: number;
  contract_cap: number;
  edge_step: number;
  edge_cap: number;
  fresh_days: number;
  fresh_bonus: number;
  aging_days: number;
  aging_bonus: number;
}

export interface ExposureData {
  generated: string; // ISO date the file was built
  formula: string; // human-readable description of the score
  weights: ExposureWeights;
  transitions: { key: string; from: string[]; to: string[] }[];
  companies: Record<string, ExposureCompany>;
  chains: Record<string, ExposureChain>;
}

// ── Loader ────────────────────────────────────────────────────────────────
// One fetch per page load, shared by every mount of the tab. A failed fetch
// (404 before the first build, network error) resolves to null instead of
// throwing, so the tab can show a notice — and the cache is cleared so the next
// mount tries again rather than remembering the failure forever.
let cached: Promise<ExposureData | null> | null = null;

export function loadExposure(): Promise<ExposureData | null> {
  if (!cached) {
    cached = fetchJson<ExposureData>("/data/exposure.json").catch(() => {
      cached = null;
      return null;
    });
  }
  return cached;
}

// ── TradingView symbols ───────────────────────────────────────────────────
// TradingView wants "EXCHANGE:CODE" with its own exchange names and bare local
// codes (no Yahoo-style ".KS" / ".TW" suffixes). Exchanges not listed here have
// no reliable mapping and return null — the UI reports how many were skipped.
export function tradingViewSymbol(
  ticker: string | null | undefined,
  exchange: string | null | undefined
): string | null {
  if (!ticker || !exchange) return null;
  const t = ticker.trim().toUpperCase();
  const strip = (suffix: string) => (t.endsWith(suffix) ? t.slice(0, -suffix.length) : t);
  switch (exchange.trim().toUpperCase()) {
    case "NASDAQ":
      return `NASDAQ:${t}`;
    case "NYSE":
      return `NYSE:${t}`;
    case "KOSPI":
    case "KRX":
      return `KRX:${strip(".KS")}`;
    case "KOSDAQ":
      return `KOSDAQ:${strip(".KQ")}`;
    case "TWSE":
      return `TWSE:${strip(".TW")}`;
    case "TSE":
      return `TSE:${strip(".T")}`;
    case "XETRA":
      return `XETR:${strip(".DE")}`;
    case "SZSE":
      return `SZSE:${strip(".SZ")}`;
    case "SSE":
      return `SSE:${strip(".SS")}`;
    default:
      return null;
  }
}

// ── Freshness ─────────────────────────────────────────────────────────────
// Recomputed in the browser from `latest` (not from `days_since`), because the
// JSON may be several days old by the time someone opens the page.
export type Freshness = "fresh" | "aging" | "stale" | "none";

export function daysSince(iso: string | null | undefined, now: Date = new Date()): number | null {
  if (!iso) return null;
  const [y, m, d] = iso.split("-").map(Number);
  if (!y || !m || !d) return null;
  const then = Date.UTC(y, m - 1, d);
  const today = Date.UTC(now.getFullYear(), now.getMonth(), now.getDate());
  return Math.max(0, Math.round((today - then) / 86400000));
}

export function freshnessOf(days: number | null, w?: ExposureWeights): Freshness {
  if (days === null) return "none";
  if (days <= (w?.fresh_days ?? 90)) return "fresh";
  if (days <= (w?.aging_days ?? 180)) return "aging";
  return "stale";
}

// ── Score explanation ─────────────────────────────────────────────────────
// "role 3 + contracts 2.0 (4) + edges 1.5 (3) + fresh 2 = 8.5" — the same
// arithmetic derive.py used, spelled out for a tooltip.
export function scoreBreakdown(c: ExposureCompany, chain: string, w: ExposureWeights): string {
  const s = c.chain_stats[chain];
  if (!s) return "";
  const contracts = w.contract_step * Math.min(s.contracts, w.contract_cap);
  const edges = w.edge_step * Math.min(s.edges, w.edge_cap);
  const total = c.score_by_chain[chain];
  return (
    `${t("role")} ${s.role_weight} + ${t("contracts")} ${contracts.toFixed(1)} (${s.contracts}` +
    `${s.contracts > w.contract_cap ? ", " + t("capped") : ""}) + ${t("edges")} ${edges.toFixed(1)} (${s.edges}` +
    `${s.edges > w.edge_cap ? ", " + t("capped") : ""}) + ${t("fresh")} ${c.freshness_bonus} = ${total.toFixed(1)}`
  );
}

// ── CSV ───────────────────────────────────────────────────────────────────
// RFC-4180 style: wrap a cell in quotes when it holds a comma, quote or newline,
// and double any quote inside it.
export function csvLine(cells: (string | number | null | undefined)[]): string {
  return cells
    .map((v) => {
      const s = v === null || v === undefined ? "" : String(v);
      return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
    })
    .join(",");
}

// Chain slug -> "YYYY-MM-DD" from a source label like "NVIDIA Q2 FY2027 (08-26-2026)".
export function labelDate(label: string | null | undefined): string {
  const m = /\((\d{2})-(\d{2})-(\d{4})\)/.exec(label || "");
  return m ? `${m[3]}-${m[1]}-${m[2]}` : "";
}
