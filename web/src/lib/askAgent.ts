// askAgent.ts — SERVER-ONLY: the "look deeper" half of Ask (since 2026-10-12).
//
// /api/ask hands Claude, in ONE request:
//   1. the snippets the browser already picked (lib/retrieval.ts);
//   2. a COMPANY MAP: one line per company in the graph (who it is, what it
//      makes, its customers and suppliers, how much data it has) — ~60k tokens,
//      identical for every question, so the API caches it. It is a table of
//      contents for finding the way, not the facts themselves;
//   3. graph lookups: company_network (a company two hops out — customers,
//      suppliers, competitors and their partners), open_company, search_facts;
//   4. web search + web fetch (Anthropic's server tools) for whatever the graph lacks.
// Claude decides by itself how far to look — the prompt (askPrompt.mjs
// LOOKUP_RULES) describes what each tool is good for and leaves the judgment to
// the model, question by question (owner, 2026-10-12: no rigid playbook).
// Every graph fact a lookup returns gets
// a number that continues the snippet list, so the answer cites it as [n] like
// any snippet, and the route streams the new facts to the browser so the [n]
// chips can show them.
//
// The whole graph (~2.7M tokens of facts) is far too big to hand Claude at
// once (the context window is 1M) — hence map first, then targeted lookups.

import fs from "node:fs";
import path from "node:path";
import type {
  BetaContentBlock,
  BetaTool,
  BetaToolUnion,
  BetaTextBlockParam,
} from "@anthropic-ai/sdk/resources/beta/messages/messages";
import { buildViz, type VizData } from "./data";
import { allFacts, retrieve, tokenize, type Snippet } from "./retrieval";
import type { MergedGraph } from "./types";

// ── The graph, loaded once per warm server instance ────────────────────────
// The same file the browser fetches. next.config.mjs ships it with the
// /api/ask function (outputFileTracingIncludes), so it can be read from disk.

const GRAPH_FILE = path.join(process.cwd(), "public", "data", "merged_graph.json");

let viz: VizData | null = null;

function graph(): VizData {
  if (!viz) {
    const g = JSON.parse(fs.readFileSync(GRAPH_FILE, "utf8")) as MergedGraph;
    viz = buildViz(g, {}, new Set()); // no logos / report keys needed here
  }
  return viz;
}

// Every fact once, plus an index: company → its facts (its own signals and the
// deals where it is supplier or customer). Built once per instance.
let facts: { all: Snippet[]; byCompany: Map<string, Snippet[]> } | null = null;

function factIndex() {
  if (!facts) {
    const { nodes, links } = graph();
    const all = allFacts(nodes, links);
    const byCompany = new Map<string, Snippet[]>();
    const add = (id: string, s: Snippet) => {
      const list = byCompany.get(id);
      if (list) list.push(s);
      else byCompany.set(id, [s]);
    };
    for (const s of all) {
      add(s.company, s);
      if (s.target && s.target !== s.company) add(s.target, s);
    }
    facts = { all, byCompany };
  }
  return facts;
}

const factsOf = (id: string): Snippet[] => factIndex().byCompany.get(id) || [];

// ── The company map ────────────────────────────────────────────────────────

const MAP_HEADER = `COMPANY MAP — every company in the graph, one line each:
name (ticker) | layers | products | customers: edges out | suppliers: edges in | stored facts | newest source date
Use it to find your way (which companies exist, who supplies whom, who has data). It is NOT citable:
open_company or search_facts return the numbered facts you cite.`;

const MAP_PRODUCTS = 3; // products shown per company
const MAP_PARTNERS = 6; // customers / suppliers shown per company

/** "A, B, C +4 more" */
function listSome(names: string[], max: number): string {
  const unique = [...new Set(names)];
  const shown = unique.slice(0, max).join(", ");
  return unique.length > max ? `${shown} +${unique.length - max} more` : shown || "—";
}

let mapBlock: BetaTextBlockParam | null = null;

/**
 * The map as a system-prompt block, cached by the API for an hour. Built once
 * per instance and byte-identical every time (no dates, fixed order), which is
 * what lets the cache hit.
 */
