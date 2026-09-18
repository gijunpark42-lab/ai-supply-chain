// retrieval.ts — "Ask the Graph", step 1 of 2: find the stored facts that can
// answer a question. (Step 2 is /api/ask, which hands those facts to Claude.)
//
// The whole graph is already in the browser (VizNode[] / VizLink[] built by
// data.ts), so the search runs HERE, on the client. Only the ~15 best snippets
// are sent to the server, and the server never touches the graph itself.
// Nothing in this file talks to the network.
//
// Two ideas a first-time reader needs:
//
//   * A "document" is ONE stored fact. There are two kinds:
//       - "signal"   = a quarterly_data entry (what a company said about itself
//                      on its own earnings call / filing)
//       - "contract" = a deal entry on a supplier → customer edge
//     Both carry a source label like "NVIDIA Q2 FY2027 (08-26-2026)"; the date
//     in parentheses is the date of the source document.
//
//   * BM25 is the classic keyword-ranking formula search engines used long
//     before neural search. A document scores higher when it contains the
//     question's words; rare words count more than common ones (idf); repeating
//     a word helps, with diminishing returns (k1); and very long documents are
//     gently penalised (b). It is ~30 lines of arithmetic and needs no model.
//
// On top of BM25 we add what a human analyst would do by reflex:
//   - naming a company     → that company's own facts count ×3
//   - naming a generation  → facts from that chain / topic count ×1.5
//   - freshness            → newer source labels get a mild bump
//   - result diversity     → one company cannot fill every slot
//
// Public API (used by components/AskGraph.tsx):
//   retrieve(question, nodes, links, k?)          → Snippet[]
//   retrieveWithMeta(question, nodes, links, k?)  → { snippets, companies, chains, topics, terms }
//   suggestQuestions(nodes)                       → string[]   (6–8 example questions)
//   tokenize(text)                                → string[]   (exported for tests)

import type { VizNode, VizLink, QuarterlyData, Contract } from "./types";

// ── Public shapes ──────────────────────────────────────────────────────────

export type SnippetKind = "signal" | "contract";

/** One stored fact, ready to be shown in the UI and sent to /api/ask. */
export interface Snippet {
  kind: SnippetKind;
  /** The node the fact belongs to (for a contract: the SUPPLIER / edge source). */
  company: string;
  /** Contract only: the edge target (the customer). */
  target?: string;
  /** Chain file the fact came from, e.g. "nvidia_vera_rubin". */
  chain: string;
  /** Source label, e.g. "SK Hynix Q2 FY2026 (08-14-2026)". */
  label: string;
  /** "YYYY-MM-DD" parsed from the label, or "" when the label has no date. */
  date: string;
  /** The fact itself (signal + figure, or edge + contract detail). */
  text: string;
  /** Timeline / screener tags the enrichment step attached (may be empty). */
  topics?: string[];
}

/** retrieve() plus what the question parser recognised — shown as a hint in the UI. */
export interface RetrievalResult {
  snippets: Snippet[];
  companies: string[];
  chains: string[];
  topics: string[];
  terms: string[];
}

// ── Tunables ───────────────────────────────────────────────────────────────

const DEFAULT_K = 40; // at most this many snippets ...
const MAX_CONTEXT_CHARS = 12_000; // ... and at most this many characters of snippet text
const MAX_SIGNAL_CHARS = 900; // a single signal is cut here (the figure is kept separately)
const MAX_CONTRACT_CHARS = 700;

const BM25_K1 = 1.2;
const BM25_B = 0.75;

const COMPANY_MULT = 3; // "company match ×3" — the named company's OWN facts
const COMPANY_FLOOR = 3; // ...which stay retrievable even with zero word overlap; worth about
//                          one matched content word, so "what did Vertiv say about backlog"
//                          prefers Vertiv's facts over strangers' incidental "backlog" mentions
const PARTY_MULT = 2; // deals where the named company is only the counterparty (edge target)
const PARTY_FLOOR = 1.5;
const COMPANY_TERM_WEIGHT = 0.5; // words that named a company already earn the ×3, so they count
//                                  half as BM25 terms — content words must dominate
const RESERVED_PER_COMPANY = 6; // a named company always gets this many of its best facts in ...
const RESERVED_RELATION = 3; // ... or this many when the question is about who-supplies-whom
const CHAIN_BONUS = 0.5; // "chain match ×1.5"
const TOPIC_BONUS = 0.5; // "topic match ×1.5"
const CONTRACT_BONUS = 0.3; // when the question is about who-supplies-whom
const PERIOD_BONUS = 0.5; // question names "Q2 FY2026" and the source label carries it
const RECENCY_MAX = 0.2; // newest label ×1.2, fading to ×1.0 over RECENCY_DAYS
const RECENCY_DAYS = 540;

// ── Text helpers ───────────────────────────────────────────────────────────

// Words are runs of letters/digits; a dot is kept only between digits, so
// "1.6T" stays one token ("1.6t") while "U.S." splits into "u" and "s".
const TOKEN_RE = /[a-z0-9]+(?:\.[0-9][a-z0-9]*)*/g;

/** Lower-case word list. Exported so a test can check the exact splitting. */
export function tokenize(text: string): string[] {
  return text.toLowerCase().match(TOKEN_RE) || [];
}

