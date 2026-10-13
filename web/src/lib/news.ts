// news.ts — the server side of the /news terminal: the last 24 hours of headlines
// from Polygon, Finnhub and Google News, each tagged with the map companies it names.
//
// DISPLAY ONLY. Nothing here writes to disk, and nothing in the graph / enrich
// pipeline reads it — news is shown on the site and never becomes graph data.
//
// Server-only: it reads API keys from process.env and the graph from disk
// (shipped with the /api/news* functions via outputFileTracingIncludes).

import fs from "node:fs";
import path from "node:path";
import { createHash } from "node:crypto";
import { toEnglish } from "./gemini";
import type { GraphNode, MergedGraph } from "./types";

// News feeds, FT's own RSS (lib/top.ts → /api/top), then the filing registries
// (lib/filings.ts → /api/filings).
export type NewsFeedName = "polygon" | "finnhub" | "google" | "ft" | "dart" | "edinet" | "sec";

export interface NewsItem {
  id: string;
  time: number; // epoch ms
  day?: string; // set when the source gives a date, not a time (DART, SEC): "2026-10-13" in its market
  title: string; // always English: non-English headlines are translated (lib/gemini.ts)
  original?: string; // the headline as published, when `title` is its translation
  source: string; // publisher
  url: string; // Google News items carry a news.google.com link (resolved on click)
  summary: string; // the feed's own blurb ("" when it has none)
  companies: string[]; // map node ids the headline / blurb / tickers point to
  tickers: string[]; // tickers the feed tagged that are NOT map companies
  feed: NewsFeedName;
  rank?: number; // Top News only: Gemini's 1-5 importance (5 = market-moving)
  category?: string; // Top News only: Politics, Economy, Markets, Companies, Tech, Energy, Other
}

export interface NewsFeed {
  at: number;
  items: NewsItem[];
  tickers: Record<string, string | null>; // map company id → its ticker (for the chips)
  feeds: { name: NewsFeedName; count: number; failed: number; label?: string }[]; // label overrides the feed's name
}

const DAY_MS = 24 * 3600_000;
const UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36";

// ── The map: who can a headline be about? ─────────────────────────────────

// Common short forms the node ids don't cover.
const EN_ALIASES: Record<string, string[]> = {
  Google: ["Alphabet"],
  "Arm Holdings": ["Arm"],
  Supermicro: ["Super Micro"],
  Foxconn: ["Hon Hai"],
  Amazon: ["AWS"],
};
// Names that are everyday words or stray initials in headlines ("Cursor", "VM",
// 미래산업 = "future industry", 大量 = "a large amount"…): tagged by ticker only.
const NAME_SKIP = new Set([
  "Flex", "Nova", "Zeus", "Yest", "Cursor", "Lambda", "Landmark", "Reflection", "Diodes",
  "Dover", "Vertex", "Cadence", "Etched", "Acuity",
  "GMI", "TLB", "TES", "DIT", "YC", "JT", "PMT", "STI", "DNF", "VM", "BHI", "ISC", "FST", "MEC",
  "미래산업", "제우스", "프로텍", "우리로",
  "大量", "全新", "创意", "光环", "长兴", "环宇", "华城", "南亚", "尖点", "顺达", "爱普",
]);
// "Amkor Technology" is "Amkor" in most headlines.
const SUFFIX = /\s+(Inc\.?|Corporation|Corp\.?|Co\.,? Ltd\.?|Ltd\.?|Holdings|Group|Technology|Technologies|Industries|Chemical)$/;
const CJK = /[぀-ヿ㐀-鿿가-힯]/;
const HANGUL = /[가-힯]/;

interface MapIndex {
  nodes: GraphNode[];
  exact: RegExp | null; // case-sensitive Latin names ("Oracle", "AMD")
  loose: RegExp[]; // case-insensitive: Latin ("SK hynix", "Nvidia"), Korean, Japanese / Chinese
  byExact: Map<string, string>; // matched text → node id
  byLower: Map<string, string>; // lowercased matched text → node id
  byTicker: Map<string, string>; // "NVDA" → "NVIDIA"
  tickerOf: Record<string, string | null>;
  queries: string[]; // Google News searches built from the map
}

