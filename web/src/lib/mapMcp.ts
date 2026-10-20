// mapMcp.ts — the read-only lookups behind the /api/mcp server (user, 2026-10-20: use the enriched map from the
// phone too, and keep it updated with every enrich). The same nine tools as the local nodus42_mcp.py, over the
// same files: public/data/merged_graph.json, company_metrics.json, company_ko.json and evidence.json, shipped
// with the /api/mcp function by next.config.mjs (outputFileTracingIncludes). Every nightly publish redeploys the
// site with fresh files, so the MCP answers from the newest map without any extra step.

import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import type { Contract, GraphEdge, GraphNode, MergedGraph, OtherEdge, QuarterlyData } from "./types";

const DATA = path.join(process.cwd(), "public", "data");

// ── Loading: each file is read once per warm server instance ───────────────
const cache = new Map<string, unknown>();

function load<T>(file: string): T {
  if (!cache.has(file)) cache.set(file, JSON.parse(fs.readFileSync(path.join(DATA, file), "utf8")));
  return cache.get(file) as T;
}

interface Index {
  g: MergedGraph;
  nodes: Map<string, GraphNode>;
  out: Map<string, GraphEdge[]>; // edges where the company is the supplier
  in: Map<string, GraphEdge[]>; // edges where the company is the customer
  other: Map<string, OtherEdge[]>; // non-AI relationships, either side
}

let index: Index | null = null;

function push<T>(map: Map<string, T[]>, key: string, value: T) {
  const list = map.get(key);
  if (list) list.push(value);
  else map.set(key, [value]);
}

function graph(): Index {
  if (!index) {
    const g = load<MergedGraph>("merged_graph.json");
    const ix: Index = { g, nodes: new Map(), out: new Map(), in: new Map(), other: new Map() };
    for (const n of g.nodes) ix.nodes.set(n.id, n);
    for (const e of g.edges) {
      push(ix.out, e.source, e);
      push(ix.in, e.target, e);
    }
    for (const e of g.other_edges || []) {
      push(ix.other, e.source, e);
      push(ix.other, e.target, e);
    }
    index = ix;
  }
  return index;
}

const koNames = () => load<Record<string, string[]>>("company_ko.json");

// ── Helpers ────────────────────────────────────────────────────────────────

// "NVIDIA Q2 FY2027 (08-26-2026)" -> "2026-08-26" ("" when the label carries no date)
export function labelDate(label: string | undefined): string {
  const m = /\((\d{2})-(\d{2})-(\d{4})\)\s*$/.exec(label || "");
  return m ? `${m[3]}-${m[1]}-${m[2]}` : "";
}

// A node id from a name, ticker or Korean name (case-insensitive), else the close matches.
function findCompany(name: string): { id?: string; candidates: string[] } {
  const { nodes } = graph();
  const q = name.trim().toLowerCase();
  for (const id of nodes.keys()) if (id.toLowerCase() === q) return { id, candidates: [] };
  for (const [id, n] of nodes)
    if (q && (n.ticker || "").toLowerCase().split(".")[0] === q.split(".")[0]) return { id, candidates: [] };
  for (const [id, names] of Object.entries(koNames()))
    if (nodes.has(id) && names.some((k) => k.toLowerCase() === q)) return { id, candidates: [] };
  const hits = [...nodes.keys()].filter((id) => id.toLowerCase().includes(q));
  if (hits.length === 1) return { id: hits[0], candidates: [] };
  return { candidates: hits.sort((a, b) => a.length - b.length).slice(0, 15) };
}

function notFound(name: string, candidates: string[]) {
  return candidates.length
    ? { error: `'${name}' matches several companies; ask again with one of them`, candidates }
    : { error: `'${name}' is not a company on the map (try search_companies)` };
}

type Fact = Record<string, string | undefined>;

