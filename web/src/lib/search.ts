// search.ts — typeahead matching for the company SearchBox.
//
// Pure functions, no React: build an index ONCE from the VizNode list, then rank
// a query against it on every keystroke. Kept separate from the component so the
// ranking can be unit-tested (web/scripts/test-search.mts) without rendering.
// Only type imports here, so Node can run that test on this file directly.
//
// Ranking, best first:
//   0  company name STARTS with the query        ("nvi"   -> NVIDIA)
//      or a Korean name starts with it           ("삼성"  -> Samsung, Samsung Electro-Mechanics)
//   1  a WORD inside the name starts with it     ("hynix" -> SK Hynix)
//      or a Korean name contains it              ("하이닉스" -> SK Hynix)
//   2  the name CONTAINS it anywhere             ("micro" -> Supermicro)
//   3  the ticker starts with it                 ("2382"  -> Quanta, "nvda" -> NVIDIA)
//   4  a WORD of a sector, sub-sector or layer name starts with it — the company is
//      filed under that component, so it makes it ("substrate" -> Ibiden, Unimicron)
//   5  a WORD of a product text starts with it — often a buyer that mentions it
//      ("memory package-substrate buyer" -> SK Hynix), so it comes after the makers.
//      Word starts, not any substring: "sic" finds SiC wafers, not every "ASIC".
//      A Korean component word is translated first ("기판" -> substrate, PCB).
// Ties inside one tier go to the better-connected node (higher degree), then A→Z.
//
// Every company whose products match also joins the query's COMPONENT GROUP — the
// companies that make what was typed. The SearchBox offers the group as one row that
// shows just those companies on the graph.

import type { VizNode } from "./types";

const HANGUL = /[가-힣]/; // one complete Korean syllable (가 … 힣)
// Japanese kana or a Chinese/Japanese character: such a query can only match a
// company's local-name aliases (company_names.json zh/ja names).
const KANA_HAN = /[\u3040-\u30ff\u3400-\u9fff]/;

// Lowercase, strip accents, collapse anything that is not a letter, digit or Korean
// syllable into a single space. "Résonac (Showa Denko)" -> "resonac showa denko".
export function normalize(s: string): string {
  return (s || "")
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "") // the accents NFD split off (U+0300..U+036F)
    .normalize("NFC") // NFD also splits Korean syllables into letters; put them back together
    .toLowerCase()
    .replace(/[^a-z0-9가-힣\u3040-\u30ff\u3400-\u9fff]+/g, " ")
    .trim();
}

// Common Korean component words -> the English words the product texts use.
// Search only: typing "기판" looks for "substrate" and "PCB" in the product texts.
export const KO_TERMS: Record<string, string[]> = {
  반도체: ["semiconductor"],
  칩: ["chip"],
  메모리: ["memory"],
  고대역폭메모리: ["hbm"],
  디램: ["dram"],
  낸드: ["nand"],
  웨이퍼: ["wafer"],
  실리콘: ["silicon"],
  기판: ["substrate", "pcb"],
  유리기판: ["glass substrate", "glass core"],
  패키징: ["packaging"],
  후공정: ["packaging", "osat"],
  본딩: ["bonding", "bonder"],
  파운드리: ["foundry"],
  장비: ["equipment"],
  소재: ["material"],
  식각: ["etch"],
  증착: ["deposition"],
  노광: ["lithography", "euv"],
  검사: ["inspection"],
  계측: ["metrology"],
  테스트: ["test"],
  감광액: ["photoresist"],
  포토레지스트: ["photoresist"],
  가스: ["gas"],
  특수가스: ["specialty gas"],
  화학: ["chemical"],
  슬러리: ["slurry"],
  소켓: ["socket"],
  프로브카드: ["probe card"],
  광: ["optical"],
  광모듈: ["transceiver", "optical module"],
  광통신: ["optical"],
  광섬유: ["fiber"],
  레이저: ["laser"],
  포토닉스: ["photonics"],
  실리콘포토닉스: ["silicon photonics"],
  케이블: ["cable"],
  전선: ["cable", "wire"],
  커넥터: ["connector"],
  스위치: ["switch"],
  서버: ["server"],
  랙: ["rack"],
  가속기: ["accelerator"],
  데이터센터: ["data center", "datacenter"],
  클라우드: ["cloud"],
  냉각: ["cooling", "thermal"],
  수냉: ["liquid cooling"],
  수랭: ["liquid cooling"],
  액침: ["immersion"],
  전력: ["power"],
  전력반도체: ["power semiconductor", "sic", "gan"],
  변압기: ["transformer"],
  배터리: ["battery"],
  원전: ["nuclear"],
  원자력: ["nuclear"],
  콘덴서: ["capacitor", "mlcc"],
  커패시터: ["capacitor", "mlcc"],
  적층세라믹콘덴서: ["mlcc"],
  동박: ["copper foil"],
  구리: ["copper"],
  탄화규소: ["sic"],
  질화갈륨: ["gan"],
  로봇: ["robot"],
  휴머노이드: ["humanoid"],
  드론: ["drone"],
  자율주행: ["autonomous"],
  카메라모듈: ["camera module"],
};

