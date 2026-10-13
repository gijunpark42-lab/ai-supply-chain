// top.ts — the server side of the /news terminal's Top News tab: the day's
// important stories (politics, the economy, markets, big companies) for a US
// investor, from Reuters and the Financial Times, as cards in the style of the
// SAVE app (user, 2026-10-13).
//
// Reuters closed its RSS in 2020, so its stories come through Google News and
// Finnhub; the FT's own section RSS feeds bring each story's standfirst, which
// the card shows as its one-line summary. Gemini (free tier, lib/gemini.ts)
// rates every story 1-5 and files it under a category — in the ingest job, not
// on request; the tab keeps 4 and up. Until anything is rated, every story shows.
//
// DISPLAY ONLY, like lib/news.ts. Server-only.

import { getCache } from "@vercel/functions";
import { generate } from "./gemini";
import { finnhub, googleNews, makeItem, rssField, tickerOf, type NewsFeed, type NewsItem } from "./news";

const DAY_MS = 24 * 3600_000;
const UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36";
const MIN_RANK = 4; // what the tab shows
export const CATEGORIES = ["Politics", "Economy", "Markets", "Companies", "Tech", "Energy", "Other"];

// The FT front page plus its news sections.
const FT_RSS = ["", "world", "companies", "markets", "global-economy", "technology"].map(
  (s) => `https://www.ft.com/${s}?format=rss`
);
// Reuters and the FT through Google News (the FT search reaches past its RSS's 25 a section).
const GN_SEARCHES = ["site:reuters.com/world", "site:reuters.com/business", "site:reuters.com/markets", "site:reuters.com/technology", "site:ft.com"];

async function ftRss(url: string): Promise<NewsItem[] | null> {
  try {
    const res = await fetch(url, { headers: { "User-Agent": UA }, cache: "no-store", signal: AbortSignal.timeout(10_000) });
    if (!res.ok) return null;
    const xml = await res.text();
    return xml
      .split("<item>")
      .slice(1)
      .map((b) =>
        makeItem("ft", rssField(b, "link"), Date.parse(rssField(b, "pubDate")), rssField(b, "title"), "Financial Times", rssField(b, "description"), [])
      )
      .filter((x): x is NewsItem => x != null);
  } catch {
    return null;
  }
}

// ── Ratings ───────────────────────────────────────────────────────────────
// Written by the ingest job (/api/news/ingest, Vercel Cron every 5 minutes) and
// kept in Vercel's Runtime Cache, so /api/top never waits on Gemini and a busy
// Gemini ("high demand" 503s) only delays a story's rating to the next run.

const RATINGS_KEY = "news-ratings-v1";
const KEEP_MS = 3 * 24 * 3600_000;
const BATCH = 100; // stories per Gemini call
const CALLS_PER_RUN = 3;
type Ratings = Record<string, [rank: number, category: string, at: number]>;

async function loadRatings(): Promise<Ratings> {
  try {
    return ((await getCache().get(RATINGS_KEY)) as Ratings | undefined) ?? {};
  } catch {
    return {};
  }
}

const RATING_RULES =
  "You are the editor of a markets news terminal for US investors. For each story (headline, maybe a " +
  "standfirst after ' | '), rate how much it matters to a US investor today — US stocks, the Fed, Treasuries, " +
  "the dollar, US politics and policy, and events abroad that move them — 1-5: 5 = market-moving or a major " +
  "political / geopolitical event (Fed decision, war escalation, election result, tariffs, sanctions, " +
  "mega-deal, big earnings shock); 4 = significant political, economic or large-company news; " +
  "3 = notable; 2 = minor or regional; 1 = lifestyle, sport, culture, puzzles, podcasts. Be strict: of a " +
  "typical day's 300 stories about 30 rate 4 and 5-10 rate 5. " +
  `Give each one category from: ${CATEGORIES.join(", ")}. ` +
  'Also say whether it is "news" (a report of something that happened or was announced) or "view" ' +
  "(column, opinion, analysis, explainer, feature, newsletter). " +
  'Return a JSON object with the same keys, each value [rank, "Category", "news" or "view"].';