export function companyMapBlock(): BetaTextBlockParam {
  if (mapBlock) return mapBlock;
  const nodes = [...graph().nodes].sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
  const lines = nodes.map((n) => {
    const products = [...new Set((n.products || []).map((p) => p.product))]
      .slice(0, MAP_PRODUCTS)
      .map((p) => (p.length > 60 ? p.slice(0, 57) + "…" : p))
      .join("; ");
    const deals =
      n.outgoing.reduce((sum, e) => sum + (e.contracts?.length || 0), 0) +
      n.incoming.reduce((sum, e) => sum + (e.contracts?.length || 0), 0);
    return [
      n.ticker ? `${n.id} (${n.ticker})` : n.id,
      [...(n.layers || []), ...(n.domains || [])].join("/") || "—",
      products || "—",
      `customers: ${listSome(n.outgoing.map((e) => e.target), MAP_PARTNERS)}`,
      `suppliers: ${listSome(n.incoming.map((e) => e.source), MAP_PARTNERS)}`,
      `${(n.quarterly_data || []).length} signals, ${deals} deals`,
      n.lastData || "no dated source",
    ].join(" | ");
  });
  mapBlock = {
    type: "text",
    text: `${MAP_HEADER}\n\n${lines.join("\n")}`,
    cache_control: { type: "ephemeral", ttl: "1h" },
  };
  return mapBlock;
}

// ── The tools ──────────────────────────────────────────────────────────────

export const ASK_TOOLS: BetaTool[] = [
  {
    name: "company_network",
    description:
      "Trace one company's network two hops out: what the company itself said, every other company's fact that names it, what its customers and suppliers (hop 1) and its competitors (same slot in the graph) said that bears on it — its products, shortages, contracts, pricing, demand, capacity — and the most relevant facts from its partners' partners (hop 2). Each fact is labelled with who said it and how they connect. Useful when a company's situation depends on the companies around it.",
    input_schema: {
      type: "object",
      properties: {
        company: { type: "string", description: "The company name exactly as the map writes it, e.g. \"Lumentum\"." },
        focus: {
          type: "string",
          description: "Optional English keywords from the question, e.g. \"EML laser shortage 2027\".",
        },
      },
      required: ["company"],
    },
    eager_input_streaming: true,
  },
  {
    name: "open_company",
    description:
      "Open one company of the map: ALL its stored facts — its own signals (what it said on calls / in filings) and the deals where it is supplier or customer — newest first, or the facts matching `focus` first. Use it when the question is about a company the snippets cover thinly or not at all, or to get the deal behind a customer/supplier link in the map.",
    input_schema: {
      type: "object",
      properties: {
        company: { type: "string", description: "The company name exactly as the map writes it, e.g. \"SK Hynix\"." },
        focus: {
          type: "string",
          description: "Optional English keywords to rank its facts by, e.g. \"HBM4 allocation NVIDIA\".",
        },
      },
      required: ["company"],
    },
    eager_input_streaming: true,
  },
  {
    name: "search_facts",
    description:
      "Keyword search over every company's stored facts (the same search that picked the snippets), best 25. Use the graph's English vocabulary (capex guidance, HBM allocation, backlog, sold out, GW commitments …). Use it for rankings and comparisons across many companies.",
    input_schema: {
      type: "object",
      properties: { query: { type: "string", description: "English search words." } },
      required: ["query"],
    },
    eager_input_streaming: true,
  },
];

// ── Web search + web fetch (Anthropic's server-side tools) ─────────────────
// Run on Anthropic's side inside the same API call: Claude searches, reads
// the results (or a whole page) and keeps writing. The graph holds what
// companies said in their own documents; the web adds what the graph lacks —
// newer news, figures the company never put in a filing (a growth rate, a
// market share), reports and estimates. Search is billed per search ($10 per
// 1,000) plus the result tokens; fetch costs only the page tokens.

const WEB_SEARCH_MAX_USES = 5; // searches per API call
const WEB_FETCH_MAX_USES = 3; // full pages read per API call …
const WEB_FETCH_MAX_TOKENS = 20_000; // … each cut at this many tokens