// Same split, but case is preserved (needed to tell the ticker "MU" from "mu").
const RAW_TOKEN_RE = /[A-Za-z0-9]+(?:\.[0-9][A-Za-z0-9]*)*/g;

// Words that carry no meaning for ranking. Question words are here on purpose
// ("what", "who", "say") — they would otherwise match every document a little.
const STOPWORDS = new Set(
  (
    "a an and are as at be been being by can could did do does for from had has have how " +
    "if in into is it its of on or over per should than that the their them then there these " +
    "they this those to under up was were what whats when where which who whom whose why will " +
    "with would about any all also some more most much many just only very vs versus " +
    "say says said tell told me us give show list explain describe mention mentions mentioned " +
    "report reports reported reporting company companies latest recent recently new news update " +
    "updates call calls quarter earnings graph data know think"
  ).split(" ")
);

// A very light stemmer: plural → singular. Tokens containing digits ("hbm4",
// "gpus" is fine, "800g" must not lose its g) are left alone.
function stem(w: string): string {
  if (/\d/.test(w)) return w;
  if (w.length > 4 && w.endsWith("ies")) return w.slice(0, -3) + "y";
  if (w.length > 4 && /(ches|shes|sses|xes|zes)$/.test(w)) return w.slice(0, -2);
  if (w.length > 3 && w.endsWith("s") && !w.endsWith("ss") && !w.endsWith("us"))
    return w.slice(0, -1);
  return w;
}

/** tokenize → drop stopwords → stem. This is what both documents and questions become. */
function terms(text: string): string[] {
  const out: string[] = [];
  for (const t of tokenize(text)) {
    if (t.length < 2 || STOPWORDS.has(t)) continue;
    out.push(stem(t));
  }
  return out;
}

// Query-side synonyms. Each expansion is added at HALF weight so the user's own
// words still dominate. Keys and values are stemmed forms.
const EXPAND: Record<string, string[]> = {
  supplier: ["supply", "supplie", "sourced", "vendor"],
  supply: ["supplier", "supplie"],
  customer: ["buyer", "client"],
  revenue: ["sale"],
  capex: ["capital", "expenditure", "spending"],
  sold: ["allocated", "allocation"],
  backlog: ["rpo", "order", "book"],
  price: ["pricing", "asp"],
  margin: ["gm", "opm"],
  demand: ["order", "visibility"],
  shortage: ["tight", "constrained", "allocation"],
};

const LABEL_DATE_RE = /\((\d{2})-(\d{2})-(\d{4})\)\s*$/;
// Reporting-period tokens as they appear in labels and questions: q1–q4, fy2026 / fy26, h1/h2, 1h/2h.
const PERIOD_RE = /^(q[1-4]|fy\d{2}|fy20\d{2}|h[12]|[12]h)$/;

/** "NVIDIA Q2 FY2027 (08-26-2026)" → { iso: "2026-08-26", ms: <epoch ms> }. */
function labelDate(label: string): { iso: string; ms: number } | null {
  const m = LABEL_DATE_RE.exec(label || "");
  if (!m) return null;
  const d = new Date(+m[3], +m[1] - 1, +m[2]);
  if (isNaN(d.getTime())) return null;
  return { iso: `${m[3]}-${m[1]}-${m[2]}`, ms: d.getTime() };
}

/** Cut text at a word boundary near `max` characters. */
function trimTo(text: string, max: number): string {
  if (text.length <= max) return text;
  const cut = text.lastIndexOf(" ", max);
  return text.slice(0, cut > max * 0.6 ? cut : max).trimEnd() + " …";
}

const isFigure = (s: string | undefined): s is string =>
  !!s && s !== "no specific figure" && s !== "not stated";

// ── The index ──────────────────────────────────────────────────────────────

interface Doc extends Snippet {
  tf: Map<string, number>; // term → how often it occurs in this doc
  len: number; // number of terms (for the BM25 length penalty)
  labelTerms: Set<string>; // the source label's own words ("q2", "fy2026") for the period boost
  ageDays: number; // days older than the newest label in the index; -1 = undated
  ms: number; // label date in epoch ms (0 = undated)
}

interface CompanyIndex {
  phrases: Map<string, string[]>; // "sk hynix" | "hynix" alias phrase → node ids
  words: Map<string, string[]>; // one distinctive word → node ids (≤ 2 ids)
  tickers: Map<string, string>; // "nvda" → "NVIDIA"
  maxWords: number; // longest alias, in words
}

interface Index {
  docs: Doc[];
  df: Map<string, number>; // term → number of docs containing it
  avgLen: number;
  companies: CompanyIndex;
}

function signalDoc(company: string, q: QuarterlyData): Doc {
  const figure = isFigure(q.figure) ? q.figure : "";
  const signal = q.signal || "";
  const label = q.quarter || "";
  const topics = [...(q.topics || [])];
  // Screener / capex tags become pseudo-topics so "capex", "guidance" and
  // "backlog" questions can prefer the entries enrichment marked as such.
  if (q.capex) topics.push("capex");
  if (q.slot === "guidance") topics.push("guidance");
  if (q.slot === "backlog_or_b2b") topics.push("backlog");
  const text = trimTo(signal, MAX_SIGNAL_CHARS) + (figure ? ` Figure: ${figure}` : "");
  const searchable = `${company} ${signal} ${figure} ${label} ${topics.join(" ")}`;
  const when = labelDate(label);
  return {
    kind: "signal",
    company,
    chain: q.chain || "",
    label,
    date: when ? when.iso : "",
    text,
    topics,
    ...termStats(searchable),
    labelTerms: new Set(tokenize(label)),
    ageDays: -1,
    ms: when ? when.ms : 0,
  };
}

