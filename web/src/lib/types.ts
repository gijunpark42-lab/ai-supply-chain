// types.ts — shapes of the curated JSON data (see merged_graph.json etc.).

export interface Product {
  chain: string;
  layer?: string | null;
  domain?: string | null;
  sector?: string | null;
  sub_sector?: string | null;
  product: string;
}

export interface QuarterlyData {
  quarter: string;
  signal: string;
  figure: string;
  chain?: string;
  // Optional tags written by enrichment (CLAUDE.md Workflow 2, JOB 5).
  topics?: string[];
  slot?: "revenue_growth" | "guidance" | "backlog_or_b2b" | "supply_status" | "next_catalyst";
  capex?: { field: string; busd?: number | null; display?: string; period?: string; metric?: string; growth?: string };
  // Present when the entry was folded from an edge whose counterparty is not a node
  // (2026-09-05 cleanup): "Customer X: ..." / "Supplier X: ..." entries.
  counterparty?: string;
  counterparty_role?: "customer" | "supplier";
}

export interface Contract {
  source: string;
  signal: string;
  units: string;
  value: string;
  date_signed: string;
  type: string;
  topics?: string[];
}

export interface GraphNode {
  id: string;
  layers: string[];
  domains: string[];
  sectors: string[];
  chains: string[];
  products: Product[];
  quarterly_data: QuarterlyData[];
  ticker: string | null;
  exchange: string | null;
  country: string;
  status: "public" | "private" | "subsidiary";
}

export interface GraphEdge {
  source: string;
  target: string;
  relationship: string;
  contracts: Contract[];
  chain: string;
  // Every chain edge is an AI supply-chain relationship: "ai" (added 2026-10-17; a graph built
  // before then has no scope, which also means "ai").
  scope?: "ai";
}

// One source of a non-AI relationship (a relations/*.json row, see relations.py).
export interface RelationRef {
  label: string; // canonical source label, e.g. "Caterpillar 10-K (02-14-2026)"
  source: string; // a saved file under transcripts/ or a public https:// URL
  quote: string; // the verbatim line, in the source's language
  date: string; // YYYY-MM-DD
  // This row's own product wording. Both companies of one relationship word it their own way, so
  // the edge keeps the first row's product as `relationship` and each ref keeps its own (graphs
  // built before the change have no per-ref product).
  product?: string;
  figure?: string;
}

// A non-AI business relationship (user decision C, 2026-10-17): merged_graph.json "other_edges",
// kept apart from `edges`. source = the supplier (or the first partner), target = the customer.
// Either end may be a company that is not a graph node.
export interface OtherEdge {
  source: string;
  target: string;
  relationship: string; // the product / service of the relationship
  relation: "supplies" | "partner";
  scope: "other";
  refs: RelationRef[];
}

export interface MergedGraph {
  nodes: GraphNode[];
  edges: GraphEdge[];
  other_edges?: OtherEdge[]; // absent in graphs built before 2026-10-17
}

export interface LogoEntry {
  file: string;
  bg: "light" | "dark";
}
export type LogoManifest = Record<string, LogoEntry>;

// ── Live quote (from /api/quote, mirrors the Python _fetch_quote output) ──
export interface LiveQuote {
  price: number | null;
  change_pct: number | null;
  year_high: number | null;
  year_low: number | null;
  currency: string;
  series: Record<string, [number, number][]>; // range -> [[epochMs, close], ...]
  as_of: string;
}

// /api/mcap response — live market cap of the node's listing (home shares for ADRs).
export interface MarketCap {
  symbol: string; // the listing the cap is computed on (2330.TW for TSM)
  adr: string | null; // the US line the node is filed under, when we looked through it
  currency: string;
  market_cap: number;
  market_cap_usd: number | null;
  adr_premium: number | null; // fraction: 0.194 = ADR 19.4% above the home shares
  fx: number | null; // units of `currency` per 1 USD
  as_of: string;
}

// /api/fundamentals response — valuation ratios (Naver / Yahoo Japan / TWSE / Yahoo Finance).
// Ratios are plain multiples (27.6 = 27.6x); roe / margins / growth / yield are
// fractions (0.39 = 39%). null = Yahoo has no value for that field.
export interface Fundamentals {
  symbol: string;
  trailing_pe: number | null;
  forward_pe: number | null;
  peg: number | null;
  pb: number | null;
  ps: number | null;
  ev_ebitda: number | null;
  ev_revenue: number | null;
  trailing_eps: number | null;
  forward_eps: number | null;
  roe: number | null;
  revenue_growth: number | null;
  gross_margin: number | null;
  op_margin: number | null;
  dividend_yield: number | null;
  target_mean: number | null;
  analysts: number | null;
  market_cap: number | null;
  currency: string | null;
  sources: string[]; // who supplied the numbers, e.g. ["Naver Finance", "Yahoo Finance"]
  as_of: string;
}

// ── The node object we feed into the 3D graph / panel (enriched at load time) ──
export interface VizNode extends GraphNode {
  primary: string;
  color: string;
  val: number;
  degree: number;
  incoming: {
    source: string;
    relationship: string;
    contracts: Contract[];
  }[];
  outgoing: {
    target: string;
    relationship: string;
    contracts: Contract[];
    chain: string;
  }[];
  // Non-AI relationships touching this company (merged_graph.json "other_edges"), shown on
  // demand in the panel. role = what the OTHER company is to this one.
  other?: OtherRelation[];
  badges: string[]; // slugs: tight/guideup/lta/capex
  lastData: string | null;
  stale: boolean;
  logo: string | null; // /logos/<file> url
  logoBg: "light" | "dark" | null;
  hasReport: boolean;
}

export interface OtherRelation {
  company: string;
  role: "customer" | "supplier" | "partner";
  product: string;
  refs: RelationRef[];
  isNode: boolean; // the other company is a graph node (its name opens its panel)
}

export interface VizLink {
  source: string;
  target: string;
  relationship: string;
  contracts: Contract[];
  chain: string;
  color: string;
  scope?: "ai" | "other"; // "other" = a non-AI relationship, drawn only on demand
  relation?: "supplies" | "partner"; // non-AI links only; a "partner" link has no direction (no arrow)
}
