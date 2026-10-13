// filings.ts — the server side of the /news terminal's Filings tab: the last day of
// regulatory filings by map companies from DART (Korea), EDINET (Japan) and SEC
// EDGAR (US-listed companies, foreign ADRs included).
//
// DISPLAY ONLY, like lib/news.ts: it reads the registries and writes nothing, and
// the enrich pipeline (dart.py, edinet.py, edgar_pull.py) never reads it.
//
// Server-only (API keys from process.env).

import { createHash } from "node:crypto";
import { getCache } from "@vercel/functions";
import { toEnglish } from "./gemini";
import { mapNodes, pool, tickerOf, type NewsFeed, type NewsItem } from "./news";

const DAY_MS = 24 * 3600_000;
const KST = 9; // DART and EDINET date their filings in Korea / Japan time
const ET = -4; // EDGAR in US Eastern (summer time; winter is an hour off — fine for a date window)
// SEC asks every client to name itself with a contact address.
export const SEC_UA = process.env.EDGAR_USER_AGENT?.trim() || "earnings-ai research gijunpark42@gmail.com";

// Insider-trade notices: dozens a day for the big names, and not news.
const SEC_SKIP = new Set(["3", "4", "5", "3/A", "4/A", "5/A", "144", "144/A"]);
const DART_SKIP = /임원ㆍ주요주주특정증권등(소유상황|거래계획)보고서/;
// The 8-K items worth naming in the headline.
const ITEMS_8K: Record<string, string> = {
  "1.01": "Material agreement",
  "1.02": "Agreement ended",
  "2.01": "Acquisition / disposal",
  "2.02": "Results",
  "2.03": "New debt",
  "2.05": "Restructuring",
  "2.06": "Impairment",
  "3.02": "Share sale",
  "5.02": "Officer / director change",
  "5.07": "Shareholder vote",
  "7.01": "Reg FD",
  "8.01": "Other events",
};

async function getJson(url: string, headers: Record<string, string> = {}): Promise<any> {
  try {
    const res = await fetch(url, {
      headers: { "User-Agent": "Mozilla/5.0", ...headers },
      cache: "no-store",
      signal: AbortSignal.timeout(15_000),
    });
    return res.ok ? await res.json() : null;
  } catch {
    return null;
  }
}

const hashId = (url: string) => createHash("sha1").update(url).digest("hex").slice(0, 12);
// The calendar date ("2026-10-13") in a market `offsetH` hours from UTC.
const dateIn = (ms: number, offsetH: number) => new Date(ms + offsetH * 3600_000).toISOString().slice(0, 10);
// Where a date-only filing sorts: the end of its market day, never later than now.
const endOfDay = (day: string, offsetH: number, now: number) =>
  Math.min(now, Date.parse(`${day}T23:59:59Z`) - offsetH * 3600_000);

function item(
  feed: NewsItem["feed"],
  source: string,
  url: string,
  time: number,
  title: string,
  company: string,
  extra: Partial<NewsItem> = {}
): NewsItem {
  return { id: hashId(url), time, title, source, url, summary: "", companies: [company], tickers: [], feed, ...extra };
}

// ── Filing times ──────────────────────────────────────────────────────────
// DART's list API and EDGAR's search give dates only. DART's "today" RSS gives
// its latest 50 filings with the minute they came in: the ingest job (every 5
// minutes, lib/digests.ts) notes them here, receipt no. → time. EDGAR keeps each
// filing's acceptance time in its index headers, read once per filing.
const DART_TIMES_KEY = "dart-times-v1";
const KEEP_MS = 3 * DAY_MS;

async function loadDartTimes(): Promise<Record<string, number>> {
  try {
    return ((await getCache().get(DART_TIMES_KEY)) as Record<string, number> | undefined) ?? {};
  } catch {
    return {};
  }
}