function contractDoc(
  source: string,
  target: string,
  relationship: string,
  chain: string,
  c: Contract
): Doc {
  const meta = [c.units, c.value, c.date_signed, c.type].filter(isFigure).join(" · ");
  const label = c.source || "";
  const text =
    `${source} → ${target}: ${relationship}. ${trimTo(c.signal || "", MAX_CONTRACT_CHARS)}` +
    (meta ? ` (${meta})` : "");
  const searchable = `${source} ${target} ${relationship} ${c.signal} ${c.units} ${c.value} ${c.type} ${label} ${(c.topics || []).join(" ")}`;
  const when = labelDate(label);
  return {
    kind: "contract",
    company: source,
    target,
    chain,
    label,
    date: when ? when.iso : "",
    text,
    topics: c.topics || [],
    ...termStats(searchable),
    labelTerms: new Set(tokenize(label)),
    ageDays: -1,
    ms: when ? when.ms : 0,
  };
}

function termStats(searchable: string): { tf: Map<string, number>; len: number } {
  const tf = new Map<string, number>();
  const ts = terms(searchable);
  for (const t of ts) tf.set(t, (tf.get(t) || 0) + 1);
  return { tf, len: ts.length };
}

// Trailing legal-name words people leave out ("Amkor Technology" → "Amkor").
const SUFFIX = new Set([
  "systems", "technologies", "technology", "inc", "corp", "corporation", "holdings",
  "group", "semiconductor", "semiconductors", "co", "ltd", "limited", "plc", "sa", "ag", "nv",
]);

// Words that appear in many company names and therefore identify none of them.
const GENERIC_WORDS = new Set([
  "technology", "technologies", "semiconductor", "semiconductors", "electric", "electronics",
  "energy", "group", "holdings", "systems", "industries", "industrial", "materials", "chemical",
  "corporation", "company", "power", "digital", "labs", "cloud", "data", "global",
  "international", "advanced", "printing", "circuit", "metals", "optical", "networks",
  "solutions", "research", "computing", "center", "fine", "mining", "smelting", "heavy",
  "electro", "mechanics", "precision", "science", "korea", "japan", "taiwan", "american",
  "united", "south", "north", "steel", "cable", "instruments", "devices", "machines", "test",
  "engineering", "design", "foundry", "memory", "micro", "silicon", "photonics",
  "optoelectronics", "infrastructure", "motion", "storage", "capital", "partners",
]);

// Business-unit / former names that no spelling rule would connect. Only added
// when the target node actually exists in the graph.
const ALIASES: Record<string, string> = {
  aws: "Amazon",
  "amazon web services": "Amazon",
  alphabet: "Google",
  "google cloud": "Google",
  gcp: "Google",
  azure: "Microsoft",
  "hon hai": "Foxconn",
  facebook: "Meta",
  "meta platforms": "Meta",
  "super micro": "Supermicro",
  "taiwan semiconductor": "TSMC",
  "samsung electronics": "Samsung",
  hynix: "SK Hynix",
};

// Upper-case tokens that are real words far more often than tickers.
const TICKER_SKIP = new Set(["ON", "IT", "US", "AI", "AT", "AN", "IN", "IS", "OR", "SO", "TO",
  "UP", "WE", "DO", "GO", "IF", "NO", "OF", "MY", "ME", "BY", "AS", "HD", "GE", "TE", "SK", "LS"]);

function buildCompanyIndex(nodes: VizNode[]): CompanyIndex {
  const phrases = new Map<string, string[]>();
  const words = new Map<string, string[]>();
  const tickers = new Map<string, string>();
  const ids = new Set(nodes.map((n) => n.id));
  let maxWords = 1;

  const addPhrase = (phrase: string, id: string) => {
    if (!phrase) return;
    const list = phrases.get(phrase) || [];
    if (!list.includes(id)) list.push(id);
    phrases.set(phrase, list);
    maxWords = Math.max(maxWords, phrase.split(" ").length);
  };

  for (const n of nodes) {
    // "Resonac (Showa Denko)" → aliases "Resonac" and "Showa Denko".
    const aliases = [n.id.replace(/\([^)]*\)/g, " ")];
    const paren = /\(([^)]+)\)/.exec(n.id);
    if (paren) aliases.push(paren[1]);

    for (const alias of aliases) {
      const w = tokenize(alias);
      if (!w.length) continue;
      addPhrase(w.join(" "), n.id);
      // Suffix-stripped form: "arm holdings" → "arm", "amkor technology" → "amkor".
      const short = [...w];
      while (short.length > 1 && SUFFIX.has(short[short.length - 1])) short.pop();
      if (short.length < w.length) addPhrase(short.join(" "), n.id);
      // Single distinctive words: "hynix", "vernova", "schneider".
      for (const word of w) {
        if (word.length < 4 || GENERIC_WORDS.has(word) || /^\d+$/.test(word)) continue;
        const list = words.get(word) || [];
        if (!list.includes(n.id)) list.push(n.id);
        words.set(word, list);
      }
    }
    // US-style tickers only ("NVDA"); "000660.KS" / "2382.TW" never appear in a question.
    if (n.ticker && !n.ticker.includes(".")) tickers.set(n.ticker.toLowerCase(), n.id);
  }

  for (const [alias, id] of Object.entries(ALIASES)) if (ids.has(id)) addPhrase(alias, id);

  // A word shared by more than two names identifies nothing — drop it.
  for (const [w, list] of words) if (list.length > 2) words.delete(w);
  // A full-name phrase always wins over a word of the same spelling ("samsung").
  for (const w of words.keys()) if (phrases.has(w)) words.delete(w);

  return { phrases, words, tickers, maxWords };
}