const esc = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

// Latin names need word edges (a Korean particle may follow: "TSMC가"); Korean
// names only a left edge ("SK하이닉스가"); Japanese / Chinese names none.
const EDGES = {
  latin: ["(?<![\\p{Script=Latin}\\p{N}])", "(?![\\p{Script=Latin}\\p{N}])"],
  hangul: ["(?<![\\p{Script=Hangul}])", ""],
  cjk: ["", ""],
} as const;

function alternation(names: string[], edges: keyof typeof EDGES, flags: string): RegExp | null {
  if (!names.length) return null;
  const body = [...new Set(names)].sort((a, b) => b.length - a.length).map(esc).join("|");
  const [left, right] = EDGES[edges];
  return new RegExp(`${left}(?:${body})${right}`, flags + "gu");
}

let mapIndex: MapIndex | null = null;

// Spelled out in full (not joined from a variable) so the bundler ships just these
// three files with the function, not all of public/data.
const GRAPH_FILE = path.join(process.cwd(), "public", "data", "merged_graph.json");
const KO_FILE = path.join(process.cwd(), "public", "data", "company_ko.json");
const NAMES_FILE = path.join(process.cwd(), "public", "data", "i18n", "company_names.json");

function readData<T>(file: string, fallback: T): T {
  try {
    return JSON.parse(fs.readFileSync(file, "utf8")) as T;
  } catch {
    return fallback;
  }
}

function getMap(): MapIndex {
  if (mapIndex) return mapIndex;
  const graph = readData<MergedGraph>(GRAPH_FILE, { nodes: [], edges: [] });
  const ko = readData<Record<string, string[]>>(KO_FILE, {});
  const local = readData<Record<string, Record<string, string>>>(NAMES_FILE, {});

  const degree: Record<string, number> = {};
  for (const e of graph.edges) {
    degree[e.source] = (degree[e.source] || 0) + 1;
    degree[e.target] = (degree[e.target] || 0) + 1;
  }

  const exact: string[] = [];
  const loose = { latin: [] as string[], hangul: [] as string[], cjk: [] as string[] };
  const byExact = new Map<string, string>();
  const byLower = new Map<string, string>();
  const byTicker = new Map<string, string>();
  const tickerOf: Record<string, string | null> = {};
  const addLatin = (n: string, id: string) => {
    if (n.length < 2 || NAME_SKIP.has(n)) return;
    const caps = n === n.toUpperCase();
    // One mixed-case word ("Oracle", "Coherent") or short initials ("AMD") must match
    // as written; multi-word names and long all-caps ids ("NVIDIA") in any case.
    if ((!n.includes(" ") && !caps) || (caps && n.length <= 4)) {
      exact.push(n);
      byExact.set(n, id);
    } else {
      loose.latin.push(n);
      byLower.set(n.toLowerCase(), id);
    }
  };
  const addLocal = (n: string, id: string) => {
    const hangul = HANGUL.test(n);
    if (!CJK.test(n) || n.length < (hangul ? 3 : 2) || NAME_SKIP.has(n)) return;
    loose[hangul ? "hangul" : "cjk"].push(n);
    byLower.set(n.toLowerCase(), id);
  };

  for (const node of graph.nodes) {
    const id = node.id;
    tickerOf[id] = node.ticker;
    if (node.ticker) byTicker.set(node.ticker.toUpperCase(), id);
    const variants = [id, ...(EN_ALIASES[id] || [])];
    const paren = id.match(/^(.*?)\s*\((.*)\)$/); // "Resonac (Showa Denko)"
    if (paren) variants.push(paren[1], paren[2]);
    const base = id.replace(SUFFIX, "");
    if (base !== id && (base.length >= 4 || (base.length === 3 && base === base.toUpperCase()))) variants.push(base);
    for (const v of variants) addLatin(v.trim(), id);
    for (const n of [...(ko[id] || []), ...Object.values(local[id] || {})]) if (n) addLocal(n.trim(), id);
  }

  mapIndex = {
    nodes: graph.nodes,
    exact: alternation(exact, "latin", ""),
    loose: (["latin", "hangul", "cjk"] as const)
      .map((k) => alternation(loose[k], k, "i"))
      .filter((re): re is RegExp => re != null),
    byExact,
    byLower,
    byTicker,
    tickerOf,
    queries: buildQueries(graph, degree),
  };
  return mapIndex;
}