/** One ingest run's share: rate the stories that have no rating yet. */
export async function rateNewStories(): Promise<{ rated: number; waiting: number }> {
  const { all } = await getCandidates();
  const ratings = await loadRatings();
  const todo = all.filter((it) => !ratings[it.id]);
  let rated = 0;
  let refused = 0;
  for (let i = 0; i < Math.min(todo.length, BATCH * CALLS_PER_RUN); i += BATCH) {
    const batch = todo.slice(i, i + BATCH);
    const out = await generate(
      RATING_RULES,
      JSON.stringify(Object.fromEntries(batch.map((it, n) => [n, it.summary ? `${it.title} | ${it.summary}` : it.title]))),
      { maxTokens: 4096, json: true }
    );
    if (!out) {
      if (++refused >= 2) break; // the free-tier limit, not a passing 503: next run
      continue;
    }
    refused = 0;
    try {
      const obj = JSON.parse(out);
      batch.forEach((it, n) => {
        const v = obj?.[n];
        // Columns and analysis stay out of Top News whatever their rank: hard news only.
        if (Array.isArray(v) && typeof v[0] === "number") {
          ratings[it.id] = [v[2] === "view" ? 0 : v[0], CATEGORIES.includes(v[1]) ? v[1] : "Other", Date.now()];
          rated++;
        }
      });
    } catch {
      console.warn(`[news] rating answer was not JSON: ${out.slice(0, 120)}`);
    }
  }
  const cutoff = Date.now() - KEEP_MS;
  for (const id of Object.keys(ratings)) if (ratings[id][2] < cutoff) delete ratings[id];
  if (rated) await getCache().set(RATINGS_KEY, ratings, { ttl: KEEP_MS / 1000, name: "news ratings" });
  return { rated, waiting: todo.length - rated };
}

// ── The stories ───────────────────────────────────────────────────────────

interface Candidates {
  all: NewsItem[];
  ftFailed: number;
  googleFailed: number;
}

// Shared by /api/top and the ingest job; a warm instance keeps it a minute.
const MEMO_MS = 60_000;
let memo: { at: number; value: Promise<Candidates> } | null = null;

function getCandidates(): Promise<Candidates> {
  if (memo && Date.now() - memo.at < MEMO_MS) return memo.value;
  const value = fetchCandidates();
  memo = { at: Date.now(), value };
  value.catch(() => (memo = null));
  return value;
}

async function fetchCandidates(): Promise<Candidates> {
  const now = Date.now();
  const since = now - DAY_MS;
  const [ft, google, finn] = await Promise.all([
    Promise.all(FT_RSS.map(ftRss)),
    Promise.all(GN_SEARCHES.map((q) => googleNews(q))),
    finnhub(),
  ]);
  const reutersFinn = (finn || []).filter((it) => /reuters/i.test(it.source));

  // One card per story: the FT's own copy (with its standfirst) wins, then
  // Finnhub's Reuters copy (with its blurb), then Google News.
  const byKey = new Map<string, NewsItem>();
  for (const it of [...ft.flatMap((x) => x || []), ...reutersFinn, ...google.flatMap((x) => x || [])]) {
    if (it.time < since || it.time > now + 600_000) continue;
    if (!/reuters|financial times/i.test(it.source)) continue;
    const key = it.title.toLowerCase().replace(/[^\p{L}\p{N}]+/gu, "").slice(0, 90);
    if (!byKey.has(key)) byKey.set(key, it);
  }
  const all = [...byKey.values()];
  for (const it of all) {
    if (/reuters/i.test(it.source)) it.source = "Reuters";
    // Finnhub's Reuters "summary" is often the headline again.
    if (it.summary && it.title.toLowerCase().startsWith(it.summary.toLowerCase().slice(0, 40))) it.summary = "";
  }
  return {
    all,
    ftFailed: ft.filter((x) => x == null).length,
    googleFailed: google.filter((x) => x == null).length,
  };
}

/** The Top News tab: rated stories of rank 4 and up. Until the first ratings
 *  exist (a fresh deploy, or no Gemini key) every story shows, unrated. */
export async function getTopFeed(): Promise<NewsFeed> {
  const [{ all, ftFailed, googleFailed }, ratings] = await Promise.all([getCandidates(), loadRatings()]);
  const anyRated = all.some((it) => ratings[it.id]);
  const items = all
    .map((it) => {
      const r = ratings[it.id];
      return r ? { ...it, rank: r[0], category: r[1] } : it;
    })
    .filter((it) => (anyRated ? (it.rank ?? 0) >= MIN_RANK : true))
    .sort((a, b) => b.time - a.time);

  const tickers: Record<string, string | null> = {};
  for (const it of items) for (const id of it.companies) tickers[id] = tickerOf(id);
  const count = (pred: (it: NewsItem) => boolean) => items.filter(pred).length;
  return {
    at: Date.now(),
    items,
    tickers,
    feeds: [
      { name: "google", label: "Reuters", count: count((it) => it.source === "Reuters"), failed: googleFailed },
      { name: "ft", label: "FT", count: count((it) => it.source === "Financial Times"), failed: ftFailed },
    ],
  };
}