function buildIndex(nodes: VizNode[], links: VizLink[]): Index {
  const docs: Doc[] = [];

  // Signals: every quarterly_data entry on every node.
  for (const n of nodes) for (const q of n.quarterly_data || []) docs.push(signalDoc(n.id, q));

  // Contracts. NOTE: buildViz() keeps only the first 3 contracts per VizLink
  // (enough for the 3D tooltip), but node.outgoing carries the full list — so
  // read from the nodes and fall back to the links only if `outgoing` is absent.
  const seen = new Set<string>();
  const haveOutgoing = nodes.some((n) => Array.isArray(n.outgoing));
  if (haveOutgoing) {
    for (const n of nodes)
      for (const e of n.outgoing || [])
        for (const c of e.contracts || []) {
          const key = `${n.id}|${e.target}|${c.source}|${c.signal}`;
          if (seen.has(key)) continue; // the same deal can be stored in two chain files
          seen.add(key);
          docs.push(contractDoc(n.id, e.target, e.relationship, e.chain, c));
        }
  } else {
    for (const l of links)
      for (const c of l.contracts || []) {
        const key = `${l.source}|${l.target}|${c.source}|${c.signal}`;
        if (seen.has(key)) continue;
        seen.add(key);
        docs.push(contractDoc(l.source, l.target, l.relationship, l.chain, c));
      }
  }

  // Document frequency + average length (the two corpus-wide BM25 statistics).
  const df = new Map<string, number>();
  let totalLen = 0;
  for (const d of docs) {
    totalLen += d.len;
    for (const t of d.tf.keys()) df.set(t, (df.get(t) || 0) + 1);
  }

  // Age is measured from the NEWEST label in the graph, not from today, so the
  // ranking does not drift as the graph goes unenriched for a while.
  let newest = 0;
  for (const d of docs) if (d.ms > newest) newest = d.ms;
  for (const d of docs) d.ageDays = d.ms ? Math.round((newest - d.ms) / 86_400_000) : -1;

  return {
    docs,
    df,
    avgLen: docs.length ? totalLen / docs.length : 1,
    companies: buildCompanyIndex(nodes),
  };
}

// Building the index costs ~2,500 tokenisations — trivial, but there is no
// reason to redo it per keystroke. We remember the last (nodes, links) pair by
// object identity: page.tsx memoises viz, so the same arrays arrive every time.
let cached: { nodes: VizNode[]; links: VizLink[]; index: Index } | null = null;

function getIndex(nodes: VizNode[], links: VizLink[]): Index {
  if (cached && cached.nodes === nodes && cached.links === links) return cached.index;
  const index = buildIndex(nodes, links);
  cached = { nodes, links, index };
  return index;
}

// ── Question parsing ───────────────────────────────────────────────────────

/**
 * Which graph nodes does the question name? Scans word n-grams longest-first
 * ("sk hynix" before "hynix"), so each word is claimed once. A lone word matches
 * a node only when it is distinctive, and a ticker only when typed in capitals.
 * Also returns the words that were claimed, so scoring can down-weight them.
 */
function detectCompanies(
  rawTokens: string[],
  ci: CompanyIndex
): { ids: string[]; consumed: Set<string> } {
  const toks = rawTokens.map((t) => t.toLowerCase());
  const used: boolean[] = new Array(toks.length).fill(false);
  const found: string[] = [];

  for (let n = Math.min(ci.maxWords, toks.length); n >= 1; n--) {
    for (let i = 0; i + n <= toks.length; i++) {
      let clash = false;
      for (let j = i; j < i + n; j++) if (used[j]) clash = true;
      if (clash) continue;

      let ids = ci.phrases.get(toks.slice(i, i + n).join(" "));
      if (!ids && n === 1) {
        const raw = rawTokens[i];
        const byTicker = ci.tickers.get(toks[i]);
        const looksLikeTicker =
          raw === raw.toUpperCase() && /[A-Z]/.test(raw) && !TICKER_SKIP.has(raw);
        ids = byTicker && looksLikeTicker ? [byTicker] : ci.words.get(toks[i]);
      }
      if (!ids) continue;
      for (const id of ids) if (!found.includes(id)) found.push(id);
      for (let j = i; j < i + n; j++) used[j] = true;
    }
  }
  const consumed = new Set<string>();
  toks.forEach((t, i) => {
    if (used[i]) consumed.add(stem(t));
  });
  return { ids: found, consumed };
}