/** Ingest job: note when DART's latest 50 filings came in. */
export async function recordDartTimes(): Promise<number> {
  let xml = "";
  try {
    const res = await fetch("https://dart.fss.or.kr/api/todayRSS.xml", {
      headers: { "User-Agent": "Mozilla/5.0" },
      cache: "no-store",
      signal: AbortSignal.timeout(10_000),
    });
    if (res.ok) xml = await res.text();
  } catch {
    // DART unreachable: next run
  }
  const times = await loadDartTimes();
  let added = 0;
  for (const b of xml.split("<item>").slice(1)) {
    const rcp = b.match(/rcpNo=(\d+)/)?.[1];
    const t = Date.parse(b.match(/<pubDate>([^<]+)<\/pubDate>/)?.[1] || "");
    if (rcp && Number.isFinite(t) && times[rcp] !== t) {
      times[rcp] = t;
      added++;
    }
  }
  const cutoff = Date.now() - KEEP_MS;
  for (const k of Object.keys(times)) if (times[k] < cutoff) delete times[k];
  if (added) await getCache().set(DART_TIMES_KEY, times, { ttl: KEEP_MS / 1000, name: "dart filing times" });
  return added;
}

const secTimes = new Map<string, number>(); // accession no. → acceptance time, kept while warm

/** "20261009160849", New York time (EDGAR's clock) → epoch ms. */
function newYorkToMs(s: string): number {
  const [y, mo, d, h, mi, se] = [0, 4, 6, 8, 10, 12].map((i, k) => Number(s.slice(i, k ? i + 2 : 4)));
  const guess = Date.UTC(y, mo - 1, d, h, mi, se);
  // Read the guess back on New York's clock: the difference is its UTC offset that day.
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York",
    hourCycle: "h23",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).formatToParts(guess);
  const get = (type: string) => Number(parts.find((p) => p.type === type)?.value);
  return guess + (guess - Date.UTC(get("year"), get("month") - 1, get("day"), get("hour"), get("minute"), get("second")));
}

