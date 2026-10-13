// digests.ts — summaries written ahead of time, so the /news terminal shows each
// story's summary in the list and on click without waiting (user, 2026-10-13).
//
// The ingest job (/api/news/ingest, a Vercel Cron every 5 minutes) rates the new
// Top News stories (lib/top.ts), then looks for new News / Filings items that
// need a summary and summarizes them five to a Gemini call
// (lib/newsSummary.ts summarizeMany) and stores them in Vercel's Runtime Cache
// under one key; /api/news and /api/filings attach them to their items.
//
// Which items: Google News stories and filings. Polygon and Finnhub stories carry
// their publisher's own summary, and Reuters / FT pages refuse to be read, so a
// summary of those would only restate the headline.
//
// Budget: ~250 items a day → ~50 Gemini calls a day for summaries, plus one
// rating call per run that finds new Top News stories (≤ 288 a day): ~350 a day,
// at most ~9 a run, well inside the free tier (~15 a minute, ~1,000 a day).
//
// Display only, like the rest of the terminal. Server-only.

import { getCache } from "@vercel/functions";
import { getFilingsFeed, recordDartTimes } from "./filings";
import { getNewsFeed, tickerOf, type Digest, type NewsFeed, type NewsItem } from "./news";
import { summarizeMany } from "./newsSummary";
import { rateNewStories } from "./top";

const KEY = "news-digests-v1"; // one entry: { item id → digest + when written }
const KEEP_MS = 3 * 24 * 3600_000; // feeds show a day; keep three
const PER_CALL = 5; // sources per Gemini call
const CALLS_PER_RUN = 6; // ≤ 30 new summaries per run, sequential: well under the per-minute limit

type Store = Record<string, Digest & { at: number }>;

async function load(): Promise<Store> {
  try {
    return ((await getCache().get(KEY)) as Store | undefined) ?? {};
  } catch {
    return {};
  }
}

/** Does this item get a pre-written summary? */
function needsDigest(it: NewsItem): boolean {
  if (it.feed === "dart" || it.feed === "edinet" || it.feed === "sec") return true;
  return it.feed === "google" && !/reuters|financial times|bloomberg|wall street journal/i.test(it.source);
}

/** The feed with every stored summary attached (and its companies' tickers). */
export async function withDigests(feed: NewsFeed): Promise<NewsFeed> {
  const store = await load();
  const tickers = { ...feed.tickers };
  const items = feed.items.map((it) => {
    const d = store[it.id];
    if (!d) return it;
    for (const id of d.companies) tickers[id] ??= tickerOf(id);
    return { ...it, digest: { summary: d.summary, url: d.url, companies: d.companies, others: d.others } };
  });
  return { ...feed, items, tickers };
}

/** One ingest run: note DART filing times (lib/filings.ts), rate the new Top News
 *  stories (lib/top.ts), then summarize the newest items that have no summary yet. */
export async function ingest() {
  const dartTimes = await recordDartTimes();
  const top = await rateNewStories();
  const digests = await summarizeNew();
  return { dartTimes, top, digests };
}

async function summarizeNew(): Promise<{ added: number; waiting: number; stored: number }> {
  const [news, filings] = await Promise.all([getNewsFeed(), getFilingsFeed()]);
  const store = await load();
  const todo = [...news.items, ...filings.items]
    .filter((it) => needsDigest(it) && !store[it.id])
    .sort((a, b) => b.time - a.time);

  let added = 0;
  let refused = 0;
  for (let i = 0; i < Math.min(todo.length, PER_CALL * CALLS_PER_RUN); i += PER_CALL) {
    const batch = todo.slice(i, i + PER_CALL);
    const out = await summarizeMany(batch.map((it) => ({ url: it.url, title: it.title, blurb: it.summary.slice(0, 1500) })));
    // Gemini refused. One refusal is often a passing "high demand" 503; two in a row
    // is the free-tier limit — stop, and the next run picks these up.
    if (out.every((d) => d == null)) {
      if (++refused >= 2) break;
      continue;
    }
    refused = 0;
    out.forEach((d, k) => {
      if (d) {
        store[batch[k].id] = { ...d, at: Date.now() };
        added++;
      }
    });
  }

  const cutoff = Date.now() - KEEP_MS;
  for (const id of Object.keys(store)) if (store[id].at < cutoff) delete store[id];
  if (added) await getCache().set(KEY, store, { ttl: KEEP_MS / 1000, name: "news digests" });
  return { added, waiting: todo.length - added, stored: Object.keys(store).length };
}