// Generation / chain / topic vocabulary. Each rule is tested against the
// space-joined lower-case tokens of the question (so "co-packaged" reads
// "co packaged" and "1.6T" reads "1.6t"). Chain ids are the files in chains/;
// topic ids are the files in timelines/ plus the pseudo-topics from signalDoc().
interface VocabRule {
  re: RegExp;
  chains?: string[];
  topics?: string[];
  /** true = the words NAME a generation (the chain boost covers them, so they
   *  count half as search terms). Product / topic words such as "hbm4" or
   *  "cowos" are real content and keep full weight. */
  generation?: boolean;
}

const TPU_CHAINS = ["google_tpu_v7_ironwood", "tpu_v8t", "tpu_v8i"];

const VOCAB: VocabRule[] = [
  { re: /\b(vera|rubin|vr200|nvl144)\b/, chains: ["nvidia_vera_rubin"], generation: true },
  { re: /\b(b200|b300|gb200|gb300|blackwell|nvl72)\b/, chains: ["nvda_b200"], generation: true },
  { re: /\b(helios|mi450|mi455|mi455x|mi400)\b/, chains: ["amd_mi450_helios"], generation: true },
  { re: /\b(mi355|mi355x|mi350|mi325|mi300)\b/, chains: ["amd_mi355"], generation: true },
  { re: /\btrainium ?3\b|\btrn3\b/, chains: ["aws_trainium3"], generation: true },
  { re: /\btrainium ?2\b|\btrn2\b/, chains: ["aws_trainium2"], generation: true },
  { re: /\btrainium\b/, chains: ["aws_trainium2", "aws_trainium3"], generation: true },
  { re: /\bironwood\b|\btpu ?v7\b|\bv7\b/, chains: ["google_tpu_v7_ironwood"], generation: true },
  { re: /\bv8t\b/, chains: ["tpu_v8t"], generation: true },
  { re: /\bv8i\b/, chains: ["tpu_v8i"], generation: true },
  { re: /\btpu ?v8\b|\bv8\b/, chains: ["tpu_v8t", "tpu_v8i"], generation: true },
  { re: /\btpus?\b/, chains: TPU_CHAINS, generation: true },
  { re: /\bhbm\w*\b|\bhigh bandwidth memory\b/, chains: ["hbm_memory"], topics: ["hbm"] },
  {
    re: /\b(cowos|soic|substrates?|packaging|glass core|glass substrate|abf|t glass|fc bga|hybrid bonding|tc bonders?|bonders?|interposers?)\b/,
    chains: ["packaging_substrate"],
    topics: ["packaging_substrate"],
  },
  { re: /\b(cpo|co packaged)\b/, chains: ["optical_networking"], topics: ["cpo"] },
  {
    re: /\b(optical|optics|transceivers?|dsps?|lasers?|eml|vcsel|1\.6t|800g|3\.2t|linear pluggable|lpo|retimers?|pluggables?)\b/,
    chains: ["optical_networking"],
    topics: ["optical_speed"],
  },
  { re: /\b(photonics?|sipho|silicon photonic\w*)\b/, chains: ["optical_networking"], topics: ["silicon_photonics"] },
  { re: /\b(ocs|optical circuit switch\w*)\b/, topics: ["ocs"] },
  {
    re: /\b(power|transformers?|grid|utility|utilities|nuclear|smr|smrs|gas turbines?|switchgear|ups|busbars?|cooling|liquid cooled|liquid cooling|thermal|cdus?|immersion|chillers?|heat exchangers?|megawatts?|gigawatts?|\d+ ?[gm]w|data ?cent(er|re)s? power)\b/,
    chains: ["power_cooling"],
    topics: ["power_cooling"],
  },
  { re: /\b(gan|sic|silicon carbide|power semiconductors?|power semis?|800v|hvdc)\b/, chains: ["power_semiconductor", "power_cooling"] },
  { re: /\b(mlccs?|capacitors?|passives?)\b/, chains: ["mlcc"] },
  { re: /\b(nand|ssds?|storage|flash|qlc|hdds?|enterprise ssd)\b/, chains: ["nand_flash"], topics: ["nand_storage"] },
  { re: /\b(cpus?|server cpus?|grace|epyc|xeon|neoverse)\b/, chains: ["cpu_datacenter"], topics: ["cpu"] },
  {
    re: /\b(foundry|foundries|n2|n3|n3p|a16|18a|2nm|3nm|wafer starts?|process node|nodes?|fabs?)\b/,
    chains: ["foundry"],
    topics: ["foundry"],
  },
  { re: /\b(neoclouds?|gpu clouds?|gpu as a service)\b/, chains: ["neocloud"] },
  {
    re: /\b(drug discovery|biotech\w*|biopharma\w*|pharma\w*|genomics?|omics|sequencing|proteomics?|antibod\w*|molecules?|clinical trials?|precision medicine|protein\w*)\b/,
    chains: ["ai_bio"],
  },
  { re: /\b(asics?|custom silicon|xpus?|custom accelerators?)\b/, chains: ["broadcom_custom_asic"] },
  { re: /\b(sold out|allocation|allocated|shortages?|tight|tightness|constrained|constraints?|lead times?)\b/, topics: ["supply_tightness"] },
  { re: /\b(launch\w*|ramp\w*|sampling|mass production|volume production|shipping)\b/, topics: ["product_launches"] },
  { re: /\b(transitions?|next gen\w*|generation|migrat\w*|upgrade cycle)\b/, topics: ["transitions"] },
  { re: /\bcapex\b|\bcapital expenditures?\b|\bcapital spending\b|\bspending plans?\b/, topics: ["capex"] },
  { re: /\b(guidance|outlook|guide|guided|forecast)\b/, topics: ["guidance"] },
  { re: /\b(backlog|rpo|remaining performance|book to bill|orders?|order book)\b/, topics: ["backlog"] },
];