/** web_search finds pages; web_fetch reads one of them in full when the search snippet is not enough. */
export const WEB_TOOLS: BetaToolUnion[] = [
  { type: "web_search_20260209", name: "web_search", max_uses: WEB_SEARCH_MAX_USES },
  { type: "web_fetch_20260209", name: "web_fetch", max_uses: WEB_FETCH_MAX_USES, max_content_tokens: WEB_FETCH_MAX_TOKENS },
];

export interface WebSource {
  url: string;
  title: string;
}

/** A finished web_search / web_fetch call block as a progress step (the query or the page), else null. */
export function webStepOf(block: BetaContentBlock): { tool: "web_search" | "web_fetch"; target: string } | null {
  if (block.type !== "server_tool_use" || (block.name !== "web_search" && block.name !== "web_fetch")) return null;
  const input = block.input as { query?: unknown; url?: unknown } | null;
  const target = block.name === "web_search" ? input?.query : input?.url;
  return typeof target === "string" ? { tool: block.name, target } : null;
}

/**
 * The web pages a finished block shows Claude used: a text block's citations,
 * or the pages a web search returned (with dynamic filtering the answer text
 * often carries no citation blocks, so the search results are the record of
 * what Claude saw). Anything else → [].
 */
export function webSourcesOf(block: BetaContentBlock): WebSource[] {
  const out: WebSource[] = [];
  if (block.type === "text" && block.citations) {
    for (const c of block.citations)
      if (c.type === "web_search_result_location") out.push({ url: c.url, title: c.title || c.url });
  } else if (block.type === "web_search_tool_result" && Array.isArray(block.content)) {
    for (const r of block.content) out.push({ url: r.url, title: r.title || r.url });
  }
  return out;
}

// Sizes raised 2026-10-12 (owner: answer quality first; the 1M context has room).
const OPEN_MAX_FACTS = 80; // open_company returns at most this many facts …
const OPEN_MAX_CHARS = 40_000; // … or this many characters of fact text
const SEARCH_K = 40; // search_facts: at most this many facts (and retrieval.ts's 30,000-character cap)
const MAX_INPUT_CHARS = 200; // longer tool arguments are rejected

// ── Numbering: lookups continue the snippet list ───────────────────────────

const factKey = (s: Snippet) => `${s.kind}|${s.company}|${s.target ?? ""}|${s.label}|${s.text}`;

/** Numbers every fact Claude has seen in this request: the snippets are 1…n, lookups go on from there. */
export class FactBook {
  private numbers = new Map<string, number>();
  count = 0;

  constructor(snippets: Snippet[]) {
    for (const s of snippets) this.numbers.set(factKey(s), ++this.count);
  }

  /** The fact's number — a fact seen before keeps its old one. */
  number(s: Snippet): { n: number; isNew: boolean } {
    const k = factKey(s);
    const known = this.numbers.get(k);
    if (known) return { n: known, isNew: false };
    this.numbers.set(k, ++this.count);
    return { n: this.count, isNew: true };
  }
}

/** What one lookup produced: the text Claude reads, and what the browser is told. */
export interface LookupResult {
  content: string;
  isError: boolean;
  /** For the progress line in the browser ("opened SK Hynix", "searched …"). */
  step: { tool: string; target: string; facts: number };
  /** Facts that got a NEW number — the browser appends them to its snippet list. */
  newFacts: Snippet[];
}

/** One fact as Claude reads it: "[52] contract | SK Hynix → NVIDIA | label | text". */
function factLine(n: number, s: Snippet): string {
  const who = s.kind === "contract" && s.target ? `${s.company} → ${s.target}` : s.company;
  return `[${n}] ${s.kind} | ${who} | ${s.label} | ${s.text}`;
}

/** Number the facts, collect the new ones, and lay them out one per line. */
function present(facts: Snippet[], book: FactBook): { lines: string[]; newFacts: Snippet[] } {
  const lines: string[] = [];
  const newFacts: Snippet[] = [];
  for (const s of facts) {
    const { n, isNew } = book.number(s);
    if (isNew) newFacts.push(s);
    lines.push(factLine(n, s));
  }
  return { lines, newFacts };
}