// The English words to look for when the query is Korean. A Korean word counts when it
// IS a dictionary word, when the user is still typing one ("유리" of "유리기판", 2+
// syllables), or when it CONTAINS one ("기판회사" -> 기판).
export function koreanTerms(q: string): string[] {
  const out: string[] = [];
  const words = Object.keys(KO_TERMS);
  for (const word of q.split(" ")) {
    if (!HANGUL.test(word)) continue;
    let keys = KO_TERMS[word] ? [word] : [];
    if (!keys.length && word.length >= 2) keys = words.filter((k) => k.startsWith(word));
    if (!keys.length) keys = words.filter((k) => k.length >= 2 && word.includes(k));
    for (const k of keys) for (const t of KO_TERMS[k]) if (!out.includes(t)) out.push(t);
  }
  return out;
}

export interface IndexedNode {
  node: VizNode;
  name: string; // normalized company name
  ticker: string; // normalized full ticker ("2382 tw")
  tickerBase: string; // ticker without its Yahoo suffix ("2382")
  koNames: string[]; // Korean names as written ("SK하이닉스") — for the "why it matched" hint
  ko: string[]; // the same, normalized without spaces ("sk하이닉스")
  products: string[]; // original product strings (for the hint)
  sectors: string[]; // original sector, sub-sector and layer/domain names
  text: string; // " " + normalized products + sectors — word starts are " " + word
  sectorText: string; // " " + normalized sectors only (tier 4)
}

export type MatchKind = "name" | "ko" | "ticker" | "product";

export interface SearchHit {
  node: VizNode;
  kind: MatchKind; // what the query matched — the row shows a hint for ko/product hits
  why: string | null; // the Korean name or product text that matched
  score: number; // tier number, lower = better
}

// The companies that make what was typed ("hbm" -> the 28 HBM makers).
export interface ComponentGroup {
  label: string; // the query as typed
  terms: string[]; // the English words searched for a Korean query ([] otherwise)
  ids: string[]; // every matching company, not only the rows shown
}

export interface SearchResult {
  hits: SearchHit[];
  group: ComponentGroup | null; // null unless 2+ companies make it
}