// "Who supplies…", "customers of…", "won a contract…" → the user cares about
// edges, so contracts get a bump and no single company may crowd the list.
const RELATION_RE =
  /\b(suppl\w*|vendors?|sourc\w*|customers?|buyers?|sells? to|ships? to|makes?|manufactur\w*|provid\w*|partners?|wins?|won|award\w*|contracts?|deals?)\b/;

// ── Scoring ────────────────────────────────────────────────────────────────

function idf(index: Index, term: string): number {
  const n = index.docs.length;
  const d = index.df.get(term) || 0;
  return Math.log(1 + (n - d + 0.5) / (d + 0.5));
}

/**
 * Weighted query terms: content words at 1.0, words that named a company at
 * COMPANY_TERM_WEIGHT (their job is done by the ×3), and synonyms of the
 * content words at 0.5. Generation words ("rubin") keep full weight — when no
 * company is named they ARE the content ("latest on Blackwell demand").
 */
function queryTerms(question: string, companyTerms: Set<string>): Map<string, number> {
  const q = new Map<string, number>();
  for (const t of terms(question)) q.set(t, companyTerms.has(t) ? COMPANY_TERM_WEIGHT : 1);
  for (const [t, w] of [...q.entries()]) {
    if (w < 1) continue;
    for (const x of EXPAND[t] || []) if (!q.has(x)) q.set(x, 0.5);
  }
  return q;
}

/**
 * Rank every document for one question and return the best ones, capped by
 * count (k), by total characters (MAX_CONTEXT_CHARS) and by per-company share.
 */
export function retrieveWithMeta(
  question: string,
  nodes: VizNode[],
  links: VizLink[],
  k: number = DEFAULT_K
): RetrievalResult {
  const index = getIndex(nodes, links);
  const rawTokens = question.match(RAW_TOKEN_RE) || [];
  const joined = " " + rawTokens.join(" ").toLowerCase() + " ";

  const { ids: companies, consumed: companyTerms } = detectCompanies(rawTokens, index.companies);
  const companySet = new Set(companies);

  // Entity words = company names + generation names. They still score, but
  // outside the company multiplier: naming NVIDIA must not turn every "Rubin"
  // mention in NVIDIA's own entries into a ×3 magnet.
  const entityTerms = new Set(companyTerms);
  const chainSet = new Set<string>();
  const topicSet = new Set<string>();
  for (const rule of VOCAB) {
    if (!rule.re.test(joined)) continue;
    for (const c of rule.chains || []) chainSet.add(c);
    for (const t of rule.topics || []) topicSet.add(t);
    if (rule.generation)
      for (const hit of joined.match(new RegExp(rule.re.source, "g")) || [])
        for (const w of hit.trim().split(" ")) if (w) entityTerms.add(stem(w));
  }

  const relationIntent = RELATION_RE.test(joined);
  const qt = queryTerms(question, companyTerms);

  // "Q2", "FY2026", "H1": when the question names a reporting period, entries
  // whose SOURCE LABEL carries that period are the ones being asked about.
  const periodTerms = [...qt.keys()].filter((t) => PERIOD_RE.test(t));

  // Cache idf per query term (same value for every document).
  const idfOf = new Map<string, number>();
  for (const t of qt.keys()) idfOf.set(t, idf(index, t));

  const scored: { d: Doc; s: number }[] = [];
  for (const d of index.docs) {
    // 1) BM25 over the question's words, split into CONTENT words ("hbm4",
    //    "capacity") and ENTITY words (company / generation names).
    let content = 0;
    let entity = 0;
    for (const [t, w] of qt) {
      const tf = d.tf.get(t);
      if (!tf) continue;
      const norm = tf + BM25_K1 * (1 - BM25_B + (BM25_B * d.len) / index.avgLen);
      const part = w * (idfOf.get(t) || 0) * ((tf * (BM25_K1 + 1)) / norm);
      if (entityTerms.has(t)) entity += part;
      else content += part;
    }
    // 2) Named company: the content match on its OWN facts counts ×3 (plus a
    //    small floor, so "what did X say recently" works with no word overlap
    //    at all); deals where it is only the counterparty count ×2. Entity
    //    words are added unmultiplied — a tiebreaker, not a magnet.
    let s: number;
    if (companySet.has(d.company)) s = content * COMPANY_MULT + entity + COMPANY_FLOOR;
    else if (d.target !== undefined && companySet.has(d.target))
      s = content * PARTY_MULT + entity + PARTY_FLOOR;
    else s = content + entity;
    if (s <= 0) continue;
    // 3) Chain / topic / period / edge-intent boosts, then freshness.
    let boost = 1;
    if (chainSet.has(d.chain)) boost += CHAIN_BONUS;
    if (d.topics && d.topics.some((t) => topicSet.has(t))) boost += TOPIC_BONUS;
    if (periodTerms.length && periodTerms.every((t) => d.labelTerms.has(t))) boost += PERIOD_BONUS;
    if (relationIntent && d.kind === "contract") boost += CONTRACT_BONUS;
    s *= boost;
    if (d.ageDays >= 0) s *= 1 + RECENCY_MAX * Math.max(0, 1 - d.ageDays / RECENCY_DAYS);
    scored.push({ d, s });
  }
  scored.sort((a, b) => b.s - a.s);

  // Selection, within the caps (k snippets, MAX_CONTEXT_CHARS characters):
  //   pass 1 — a named company gets its best few facts reserved up front, so
  //            "what did Vertiv say about backlog" is mostly about Vertiv even
  //            when other companies' entries happen to contain "backlog";
  //   pass 2 — everything else by score, with one company holding at most
  //            `perCompany` slots so a hub like NVIDIA cannot crowd out its suppliers.
  const perCompany = relationIntent ? 4 : 8;
  const reserve = relationIntent ? RESERVED_RELATION : RESERVED_PER_COMPANY;
  const count = new Map<string, number>();
  const picked: { d: Doc; s: number }[] = [];
  let chars = 0;
  const take = (item: { d: Doc; s: number }) => {
    picked.push(item);
    chars += item.d.text.length;
    count.set(item.d.company, (count.get(item.d.company) || 0) + 1);
  };
  const fits = (d: Doc) => picked.length < k && chars + d.text.length <= MAX_CONTEXT_CHARS;

  for (const item of scored) {
    if (!companySet.has(item.d.company) || (count.get(item.d.company) || 0) >= reserve) continue;
    if (fits(item.d)) take(item);
  }
  for (const item of scored) {
    if (MAX_CONTEXT_CHARS - chars < 150 || picked.length >= k) break;
    if (picked.includes(item)) continue;
    if ((count.get(item.d.company) || 0) >= perCompany) continue;
    if (fits(item.d)) take(item); // else: too long for what is left — try a shorter one
  }
  picked.sort((a, b) => b.s - a.s);

  const snippets: Snippet[] = picked.map(({ d }) => ({
    kind: d.kind,
    company: d.company,
    target: d.target,
    chain: d.chain,
    label: d.label,
    date: d.date,
    text: d.text,
    topics: d.topics,
  }));

  return {
    snippets,
    companies,
    chains: [...chainSet],
    topics: [...topicSet],
    terms: [...qt.keys()].filter((t) => qt.get(t) === 1),
  };
}