// "(NASDAQ: NVDA)" in press releases and "$NVDA" cashtags.
const TICKER_IN_TEXT = /\b(?:NASDAQ|Nasdaq|NYSE(?: American| Arca)?|OTCQX|OTC)\s*:\s*([A-Z][A-Z.]{0,6})|\$([A-Z]{2,5})\b/g;

/** The map companies a piece of text names, plus the given tickers split into
 *  map companies and the rest. */
export function tagCompanies(text: string, tickers: string[] = []): { companies: string[]; others: string[] } {
  const m = getMap();
  // Overlapping hits ("Samsung" inside "Samsung SDI", "Micron" inside "Hana Micron"):
  // the longest name wins.
  const spans: [number, number, string][] = [];
  const collect = (re: RegExp, lookup: (s: string) => string | undefined) => {
    for (const hit of text.matchAll(re)) {
      const id = lookup(hit[0]);
      if (id) spans.push([hit.index!, hit.index! + hit[0].length, id]);
    }
  };
  if (m.exact) collect(m.exact, (s) => m.byExact.get(s));
  for (const re of m.loose) collect(re, (s) => m.byLower.get(s.toLowerCase()));
  spans.sort((a, b) => b[1] - b[0] - (a[1] - a[0]));
  const found = new Set<string>();
  const taken: [number, number][] = [];
  for (const [s, e, id] of spans) {
    if (taken.some(([ts, te]) => s < te && e > ts)) continue;
    taken.push([s, e]);
    found.add(id);
  }
  const others = new Set<string>();
  const all = [...tickers, ...Array.from(text.matchAll(TICKER_IN_TEXT), (h) => h[1] || h[2])];
  for (const raw of all) {
    const tk = raw.trim().toUpperCase();
    if (!tk) continue;
    const id = m.byTicker.get(tk);
    if (id) found.add(id);
    else others.add(tk);
  }
  return { companies: [...found], others: [...others] };
}

export function tickerOf(id: string): string | null {
  return getMap().tickerOf[id] ?? null;
}

/** Every map company (for lib/filings.ts, which looks filings up by code). */
export function mapNodes(): GraphNode[] {
  return getMap().nodes;
}

// ── Google News searches ──────────────────────────────────────────────────

// The site is for US investors (user, 2026-10-13), so every search runs on the
// US English edition — Asian suppliers too, by their English names: their
// English-language coverage (Nikkei Asia, KED Global, DigiTimes…) is what a US
// investor reads, and it needs no translating.
const GN_LOCALE = "hl=en-US&gl=US&ceid=US:en";
// Industry-wide searches.
const TOPICS = [
  '(semiconductor OR chipmaker OR HBM OR "AI chip" OR foundry)',
  '("data center" OR hyperscaler OR "AI infrastructure")',
];
const BATCH = 20; // names per OR-search
const TOP_COMPANIES = 240; // most-connected public companies searched by name

function buildQueries(graph: MergedGraph, degree: Record<string, number>): string[] {
  const ranked = [...graph.nodes].sort((a, b) => (degree[b.id] || 0) - (degree[a.id] || 0));
  const searchName = (id: string) => {
    if (id === "KLA") return "KLA Corp"; // bare "KLA" is mostly Kosovo news
    const base = id.replace(SUFFIX, "");
    return base.length >= 4 ? base : id;
  };
  const names = ranked
    .filter((n) => n.status !== "private" && !NAME_SKIP.has(n.id))
    .slice(0, TOP_COMPANIES)
    .map((n) => searchName(n.id));
  const out = [...TOPICS];
  for (let i = 0; i < names.length; i += BATCH) out.push(names.slice(i, i + BATCH).map((n) => `"${n}"`).join(" OR "));
  return out;
}