function stringArg(input: unknown, key: string): string | null {
  const v = (input as Record<string, unknown> | null)?.[key];
  return typeof v === "string" && v.trim() && v.length <= MAX_INPUT_CHARS ? v.trim() : null;
}

function errorResult(tool: string, target: string, message: string): LookupResult {
  return { content: message, isError: true, step: { tool, target, facts: 0 }, newFacts: [] };
}

/** Map a name Claude typed to a node id: exact, then case-insensitive, then the closest containing match. */
function resolveCompany(name: string): string | null {
  const ids = graph().nodes.map((n) => n.id);
  if (ids.includes(name)) return name;
  const lower = name.toLowerCase();
  const same = ids.find((id) => id.toLowerCase() === lower);
  if (same) return same;
  const near = ids
    .filter((id) => id.toLowerCase().includes(lower) || lower.includes(id.toLowerCase()))
    .sort((a, b) => Math.abs(a.length - name.length) - Math.abs(b.length - name.length));
  return near[0] || null;
}

function openCompany(input: unknown, book: FactBook): LookupResult {
  const asked = stringArg(input, "company");
  if (!asked) return errorResult("open_company", "?", "open_company needs `company`: a name from the map.");
  const id = resolveCompany(asked);
  if (!id)
    return errorResult("open_company", asked, `No company named "${asked}" in the map. Use a name exactly as the map writes it.`);
  const focus = stringArg(input, "focus");

  const all = factsOf(id);
  // Rank: facts containing more of the focus words first, then newest first.
  const focusWords = new Set(focus ? tokenize(focus) : []);
  const hits = (s: Snippet) => {
    if (!focusWords.size) return 0;
    const words = new Set(tokenize(`${s.text} ${s.label} ${s.target ?? ""} ${(s.topics || []).join(" ")}`));
    let n = 0;
    for (const w of focusWords) if (words.has(w)) n++;
    return n;
  };
  const ranked = all
    .map((s) => ({ s, h: hits(s) }))
    .sort((a, b) => b.h - a.h || (a.s.date < b.s.date ? 1 : a.s.date > b.s.date ? -1 : 0))
    .map((x) => x.s);

  const shown: Snippet[] = [];
  let chars = 0;
  for (const s of ranked) {
    if (shown.length >= OPEN_MAX_FACTS || chars + s.text.length > OPEN_MAX_CHARS) break;
    shown.push(s);
    chars += s.text.length;
  }
  const { lines, newFacts } = present(shown, book);
  const head = `open_company "${id}"${focus ? ` (focus: ${focus})` : ""} — ${shown.length} of ${all.length} facts, ${
    focus ? "focus matches first" : "newest first"
  }:`;
  const tail =
    all.length > shown.length ? `\n… ${all.length - shown.length} more not shown — call again with a narrower focus.` : "";
  return {
    content: all.length ? `${head}\n${lines.join("\n")}${tail}` : `"${id}" has no stored facts yet.`,
    isError: false,
    step: { tool: "open_company", target: id, facts: shown.length },
    newFacts,
  };
}

function searchFacts(input: unknown, book: FactBook): LookupResult {
  const query = stringArg(input, "query");
  if (!query) return errorResult("search_facts", "?", "search_facts needs `query`: English search words.");
  const { nodes, links } = graph();
  const found = retrieve(query, nodes, links, SEARCH_K);
  const { lines, newFacts } = present(found, book);
  return {
    content: found.length ? `search_facts "${query}" — ${found.length} facts:\n${lines.join("\n")}` : `Nothing matched "${query}".`,
    isError: false,
    step: { tool: "search_facts", target: query, facts: found.length },
    newFacts,
  };
}

// ── company_network: two hops around one company ───────────────────────────
// "Ask about Lumentum" should also bring what Google (customer), AXT
// (supplier) or Coherent (competitor) said about lasers, shortages and
// contracts — and what THEIR partners said. Hop 2 alone holds thousands of
// facts, so every neighbour's facts are scored for relevance to the asked
// company and only the best are kept:
//   names the company                         +3
//   names the hop-1 company in between        +1   (hop 2 only)
//   each of the company's product words      +1   (at most 2)
//   a supply word (shortage, contract, price…) +1
//   a focus word from the question            +1   (at most 2)
// Hop 1 and competitors keep facts scoring ≥ 2, hop 2 (stricter) ≥ 3.