/** The plain version: just the snippets. */
export function retrieve(
  question: string,
  nodes: VizNode[],
  links: VizLink[],
  k: number = DEFAULT_K
): Snippet[] {
  return retrieveWithMeta(question, nodes, links, k).snippets;
}

// ── Suggested questions ────────────────────────────────────────────────────

// Readable phrase for each timeline topic id (for "What did X say about …?").
const TOPIC_PHRASE: Record<string, string> = {
  hbm: "HBM",
  cpo: "co-packaged optics",
  power_cooling: "power and cooling",
  packaging_substrate: "advanced packaging",
  supply_tightness: "supply tightness",
  foundry: "foundry capacity",
  nand_storage: "NAND and storage",
  optical_speed: "800G and 1.6T optics",
  silicon_photonics: "silicon photonics",
  cpu: "server CPUs",
  ocs: "optical circuit switches",
  product_launches: "product launches",
  transitions: "the next generation",
};

let suggestCache: { nodes: VizNode[]; out: string[] } | null = null;

/**
 * 6–8 example questions built FROM the data, so every chip has something to
 * find. Each candidate is kept only if the graph really contains matching text.
 */
export function suggestQuestions(nodes: VizNode[]): string[] {
  if (suggestCache && suggestCache.nodes === nodes) return suggestCache.out;

  const all: { company: string; q: QuarterlyData }[] = [];
  for (const n of nodes) for (const q of n.quarterly_data || []) all.push({ company: n.id, q });
  const anyText = (re: RegExp) => all.some((x) => re.test(x.q.signal + " " + x.q.figure));
  const anyTopic = (t: string) => all.some((x) => (x.q.topics || []).includes(t));

  const out: string[] = [];
  const add = (ok: boolean, question: string) => {
    if (ok && out.length < 8 && !out.includes(question)) out.push(question);
  };

  add(
    nodes.some((n) =>
      n.products.some((p) => p.chain === "nvidia_vera_rubin" && /hbm4/i.test(p.product))
    ) && anyText(/hbm4/i),
    "Who supplies HBM4 for NVIDIA Vera Rubin?"
  );
  add(anyText(/sold out|allocat/i), "Which companies report supply as sold out or on allocation?");

  // The two best-connected companies with data: ask about their latest topic.
  // Entries enriched before topic tagging existed have no `topics`, so fall back
  // to the same vocabulary rules the question parser uses, run over the text.
  const hubs = [...nodes]
    .filter((n) => (n.quarterly_data || []).length > 0)
    .sort((a, b) => b.degree - a.degree)
    .slice(0, 2);
  for (const n of hubs) {
    const newestFirst = [...n.quarterly_data].sort(
      (a, b) => (labelDate(b.quarter)?.ms || 0) - (labelDate(a.quarter)?.ms || 0)
    );
    let topic: string | undefined;
    for (const q of newestFirst) {
      topic = (q.topics || []).find((t) => TOPIC_PHRASE[t]);
      if (topic) break;
      const text = " " + tokenize(q.signal || "").join(" ") + " ";
      const rule = VOCAB.find((r) => r.topics?.some((t) => TOPIC_PHRASE[t]) && r.re.test(text));
      topic = rule?.topics?.find((t) => TOPIC_PHRASE[t]);
      if (topic) break;
    }
    add(!!topic, `What did ${n.id} say about ${TOPIC_PHRASE[topic || ""]} most recently?`);
  }

  add(all.some((x) => !!x.q.capex), "How much capex are the hyperscalers guiding for this year?");
  add(anyTopic("cpo"), "When does co-packaged optics (CPO) reach volume, according to the graph?");
  add(anyText(/1\.6T/), "Who is winning 1.6T optical transceiver and DSP business?");
  add(
    nodes.some((n) => n.domains.includes("power") && n.quarterly_data.some((q) => /backlog/i.test(q.signal))),
    "Which power and cooling suppliers report record backlog from data centers?"
  );
  add(anyText(/trainium ?3/i), "What do suppliers say about AWS Trainium3?");
  add(anyText(/helios|mi450/i), "What is the latest on AMD MI450 Helios?");
  add(anyText(/tpu/i), "What does the graph say about Google TPU demand and its suppliers?");

  suggestCache = { nodes, out };
  return out;
}