// ── Fetching ──────────────────────────────────────────────────────────────

async function getText(url: string, ms = 10_000): Promise<string | null> {
  try {
    const res = await fetch(url, { headers: { "User-Agent": UA }, cache: "no-store", signal: AbortSignal.timeout(ms) });
    return res.ok ? await res.text() : null;
  } catch {
    return null;
  }
}

async function getJson(url: string): Promise<any> {
  const text = await getText(url);
  if (text == null) return null;
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

const ENTITIES: Record<string, string> = { amp: "&", lt: "<", gt: ">", quot: '"', apos: "'", nbsp: " " };
export function decodeEntities(s: string): string {
  return s.replace(/&(#x[0-9a-f]+|#\d+|[a-z]+);/gi, (m, e: string) => {
    if (e[0] === "#") {
      const code = e[1] === "x" || e[1] === "X" ? parseInt(e.slice(2), 16) : parseInt(e.slice(1), 10);
      return Number.isFinite(code) ? String.fromCodePoint(code) : m;
    }
    return ENTITIES[e.toLowerCase()] ?? m;
  });
}

export function makeItem(
  feed: NewsFeedName,
  url: string,
  time: number,
  title: string,
  source: string,
  summary: string,
  tickers: string[]
): NewsItem | null {
  if (!url || !title || !Number.isFinite(time)) return null;
  const clean = summary.replace(/\s+/g, " ").trim();
  const { companies, others } = tagCompanies(`${title}\n${clean}`, tickers);
  return {
    id: createHash("sha1").update(url).digest("hex").slice(0, 12),
    time,
    title: title.trim(),
    source: (source || "").trim(),
    url,
    summary: clean,
    companies,
    tickers: others,
    feed,
  };
}

async function polygon(since: number): Promise<NewsItem[] | null> {
  const key = process.env.POLYGON_API_KEY?.trim();
  if (!key) return [];
  const gte = new Date(since).toISOString().slice(0, 19) + "Z";
  const j = await getJson(
    `https://api.polygon.io/v2/reference/news?published_utc.gte=${gte}&order=desc&sort=published_utc&limit=1000&apiKey=${key}`
  );
  if (!Array.isArray(j?.results)) return null;
  return j.results
    .map((r: any) =>
      makeItem("polygon", r.article_url, Date.parse(r.published_utc), r.title || "", r.publisher?.name || "", r.description || "", r.tickers || [])
    )
    .filter((x: NewsItem | null): x is NewsItem => x != null)
    .filter((x: NewsItem) => !STOCK_PICK_MILLS.test(x.source) || x.companies.length > 0);
}

// "Is X a buy?" mills — most of Polygon's day (~500 of ~600 stories). Kept only
// when they are about a map company.
const STOCK_PICK_MILLS = /^(Zacks|The Motley Fool)/i;

export async function finnhub(): Promise<NewsItem[] | null> {
  const key = process.env.FINNHUB_API_KEY?.trim();
  if (!key) return [];
  const j = await getJson(`https://finnhub.io/api/v1/news?category=general&token=${key}`);
  if (!Array.isArray(j)) return null;
  return j
    .map((r: any) => {
      // "… - Reuters": the same story from Google News comes without it.
      const title = String(r.headline || "").replace(/\s+-\s+Reuters$/i, "");
      const related = r.related ? String(r.related).split(",") : [];
      return makeItem("finnhub", r.url, (r.datetime || 0) * 1000, title, r.source || "", r.summary || "", related);
    })
    .filter((x: NewsItem | null): x is NewsItem => x != null);
}

/** One field of an RSS <item> block, entities decoded. */
export const rssField = (xml: string, name: string) => {
  const m = xml.match(new RegExp(`<${name}[^>]*>([\\s\\S]*?)</${name}>`));
  return m ? decodeEntities(m[1].replace(/^<!\[CDATA\[|\]\]>$/g, "")).trim() : "";
};

export async function googleNews(q: string): Promise<NewsItem[] | null> {
  const xml = await getText(`https://news.google.com/rss/search?q=${encodeURIComponent(q + " when:1d")}&${GN_LOCALE}`);
  if (xml == null) return null;
  const items: NewsItem[] = [];
  for (const block of xml.split("<item>").slice(1)) {
    const source = rssField(block, "source");
    let title = rssField(block, "title");
    // Google appends " - Publisher" to every headline.
    if (source && title.endsWith(` - ${source}`)) title = title.slice(0, -(source.length + 3));
    const it = makeItem("google", rssField(block, "link"), Date.parse(rssField(block, "pubDate")), title, source, "", []);
    if (it) items.push(it);
  }
  return items;
}

/** Run async jobs `limit` at a time (Google News throttles bursts). */
export async function pool<T>(jobs: (() => Promise<T>)[], limit: number): Promise<T[]> {
  const out: T[] = new Array(jobs.length);
  let next = 0;
  const worker = async () => {
    while (next < jobs.length) {
      const i = next++;
      out[i] = await jobs[i]();
    }
  };
  await Promise.all(Array.from({ length: Math.min(limit, jobs.length) }, worker));
  return out;
}

// One warm instance serves repeat polls from memory; the CDN (s-maxage on the
// route) absorbs the rest.
const MEMO_MS = 60_000;
let memo: { at: number; feed: Promise<NewsFeed> } | null = null;

export function getNewsFeed(): Promise<NewsFeed> {
  if (memo && Date.now() - memo.at < MEMO_MS) return memo.feed;
  const feed = buildFeed();
  memo = { at: Date.now(), feed };
  feed.catch(() => (memo = null));
  return feed;
}

async function buildFeed(): Promise<NewsFeed> {
  const now = Date.now();
  const since = now - DAY_MS;
  const { queries } = getMap();
  const [poly, finn, google] = await Promise.all([
    polygon(since),
    finnhub(),
    pool(queries.map((q) => () => googleNews(q)), 6),
  ]);

  const feeds: NewsFeed["feeds"] = [
    { name: "polygon", count: poly?.length ?? 0, failed: poly ? 0 : 1 },
    { name: "finnhub", count: 0, failed: finn ? 0 : 1 },
    { name: "google", count: 0, failed: google.filter((g) => g == null).length },
  ];

  // Same story from several feeds / searches → one row; the feeds with blurbs
  // and tickers (Polygon, Finnhub) come first so their copy is the one kept.
  const byKey = new Map<string, NewsItem>();
  const all = [...(poly || []), ...(finn || []), ...google.flatMap((g) => g || [])];
  for (const it of all) {
    if (it.time < since || it.time > now + 600_000) continue;
    const key = it.title.toLowerCase().replace(/[^\p{L}\p{N}]+/gu, "").slice(0, 90);
    const seen = byKey.get(key);
    if (seen) {
      seen.companies = [...new Set([...seen.companies, ...it.companies])];
      seen.tickers = [...new Set([...seen.tickers, ...it.tickers])];
      continue;
    }
    byKey.set(key, it);
    if (it.feed === "finnhub") feeds[1].count++;
    if (it.feed === "google") feeds[2].count++;
  }
  const items = [...byKey.values()].sort((a, b) => b.time - a.time);

  // Every headline and publisher reads in English (user, 2026-10-13); companies were
  // tagged on the original wording above, so Korean / Japanese names still count.
  const english = await toEnglish(items.flatMap((it) => [it.title, it.source]));
  for (const it of items) {
    const en = english.get(it.title);
    if (en) [it.original, it.title] = [it.title, en];
    it.source = english.get(it.source) ?? it.source;
  }

  const tickers: Record<string, string | null> = {};
  for (const it of items) for (const id of it.companies) tickers[id] = tickerOf(id);
  return { at: now, items, tickers, feeds };
}