// `aliases` = Korean names per company ({ "SK Hynix": ["SK하이닉스", …] }), from
// /data/company_ko.json. Optional: without it Korean names simply never match.
export function buildSearchIndex(nodes: VizNode[], aliases: Record<string, string[]> = {}): IndexedNode[] {
  return nodes.map((node) => {
    const products: string[] = [];
    for (const p of node.products || []) {
      if (p.product && !products.includes(p.product)) products.push(p.product);
    }
    // Sectors, sub-sectors and the layer/domain names ("advanced_packaging" ->
    // "advanced packaging"), so "cooling", "CPO" or "thermal" find the companies filed there.
    const sectors: string[] = [];
    const add = (s?: string | null) => {
      if (s && !sectors.includes(s)) sectors.push(s);
    };
    (node.sectors || []).forEach(add);
    for (const p of node.products || []) add(p.sub_sector);
    for (const g of [...(node.layers || []), ...(node.domains || [])]) add(g.replace(/_/g, " "));
    const koNames = aliases[node.id] || [];
    const ticker = normalize(node.ticker || "");
    return {
      node,
      name: normalize(node.id),
      ticker,
      tickerBase: ticker.split(" ")[0] || "",
      koNames,
      ko: koNames.map((k) => normalize(k).replace(/ /g, "")),
      products,
      sectors,
      text: " " + normalize([...products, ...sectors].join(" | ")),
      sectorText: " " + normalize(sectors.join(" | ")),
    };
  });
}

export function searchNodes(index: IndexedNode[], query: string, limit = 10): SearchResult {
  const q = normalize(query);
  if (!q) return { hits: [], group: null };
  const korean = HANGUL.test(q);
  const qk = q.replace(/ /g, ""); // Korean names are compared without spaces
  // What to look for in the product texts: the query itself (2+ characters, so one
  // letter does not match every product), or the English words for a Korean query.
  const terms = korean ? koreanTerms(q) : q.length >= 2 ? [q] : [];
  const hits: SearchHit[] = [];
  const groupIds: string[] = [];
  for (const it of index) {
    const term = terms.find((t) => it.text.includes(" " + t)) || null;
    if (term) groupIds.push(it.node.id);
    let tier = -1;
    let kind: MatchKind = "name";
    let why: string | null = null;
    if (it.name.startsWith(q)) tier = 0;
    else if (it.name.includes(" " + q)) tier = 1;
    else if (it.name.includes(q)) tier = 2;
    else if ((korean || KANA_HAN.test(q)) && it.ko.some((k) => k.includes(qk))) {
      const i = it.ko.findIndex((k) => k.includes(qk));
      tier = it.ko[i].startsWith(qk) ? 0 : 1;
      kind = "ko";
      why = it.koNames[i];
    } else if (it.tickerBase && (it.tickerBase.startsWith(q) || it.ticker.startsWith(q))) {
      tier = 3;
      kind = "ticker";
    } else if (term) {
      tier = terms.some((t) => it.sectorText.includes(" " + t)) ? 4 : 5;
      kind = "product";
      // Find the human-readable text that matched, so the row can say why.
      const hasTerm = (s: string) => (" " + normalize(s)).includes(" " + term);
      why = it.products.find(hasTerm) || it.sectors.find(hasTerm) || null;
    }
    if (tier < 0) continue;
    hits.push({ node: it.node, kind, why, score: tier });
  }
  hits.sort(
    (a, b) =>
      a.score - b.score ||
      b.node.degree - a.node.degree ||
      a.node.id.localeCompare(b.node.id)
  );
  const group = groupIds.length >= 2 ? { label: query.trim(), terms: korean ? terms : [], ids: groupIds } : null;
  return { hits: hits.slice(0, limit), group };
}

// ── Recent picks (localStorage) ────────────────────────────────────────────
// The last 8 companies the user picked, newest first. Every localStorage call is
// wrapped in try/catch: it throws in private windows / SSR / when storage is full,
// and a search box must never crash the page over a nicety.

const RECENT_KEY = "aisc.recent";
const RECENT_MAX = 8;

export function loadRecent(): string[] {
  try {
    const raw = localStorage.getItem(RECENT_KEY);
    const arr = raw ? JSON.parse(raw) : [];
    return Array.isArray(arr)
      ? arr.filter((x): x is string => typeof x === "string").slice(0, RECENT_MAX)
      : [];
  } catch {
    return [];
  }
}

export function pushRecent(id: string): string[] {
  const next = [id, ...loadRecent().filter((x) => x !== id)].slice(0, RECENT_MAX);
  try {
    localStorage.setItem(RECENT_KEY, JSON.stringify(next));
  } catch {}
  return next;
}