// ── Union retrieval (the question plus its rewrites from /api/ask/rewrite) ──
//
// Step 1 of the Ask flow can now produce 2–4 extra phrasings of the question in
// the graph's own vocabulary ("HBM allocation", "capex guidance" …). Each
// phrasing is searched on its own with the ranking above, untouched, and the
// results are merged here. Nothing in this section changes a score.

const UNION_K = 15; // each REWRITTEN query contributes at most this many snippets ...
const UNION_MAX_SNIPPETS = 50; // ... the merged list stops here (the route accepts 60) ...
const UNION_MAX_CHARS = 18_000; // ... or here, in characters of snippet text (the route accepts 20,000)

/** Unique union of several string lists, keeping the first list's order first. */
function unionOf(lists: string[][]): string[] {
  const out: string[] = [];
  for (const list of lists) for (const x of list) if (!out.includes(x)) out.push(x);
  return out;
}

/**
 * Search the graph for several phrasings of one question and merge the results.
 *
 * `queries[0]` is the user's ORIGINAL question and runs with the default k
 * (DEFAULT_K); every other entry is a rewrite and runs with k = UNION_K. The
 * merged list keeps the original's snippets first, in their own order, then
 * appends what each rewrite found, query by query. A snippet two queries both
 * found is kept once — the key is `kind|company|target|label|text`. The union
 * stops at UNION_MAX_SNIPPETS snippets / UNION_MAX_CHARS characters of text; a
 * snippet that no longer fits is skipped and the next one is tried, the same
 * idiom retrieveWithMeta uses.
 *
 * `companies` / `chains` / `topics` / `terms` are the unique unions of every
 * query's parse, the original's first. `queries` lists the strings actually
 * searched: blank rewrites and repeats (case-insensitive, including a repeat of
 * the original) are dropped. Pure: no cache, no module state.
 */
export function retrieveUnion(
  queries: string[],
  nodes: VizNode[],
  links: VizLink[]
): RetrievalResult & { queries: string[] } {
  // Which strings to search: the original as-is, then each distinct non-blank rewrite.
  const searched: string[] = queries.length ? [queries[0]] : [];
  const seenQuery = new Set(searched.map((s) => s.trim().toLowerCase()));
  for (const q of queries.slice(1)) {
    const key = q.trim().toLowerCase();
    if (!key || seenQuery.has(key)) continue;
    seenQuery.add(key);
    searched.push(q.trim());
  }

  const results = searched.map((q, i) =>
    i === 0 ? retrieveWithMeta(q, nodes, links) : retrieveWithMeta(q, nodes, links, UNION_K)
  );

  // Merge the snippets, in order, within the caps.
  const seen = new Set<string>();
  const snippets: Snippet[] = [];
  let chars = 0;
  for (const r of results) {
    for (const s of r.snippets) {
      if (snippets.length >= UNION_MAX_SNIPPETS) break;
      const key = `${s.kind}|${s.company}|${s.target ?? ""}|${s.label}|${s.text}`;
      if (seen.has(key)) continue; // the same fact, found by two phrasings
      if (chars + s.text.length > UNION_MAX_CHARS) continue; // too long for what is left — try a shorter one
      seen.add(key);
      snippets.push(s);
      chars += s.text.length;
    }
  }

  return {
    snippets,
    companies: unionOf(results.map((r) => r.companies)),
    chains: unionOf(results.map((r) => r.chains)),
    topics: unionOf(results.map((r) => r.topics)),
    terms: unionOf(results.map((r) => r.terms)),
    queries: searched,
  };
}