// One quarterly_data entry or contract, in a compact, citable shape.
function entry(q: QuarterlyData | Contract, company?: string, counterparty?: string): Fact {
  const raw = q as unknown as Record<string, string | undefined>;
  const label = raw.quarter || raw.source || "";
  const out: Fact = { source: label, date: labelDate(label), signal: raw.signal };
  for (const key of ["figure", "units", "value", "date_signed", "type", "chain"]) {
    const v = raw[key];
    if (v && v !== "no specific figure" && v !== "not stated") out[key] = v;
  }
  if (company) out.company = company;
  if (counterparty) out.counterparty = counterparty;
  return out;
}

const newestFirst = (a: Fact, b: Fact) => (b.date || "").localeCompare(a.date || "");

function edgeSummary(e: GraphEdge, side: "source" | "target") {
  const deals = [...(e.contracts || [])].sort((a, b) => labelDate(b.source).localeCompare(labelDate(a.source)));
  return {
    company: e[side],
    relationship: e.relationship,
    chain: e.chain,
    contracts: deals.length,
    latest: deals.length ? entry(deals[0]) : null,
  };
}

const matchesAll = (row: Fact, words: string[]) => {
  const text = JSON.stringify(row).toLowerCase();
  return words.every((w) => text.includes(w));
};
const wordsOf = (s: string) => s.toLowerCase().split(/\s+/).filter(Boolean);

// ── The tools (same names and answers as nodus42_mcp.py) ───────────────────

export function searchCompanies(query: string, limit = 20) {
  const { nodes } = graph();
  const ko = koNames();
  const words = wordsOf(query);
  const found: { score: [number, number]; id: string; n: GraphNode }[] = [];
  for (const [id, n] of nodes) {
    const text = [id, n.ticker || "", (ko[id] || []).join(" "), n.sectors.join(" "),
      n.products.map((p) => p.product || "").join(" ")].join(" ").toLowerCase();
    if (words.length && words.every((w) => text.includes(w))) {
      const rank = query.toLowerCase() === id.toLowerCase() ? 0 : id.toLowerCase().includes(words[0]) ? 1 : 2;
      found.push({ score: [rank, -n.quarterly_data.length], id, n });
    }
  }
  found.sort((a, b) => a.score[0] - b.score[0] || a.score[1] - b.score[1]);
  return found.slice(0, limit).map(({ id, n }) => ({
    name: id, ticker: n.ticker, exchange: n.exchange, country: n.country, status: n.status,
    layers: n.layers, sectors: n.sectors, chains: n.chains,
  }));
}

export function companyProfile(company: string, entries = 25) {
  const { id, candidates } = findCompany(company);
  if (!id) return notFound(company, candidates);
  const ix = graph();
  const n = ix.nodes.get(id)!;
  const facts = [...n.quarterly_data].sort((a, b) => labelDate(b.quarter).localeCompare(labelDate(a.quarter)));
  const metrics = load<Record<string, unknown>>("company_metrics.json")[id] ?? null;
  const others = (ix.other.get(id) || []).slice(0, 60).map((e) => ({
    source: e.source, target: e.target, relation: e.relation, relationship: e.relationship,
    source_label: e.refs?.[0]?.label,
  }));
  return {
    name: id, ticker: n.ticker, exchange: n.exchange, country: n.country, status: n.status,
    placements: n.products.map((p) => {
      const out: Record<string, string> = {};
      for (const k of ["chain", "layer", "domain", "sector", "sub_sector", "product"] as const) {
        const v = (p as unknown as Record<string, string | null>)[k];
        if (v) out[k] = v;
      }
      return out;
    }),
    suppliers: (ix.in.get(id) || []).map((e) => edgeSummary(e, "source")),
    customers: (ix.out.get(id) || []).map((e) => edgeSummary(e, "target")),
    other_relationships: others,
    screener: metrics,
    facts_total: facts.length,
    latest_facts: facts.slice(0, entries).map((q) => entry(q)),
  };
}