const SUPPLY_RE =
  /\b(shortages?|short supply|tight\w*|sold out|allocat\w*|constrain\w*|bottlenecks?|lead times?|capacity|LTAs?|long-term agreements?|prepay\w*|contracts?|agreements?|prices?|pricing|backlog|demand|ramp\w*|qualif\w*|supply)\b/i;

// Words too common to tell one product from another.
const PRODUCT_STOP = new Set([
  "and", "for", "the", "with", "from", "into", "plus", "based", "high", "products", "product",
  "solutions", "systems", "components", "parts", "services", "equipment", "materials", "chips",
  "chip", "units", "supply", "used", "other", "global", "market", "custom", "advanced",
]);

const NET_OWN = 50; // the company's own facts (newest / focus first)
const NET_NAMED = 40; // other companies' facts naming it
const NET_HOP1 = 60; // hop-1 facts in total …
const NET_HOP1_EACH = 6; // … at most this many per neighbour
const NET_PEER_COMPANIES = 12; // the closest competitors considered …
const NET_PEERS = 40; // … their facts in total …
const NET_PEERS_EACH = 3; // … at most this many per competitor
const NET_HOP2 = 40;
const NET_HOP2_EACH = 3;

const escapeRe = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/** "Resonac (Showa Denko)" → /\b(resonac|showa denko)\b/i */
function nameRe(id: string): RegExp {
  const parts = [id.replace(/\s*\([^)]*\)/g, "").trim()];
  const paren = /\(([^)]+)\)/.exec(id);
  if (paren) parts.push(paren[1]);
  return new RegExp(`\\b(${parts.filter(Boolean).map(escapeRe).join("|")})\\b`, "i");
}

