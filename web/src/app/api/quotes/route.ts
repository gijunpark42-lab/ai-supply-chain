// /api/quotes — BATCH quote proxy for the Picks tab. /api/quote returns one
// symbol with four chart ranges (heavy); this returns just the last price for
// many symbols at once, which is all a tracking table needs.
//
// Yahoo's /v7/finance/quote batch endpoint now demands a crumb+cookie, so we
// fetch each symbol's 1-day chart in parallel and read `meta` — the same source
// /api/quote already trusts. `meta.regularMarketPrice` is live during the
// session and settles to the official close after it.

import { NextRequest, NextResponse } from "next/server";

export const runtime = "nodejs";
export const revalidate = 0; // this route decides its own caching (see CACHE_MS)

const CACHE_MS = 20_000; // serve a memo for 20 s so a page refresh is not 18 fetches
const MAX_SYMBOLS = 40;

interface Quote {
  price: number | null;
  prev_close: number | null; // previous session's close → the day % change
  day_pct: number | null;
  currency: string | null;
  market_state: string | null; // REGULAR / CLOSED / PRE / POST
  quote_time: number | null; // epoch ms of the last trade Yahoo reported
}

// Memo lives on the warm lambda; a cold start just refetches.
const memo = new Map<string, { at: number; q: Quote }>();

async function fetchQuote(symbol: string): Promise<Quote | null> {
  const url =
    `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(symbol)}` +
    `?range=1d&interval=5m`;
  try {
    const res = await fetch(url, {
      headers: { "User-Agent": "Mozilla/5.0 (compatible; supply-chain-app/1.0)" },
      cache: "no-store",
    });
    if (!res.ok) return null;
    const meta = (await res.json())?.chart?.result?.[0]?.meta;
    if (!meta) return null;

    const price = meta.regularMarketPrice ?? null;
    // chartPreviousClose on a 1d range IS the prior session's close.
    const prev = meta.previousClose ?? meta.chartPreviousClose ?? null;
    return {
      price,
      prev_close: prev,
      day_pct:
        price != null && prev ? Math.round(((price - prev) / prev) * 10000) / 100 : null,
      currency: meta.currency ?? null,
      market_state: meta.marketState ?? null,
      quote_time: meta.regularMarketTime ? meta.regularMarketTime * 1000 : null,
    };
  } catch {
    return null;
  }
}

export async function GET(req: NextRequest) {
  const raw = req.nextUrl.searchParams.get("symbols") || "";
  const symbols = Array.from(
    new Set(
      raw
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean)
    )
  ).slice(0, MAX_SYMBOLS);

  if (symbols.length === 0)
    return NextResponse.json({ error: "no symbols" }, { status: 400 });

  const now = Date.now();
  const out: Record<string, Quote> = {};
  const misses: string[] = [];
  for (const s of symbols) {
    const hit = memo.get(s);
    if (hit && now - hit.at < CACHE_MS) out[s] = hit.q;
    else misses.push(s);
  }

  const fetched = await Promise.all(misses.map(fetchQuote));
  misses.forEach((s, i) => {
    const q = fetched[i];
    if (!q) return;
    memo.set(s, { at: now, q });
    out[s] = q;
  });

  return NextResponse.json(
    { quotes: out, as_of: new Date().toISOString() },
    { headers: { "Cache-Control": "no-store" } }
  );
}