export function companyEntries(company: string, query = "", since = "", limit = 50) {
  const { id, candidates } = findCompany(company);
  if (!id) return notFound(company, candidates);
  const ix = graph();
  let rows: Fact[] = ix.nodes.get(id)!.quarterly_data.map((q) => entry(q));
  for (const e of [...(ix.out.get(id) || []), ...(ix.in.get(id) || [])])
    rows.push(...(e.contracts || []).map((c) => entry(c, e.source, e.target)));
  const words = wordsOf(query);
  rows = rows.filter((r) => matchesAll(r, words) && (!since || (r.date || "") >= since)).sort(newestFirst);
  return { company: id, matches: rows.length, entries: rows.slice(0, limit) };
}

export function searchEntries(query: string, company = "", chain = "", since = "", limit = 40) {
  const ix = graph();
  let only: string | undefined;
  if (company) {
    const hit = findCompany(company);
    if (!hit.id) return notFound(company, hit.candidates);
    only = hit.id;
  }
  const words = wordsOf(query);
  const rows: Fact[] = [];
  for (const [id, n] of ix.nodes) {
    if (only && id !== only) continue;
    for (const q of n.quarterly_data) if (!chain || q.chain === chain) rows.push(entry(q, id));
  }
  for (const e of ix.g.edges) {
    if ((only && only !== e.source && only !== e.target) || (chain && e.chain !== chain)) continue;
    rows.push(...(e.contracts || []).map((c) => entry(c, e.source, e.target)));
  }
  const hits = rows.filter((r) => matchesAll(r, words) && (!since || (r.date || "") >= since)).sort(newestFirst);
  return { matches: hits.length, entries: hits.slice(0, limit) };
}

export function relationship(companyA: string, companyB: string) {
  const a = findCompany(companyA);
  if (!a.id) return notFound(companyA, a.candidates);
  const b = findCompany(companyB);
  if (!b.id) return notFound(companyB, b.candidates);
  const ix = graph();
  const pair = (s: string, t: string) => (s === a.id && t === b.id) || (s === b.id && t === a.id);
  return {
    companies: [a.id, b.id],
    ai_edges: ix.g.edges.filter((e) => pair(e.source, e.target)).map((e) => ({
      supplier: e.source, customer: e.target, relationship: e.relationship, chain: e.chain,
      deals: (e.contracts || []).map((c) => entry(c)).sort(newestFirst),
    })),
    other_relationships: (ix.other.get(a.id) || []).filter((e) => pair(e.source, e.target)),
  };
}

export function supplyChain(company: string, direction = "both", depth = 1) {
  const { id, candidates } = findCompany(company);
  if (!id) return notFound(company, candidates);
  const ix = graph();
  const steps = Math.max(1, Math.min(Math.floor(depth) || 1, 2));
  const walk = (key: "in" | "out", side: "source" | "target") => {
    const links: Record<string, unknown>[] = [];
    const seen = new Set([id]);
    let frontier = [id];
    for (let step = 1; step <= steps; step++) {
      const next: string[] = [];
      for (const c of frontier)
        for (const e of ix[key].get(c) || []) {
          links.push({ step, supplier: e.source, customer: e.target, relationship: e.relationship,
            chain: e.chain, deals: (e.contracts || []).length });
          if (!seen.has(e[side])) {
            seen.add(e[side]);
            next.push(e[side]);
          }
        }
      frontier = next;
    }
    return links.slice(0, 200);
  };
  const out: Record<string, unknown> = { company: id };
  if (direction === "up" || direction === "both") out.upstream = walk("in", "source");
  if (direction === "down" || direction === "both") out.downstream = walk("out", "target");
  return out;
}