function companyNetwork(input: unknown, book: FactBook): LookupResult {
  const asked = stringArg(input, "company");
  if (!asked) return errorResult("company_network", "?", "company_network needs `company`: a name from the map.");
  const id = resolveCompany(asked);
  if (!id)
    return errorResult("company_network", asked, `No company named "${asked}" in the map. Use a name exactly as the map writes it.`);
  const focus = stringArg(input, "focus");
  const { byId } = graph();
  const node = byId.get(id)!;

  // Hop 1 with each neighbour's role; hop 2 with the hop-1 company it comes through.
  const role = new Map<string, string>();
  for (const e of node.outgoing) role.set(e.target, "customer");
  for (const e of node.incoming) role.set(e.source, role.has(e.source) ? "customer & supplier" : "supplier");
  role.delete(id);
  const via = new Map<string, { through: string; how: string }>();
  for (const [n1, r1] of role) {
    const nb = byId.get(n1);
    if (!nb) continue;
    const add = (n2: string, how: string) => {
      if (n2 !== id && !role.has(n2) && !via.has(n2)) via.set(n2, { through: n1, how });
    };
    for (const e of nb.outgoing) add(e.target, `customer of ${n1} (${r1})`);
    for (const e of nb.incoming) add(e.source, `supplier of ${n1} (${r1})`);
  }

  // Relevance words: the company's name, its product words, the question's focus words.
  const target = nameRe(id);
  const productWords = new Set(
    tokenize((node.products || []).map((p) => p.product).join(" ") + " " + (node.sectors || []).join(" ")).filter(
      (w) => w.length >= 3 && !PRODUCT_STOP.has(w) && !/^\d+$/.test(w)
    )
  );
  const focusWords = new Set(focus ? tokenize(focus).filter((w) => w.length >= 3) : []);
  const throughRe = new Map<string, RegExp>();
  const score = (s: Snippet, through?: string) => {
    const text = `${s.text} ${s.target ?? ""}`;
    const words = new Set(tokenize(text));
    let pts = 0;
    if (target.test(text) || s.company === id || s.target === id) pts += 3;
    if (through) {
      let re = throughRe.get(through);
      if (!re) throughRe.set(through, (re = nameRe(through)));
      if (re.test(text) || s.target === through || s.company === through) pts += 1;
    }
    let hits = 0;
    for (const w of productWords) if (words.has(w) && ++hits === 2) break;
    pts += hits;
    if (SUPPLY_RE.test(text)) pts += 1;
    let f = 0;
    for (const w of focusWords) if (words.has(w) && ++f === 2) break;
    return pts + f;
  };
  const newestFirst = (a: Snippet, b: Snippet) => (a.date < b.date ? 1 : a.date > b.date ? -1 : 0);

  const seen = new Set<string>(); // a fact appears once, in the first section that has it
  const sections: { title: string; lines: string[] }[] = [];
  const newFacts: Snippet[] = [];
  let total = 0;
  const emit = (title: string, items: { s: Snippet; tag?: string }[]) => {
    const lines: string[] = [];
    for (const { s, tag } of items) {
      const { n, isNew } = book.number(s);
      if (isNew) newFacts.push(s);
      lines.push(tag ? `${factLine(n, s)}   ← ${tag}` : factLine(n, s));
    }
    total += lines.length;
    sections.push({ title, lines });
  };
  const fresh = (s: Snippet) => {
    const k = factKey(s);
    if (seen.has(k)) return false;
    seen.add(k);
    return true;
  };
  /** The first `max` items not shown in an earlier section (only those get marked as shown). */
  const takeFresh = <T extends { s: Snippet }>(items: T[], max: number): T[] => {
    const out: T[] = [];
    for (const it of items) {
      if (out.length >= max) break;
      if (fresh(it.s)) out.push(it);
    }
    return out;
  };

  // 1) The company's own facts (and the deals on its edges).
  const own = factsOf(id);
  const ownPicked = takeFresh(
    own.map((s) => ({ s, f: score(s) })).sort((a, b) => b.f - a.f || newestFirst(a.s, b.s)),
    NET_OWN
  );
  emit(`${id} itself — ${ownPicked.length} of ${own.length} facts`, ownPicked);

  // 2) Every other company's facts that name it (signals and deals between others).
  const linkOf = (who: string) =>
    role.has(who) ? `${who} (${role.get(who)})` : via.has(who) ? `${who} (2 hops away)` : `${who} (not directly linked)`;
  const named = factIndex()
    .all.filter((s) => s.company !== id && s.target !== id && target.test(s.text))
    .sort(newestFirst)
    .map((s) => ({ s, tag: linkOf(s.company) }));
  const namedPicked = takeFresh(named, NET_NAMED);
  emit(`Other companies naming ${id} — ${namedPicked.length} of ${named.length}, newest first`, namedPicked);

  // 3) Hop 1: customers and suppliers.
  const hop1: { s: Snippet; f: number; tag: string; who: string }[] = [];
  for (const [n1, r1] of role)
    for (const s of factsOf(n1)) {
      const f = score(s);
      if (f >= 2) hop1.push({ s, f, tag: `${n1} (${r1})`, who: n1 });
    }
  const hop1Picked = pickRanked(hop1, NET_HOP1_EACH, NET_HOP1, fresh);
  emit(
    `Hop 1 — customers: ${listSome([...role].filter(([, r]) => r !== "supplier").map(([n]) => n), 8)}; suppliers: ${listSome(
      [...role].filter(([, r]) => r === "supplier").map(([n]) => n),
      8
    )} — ${hop1Picked.length} relevant facts`,
    hop1Picked
  );

  // 4) Competitors: companies that fill the same slot (chain + sector +
  //    sub-sector) as the asked company AND make something with the same product
  //    words (laser, EML, HBM …). A shared sector alone is too wide (TSMC sits
  //    in an optics sector too), so they are ranked by shared slots ×2 + shared
  //    product words and only the top NET_PEER_COMPANIES count. Scored like hop 1.
  const slotKey = (p: { chain: string; sector?: string | null; sub_sector?: string | null }) =>
    `${p.chain}|${p.sector ?? ""}|${p.sub_sector ?? ""}`;
  const slots = new Map<string, string>(); // slot key → sector name, for the tag
  for (const p of node.products || []) slots.set(slotKey(p), p.sub_sector || p.sector || p.chain);
  const ranked: { id: string; sector: string; rank: number }[] = [];
  for (const nb of graph().nodes) {
    if (nb.id === id) continue;
    const sharedSlots = new Set((nb.products || []).map(slotKey).filter((k) => slots.has(k)));
    if (!sharedSlots.size) continue;
    const words = new Set(tokenize((nb.products || []).map((p) => p.product).join(" ")));
    let overlap = 0;
    for (const w of productWords) if (words.has(w)) overlap++;
    if (!overlap) continue;
    ranked.push({ id: nb.id, sector: slots.get([...sharedSlots][0])!, rank: sharedSlots.size * 2 + overlap });
  }
  ranked.sort((a, b) => b.rank - a.rank);
  const peers = new Map(ranked.slice(0, NET_PEER_COMPANIES).map((r) => [r.id, r.sector])); // competitor → shared sector
  const peerFacts: { s: Snippet; f: number; tag: string; who: string }[] = [];
  for (const [p, sector] of peers)
    for (const s of factsOf(p)) {
      const f = score(s);
      if (f >= 2) peerFacts.push({ s, f, tag: `${p} (competitor: ${sector}${role.has(p) ? `; also a ${role.get(p)}` : ""})`, who: p });
    }
  const peersPicked = pickRanked(peerFacts, NET_PEERS_EACH, NET_PEERS, fresh);
  emit(`Competitors — same slot as ${id}: ${listSome([...peers.keys()], 12)} — ${peersPicked.length} relevant facts`, peersPicked);

  // 5) Hop 2: their partners — stricter.
  const hop2: { s: Snippet; f: number; tag: string; who: string }[] = [];
  for (const [n2, v] of via)
    for (const s of factsOf(n2)) {
      const f = score(s, v.through);
      if (f >= 3) hop2.push({ s, f, tag: `${n2}: ${v.how}`, who: n2 });
    }
  const hop2Picked = pickRanked(hop2, NET_HOP2_EACH, NET_HOP2, fresh);
  emit(`Hop 2 — ${via.size} companies; ${hop2Picked.length} most relevant facts`, hop2Picked);

  const content =
    `company_network "${id}"${focus ? ` (focus: ${focus})` : ""} — ${role.size} hop-1, ${peers.size} competitor and ${via.size} hop-2 companies. ` +
    `"←" says who the fact comes from and how it connects to ${id}.\n\n` +
    sections.map((sec) => `## ${sec.title}\n${sec.lines.join("\n") || "(none)"}`).join("\n\n");
  return { content, isError: false, step: { tool: "company_network", target: id, facts: total }, newFacts };
}