async function secAcceptance(url: string): Promise<number | null> {
  const m = url.match(/\/data\/(\d+)\/(\d{18})\//);
  if (!m) return null;
  const [, cik, acc] = m;
  if (secTimes.has(acc)) return secTimes.get(acc)!;
  const dashed = `${acc.slice(0, 10)}-${acc.slice(10, 12)}-${acc.slice(12)}`;
  try {
    const res = await fetch(`https://www.sec.gov/Archives/edgar/data/${cik}/${acc}/${dashed}-index-headers.html`, {
      headers: { "User-Agent": SEC_UA },
      cache: "no-store",
      signal: AbortSignal.timeout(10_000),
    });
    const stamp = res.ok ? (await res.text()).match(/ACCEPTANCE-DATETIME>\s*(\d{14})/)?.[1] : undefined;
    if (!stamp) return null;
    const t = newYorkToMs(stamp);
    secTimes.set(acc, t);
    return t;
  } catch {
    return null;
  }
}

// ── DART (Korea) ──────────────────────────────────────────────────────────
// The list API dates filings only, so it is asked for yesterday's and today's
// Korean dates; filings whose minute the RSS gave are then kept to the last 24 h.
async function dart(now: number): Promise<NewsItem[] | null> {
  const key = process.env.DART_API_KEY?.trim();
  if (!key) return [];
  const byCode = new Map<string, string>(); // "000660" → "SK Hynix"
  for (const n of mapNodes()) {
    const m = n.country === "KR" ? n.ticker?.match(/^(\d{6})(\.K[SQ])?$/) : null;
    if (m) byCode.set(m[1], n.id);
  }
  const from = dateIn(now - DAY_MS, KST).replace(/-/g, "");
  const to = dateIn(now, KST).replace(/-/g, "");
  const page = (no: number) =>
    getJson(`https://opendart.fss.or.kr/api/list.json?crtfc_key=${key}&bgn_de=${from}&end_de=${to}&page_count=100&page_no=${no}`);
  const first = await page(1);
  if (first?.status === "013") return []; // no filings at all
  if (first?.status !== "000") return null;
  // Every filing in Korea that day (~500-1,000), 100 a page; ours are picked out below.
  const rest = await pool(
    Array.from({ length: Math.min((first.total_page || 1) - 1, 20) }, (_, i) => () => page(i + 2)),
    4
  );
  const rows = [first, ...rest]
    .flatMap((p) => p?.list || [])
    .filter((r: any) => byCode.has(r.stock_code) && !DART_SKIP.test(r.report_nm))
    .sort((a: any, b: any) => b.rcept_no.localeCompare(a.rcept_no)); // receipt order within a day
  const times = await loadDartTimes();
  const items = rows.map((r: any, i: number) => {
    const day = `${r.rcept_dt.slice(0, 4)}-${r.rcept_dt.slice(4, 6)}-${r.rcept_dt.slice(6, 8)}`;
    const url = `https://dart.fss.or.kr/dsaf001/main.do?rcpNo=${r.rcept_no}`;
    const company = byCode.get(r.stock_code)!;
    const report = String(r.report_nm).replace(/\s+/g, " ").trim();
    // The map's English name; buildFeed translates the report name.
    const title = `${company} — ${report}`;
    const original = `${r.corp_name} — ${report}`;
    const time = times[r.rcept_no];
    return time
      ? item("dart", "DART", url, time, title, company, { original })
      : item("dart", "DART", url, endOfDay(day, KST, now) - i, title, company, { day, original });
  });
  return items.filter((it: NewsItem) => it.day || it.time >= now - DAY_MS);
}

// ── EDINET (Japan) ────────────────────────────────────────────────────────
async function edinet(now: number): Promise<NewsItem[] | null> {
  const key = process.env.EDINET_API_KEY?.trim();
  if (!key) return [];
  const bySec = new Map<string, string>(); // EDINET's 5-digit code "80350" → "Tokyo Electron"
  for (const n of mapNodes()) {
    const m = n.country === "JP" ? n.ticker?.match(/^([0-9A-Z]{4})(\.T)?$/) : null;
    if (m) bySec.set(m[1] + "0", n.id);
  }
  const days = [...new Set([dateIn(now - DAY_MS, KST), dateIn(now, KST)])];
  const lists = await Promise.all(
    days.map((d) => getJson(`https://api.edinet-fsa.go.jp/api/v2/documents.json?date=${d}&type=2&Subscription-Key=${key}`))
  );
  if (lists.every((l) => !Array.isArray(l?.results))) return null;
  const out: NewsItem[] = [];
  for (const r of lists.flatMap((l) => l?.results || [])) {
    const company = r.secCode && bySec.get(r.secCode);
    if (!company || !r.docID || r.withdrawalStatus === "1") continue;
    const time = Date.parse(`${String(r.submitDateTime).replace(" ", "T")}:00+09:00`); // "2026-10-13 09:02" JST
    if (!(time >= now - DAY_MS)) continue;
    const url = `https://disclosure2.edinet-fsa.go.jp/WZEK0040.aspx?${r.docID}`;
    out.push(
      item("edinet", "EDINET", url, time, `${company} — ${r.docDescription}`, company, {
        original: `${r.filerName} — ${r.docDescription}`,
      })
    );
  }
  return out;
}

// ── SEC EDGAR (US) ────────────────────────────────────────────────────────
// EDGAR full-text search takes every map company's CIK in one query; it dates
// filings only, so each one's acceptance time comes from its index headers.
let cikMemo: Promise<Map<number, string>> | null = null;
function mapCiks(): Promise<Map<number, string>> {
  cikMemo ??= getJson("https://www.sec.gov/files/company_tickers.json", { "User-Agent": SEC_UA }).then((j) => {
    const cikOf = new Map<string, number>();
    for (const row of Object.values<any>(j || {})) cikOf.set(String(row.ticker).toUpperCase(), row.cik_str);
    const out = new Map<number, string>(); // CIK → node id
    for (const n of mapNodes()) {
      const cik = n.ticker && /^[A-Z][A-Z.-]{0,5}$/.test(n.ticker) ? cikOf.get(n.ticker.replace(".", "-")) : undefined;
      if (cik) out.set(cik, n.id);
    }
    if (!out.size) cikMemo = null; // SEC refused: try again next time
    return out;
  });
  return cikMemo;
}

async function sec(now: number): Promise<NewsItem[] | null> {
  const byCik = await mapCiks();
  if (!byCik.size) return null;
  const ciks = [...byCik.keys()].map((c) => String(c).padStart(10, "0")).join(",");
  const base =
    `https://efts.sec.gov/LATEST/search-index?dateRange=custom&startdt=${dateIn(now - DAY_MS, ET)}` +
    `&enddt=${dateIn(now, ET)}&ciks=${ciks}`;
  const hits: any[] = [];
  for (let from = 0; from < 500; from += 100) {
    const j = await getJson(`${base}&from=${from}`, { "User-Agent": SEC_UA });
    if (!j?.hits) {
      if (!from) return null;
      break;
    }
    hits.push(...j.hits.hits);
    if (hits.length >= j.hits.total.value || !j.hits.hits.length) break;
  }
  const filings = collect();
  await pool(
    filings.map((it) => async () => {
      const t = await secAcceptance(it.url);
      if (t) [it.time, it.day] = [t, undefined];
    }),
    4
  );
  return filings.filter((it) => it.day || it.time >= now - DAY_MS);

  function collect(): NewsItem[] {
    // A filing comes back once per document; keep one per filing, preferring the
    // press release (EX-99) — it reads better and summarizes better than the cover.
    const byFiling = new Map<string, any>();
    for (const h of hits) {
      const s = h._source;
      if (SEC_SKIP.has(s.form)) continue;
      const adsh = String(h._id).split(":")[0];
      const seen = byFiling.get(adsh);
      const rank = (x: any) => (/^EX-99/.test(x._source.file_type) ? 2 : x._source.file_type === x._source.form ? 1 : 0);
      if (!seen || rank(h) > rank(seen)) byFiling.set(adsh, h);
    }
    return [...byFiling.values()]
      .sort((a, b) => b._source.file_date.localeCompare(a._source.file_date) || b._id.localeCompare(a._id))
      .map((h, i) => {
        const s = h._source;
        const [adsh, file] = String(h._id).split(":");
        const cik = (s.ciks as string[]).map(Number).find((c) => byCik.has(c))!;
        const items = ((s.items as string[]) || []).map((x) => ITEMS_8K[x]).filter(Boolean);
        const title = `${byCik.get(cik)} — ${s.form}${items.length ? ` · ${items.join(", ")}` : ""}`;
        const url = `https://www.sec.gov/Archives/edgar/data/${cik}/${adsh.replace(/-/g, "")}/${file}`;
        return item("sec", "SEC", url, endOfDay(s.file_date, ET, now) - i, title, byCik.get(cik)!, { day: s.file_date });
      });
  }
}

// ── The feed ──────────────────────────────────────────────────────────────
// /api/filings is CDN-cached 10 minutes (DART allows 20,000 calls a day, shared
// with the nightly enrich); a warm instance also keeps its last answer that long.
const MEMO_MS = 10 * 60_000;
let memo: { at: number; feed: Promise<NewsFeed> } | null = null;

export function getFilingsFeed(): Promise<NewsFeed> {
  if (memo && Date.now() - memo.at < MEMO_MS) return memo.feed;
  const feed = buildFeed();
  memo = { at: Date.now(), feed };
  feed.catch(() => (memo = null));
  return feed;
}

async function buildFeed(): Promise<NewsFeed> {
  const now = Date.now();
  const [d, e, s] = await Promise.all([dart(now), edinet(now), sec(now)]);
  const items = [...(d || []), ...(e || []), ...(s || [])].sort((a, b) => b.time - a.time);
  // English titles (user, 2026-10-13): "LS Electric — 단일판매ㆍ공급계약체결" → "… — Single sales /
  // supply contract". Report names repeat day to day, so most come from the warm cache.
  const english = await toEnglish(items.map((it) => it.title));
  for (const it of items) it.title = english.get(it.title) ?? it.title;
  const tickers: Record<string, string | null> = {};
  for (const it of items) for (const id of it.companies) tickers[id] = tickerOf(id);
  return {
    at: now,
    items,
    tickers,
    feeds: [
      { name: "dart", count: d?.length ?? 0, failed: d ? 0 : 1 },
      { name: "edinet", count: e?.length ?? 0, failed: e ? 0 : 1 },
      { name: "sec", count: s?.length ?? 0, failed: s ? 0 : 1 },
    ],
  };
}