export function chainOverview(chain = "") {
  const ix = graph();
  if (!chain) {
    const counts = new Map<string, [number, number]>();
    for (const n of ix.nodes.values())
      for (const c of n.chains) (counts.get(c) || counts.set(c, [0, 0]).get(c)!)[0] += 1;
    for (const e of ix.g.edges) if (e.chain) (counts.get(e.chain) || counts.set(e.chain, [0, 0]).get(e.chain)!)[1] += 1;
    return { chains: [...counts].sort().map(([c, [companies, edges]]) => ({ chain: c, companies, edges })) };
  }
  const players: Record<string, string | null>[] = [];
  for (const [id, n] of ix.nodes)
    for (const p of n.products)
      if (p.chain === chain)
        players.push({ company: id, layer: p.layer || p.domain || null, sector: p.sector ?? null,
          sub_sector: p.sub_sector ?? null, product: p.product });
  if (!players.length) return { error: `no chain named '${chain}' (call chain_overview with no argument for the list)` };
  players.sort((x, y) => `${x.layer}|${x.sector}|${x.company}`.localeCompare(`${y.layer}|${y.sector}|${y.company}`));
  const edges = ix.g.edges.filter((e) => e.chain === chain).map((e) => ({
    supplier: e.source, customer: e.target, relationship: e.relationship, deals: (e.contracts || []).length,
  }));
  return { chain, companies: players, edges };
}

interface EvidenceRecord {
  doc: string | null;
  excerpt: string | null;
  status: string;
}

export function sourceExcerpt(company: string, sourceLabel: string, contains = "") {
  const { id, candidates } = findCompany(company);
  if (!id) return notFound(company, candidates);
  const ix = graph();
  const ev = load<{ entries: Record<string, EvidenceRecord> }>("evidence.json").entries;
  const words = wordsOf(contains);
  const pool: [string, string, string, QuarterlyData | Contract][] = ix.nodes.get(id)!.quarterly_data.map(
    (q) => ["qd", id, "", q] as [string, string, string, QuarterlyData]);
  for (const e of [...(ix.out.get(id) || []), ...(ix.in.get(id) || [])])
    for (const c of e.contracts || []) pool.push(["contract", e.source, e.target, c]);
  const found = [];
  for (const [kind, src, tgt, q] of pool) {
    const raw = q as unknown as Record<string, string | undefined>;
    const label = raw.quarter || raw.source || "";
    const signal = raw.signal || "";
    if (label !== sourceLabel || !words.every((w) => signal.toLowerCase().includes(w))) continue;
    // the same key evidence.py writes: sha1("kind|company|target|label|signal")[:16]
    const key = crypto.createHash("sha1").update([kind, src, tgt, label, signal].join("|"), "utf8").digest("hex").slice(0, 16);
    const rec = ev[key];
    found.push({ signal, document: rec?.doc ?? null, status: rec?.status ?? null, excerpt: rec?.excerpt ?? null });
  }
  if (!found.length) return { error: `no entry of ${id} under '${sourceLabel}'${contains ? ` containing '${contains}'` : ""}` };
  return { company: id, source: sourceLabel, entries: found.slice(0, 10) };
}

export function mapStatus() {
  const { g } = graph();
  let facts = 0;
  let newest = "";
  for (const n of g.nodes)
    for (const q of n.quarterly_data) {
      facts += 1;
      const d = labelDate(q.quarter);
      if (d > newest) newest = d;
    }
  const deals = g.edges.reduce((sum, e) => sum + (e.contracts || []).length, 0);
  // The build date written into evidence.json by graph_build.py ({"generated":"YYYY-MM-DD", ...}). File times are no
  // use here: Vercel gives every deployed file the same fixed old timestamp. Only the first bytes are read.
  const head = Buffer.alloc(64);
  const fd = fs.openSync(path.join(DATA, "evidence.json"), "r");
  fs.readSync(fd, head, 0, 64, 0);
  fs.closeSync(fd);
  const built = /"generated"\s*:\s*"([\d-]+)"/.exec(head.toString("utf8"))?.[1] ?? "";
  return {
    companies: g.nodes.length, ai_edges: g.edges.length, other_relationships: (g.other_edges || []).length,
    company_facts: facts, edge_deals: deals, newest_source_date: newest, graph_built: built,
  };
}