/**
 * Best-scored first (then newest), at most `each` per company and `max` in
 * total, skipping facts already shown. Two passes: first every company's single
 * best fact (so a customer like Google is never crowded out by the many deals on
 * the asked company's own edges), then the rest by score.
 */
function pickRanked(
  items: { s: Snippet; f: number; tag: string; who: string }[],
  each: number,
  max: number,
  fresh: (s: Snippet) => boolean
): { s: Snippet; tag: string }[] {
  items.sort((a, b) => b.f - a.f || (a.s.date < b.s.date ? 1 : a.s.date > b.s.date ? -1 : 0));
  const per = new Map<string, number>();
  const taken = new Set<(typeof items)[number]>();
  const out: { s: Snippet; tag: string }[] = [];
  for (const limit of [1, each])
    for (const it of items) {
      if (out.length >= max) break;
      if (taken.has(it) || (per.get(it.who) || 0) >= limit || !fresh(it.s)) continue;
      taken.add(it);
      per.set(it.who, (per.get(it.who) || 0) + 1);
      out.push({ s: it.s, tag: it.tag });
    }
  return out;
}

/** Run one tool call. Never throws: a bad call comes back as an error result Claude can read. */
export function runLookup(name: string, input: unknown, book: FactBook): LookupResult {
  if (name === "company_network") return companyNetwork(input, book);
  if (name === "open_company") return openCompany(input, book);
  if (name === "search_facts") return searchFacts(input, book);
  return errorResult(name, "?", `Unknown tool "${name}".`);
}
