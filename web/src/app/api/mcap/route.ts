// /api/mcap — live market cap for a node's listing, in its trading currency and in
// USD at the live FX rate. ADRs / NY-registry lines are valued on the HOME listing
// (TSM → 2330.TW, see HOME_LISTING in lib/yahoo.ts). The panel polls this every 30 s.

import { NextRequest, NextResponse } from "next/server";
import { homeSymbol, yahooSymbol } from "@/lib/yahoo";
import { yahooMarketCap } from "@/lib/fundamentals";

export const runtime = "nodejs";

// Units of `currency` per 1 USD, from Yahoo's "<CUR>=X" pair (KRW=X → 1338.09).
async function perUsd(currency: string): Promise<number | null> {
  try {
    const res = await fetch(
      `https://query1.finance.yahoo.com/v8/finance/chart/${currency}=X?range=1d&interval=5m`,
      {
        headers: { "User-Agent": "Mozilla/5.0 (compatible; supply-chain-app/1.0)" },
        next: { revalidate: 60 },
      }
    );
    if (!res.ok) return null;
    const rate = (await res.json())?.chart?.result?.[0]?.meta?.regularMarketPrice;
    return typeof rate === "number" && rate > 0 ? rate : null;
  } catch {
    return null;
  }
}

export async function GET(req: NextRequest) {
  const params = req.nextUrl.searchParams;
  const listed = yahooSymbol(params.get("ticker") || "", params.get("exchange"));
  if (!listed) return NextResponse.json({ error: "no symbol" }, { status: 400 });

  const home = homeSymbol(listed);
  let symbol = home;
  let q = await yahooMarketCap(symbol);
  // Taiwan OTC names stored as ".TW" live under ".TWO" on Yahoo (same retry as /api/quote).
  if (!q && symbol.endsWith(".TW")) {
    symbol = symbol.replace(/\.TW$/, ".TWO");
    q = await yahooMarketCap(symbol);
  }
  if (!q) return NextResponse.json({ error: "no data" }, { status: 404 });

  // LSE prices are in pence (GBp), but Yahoo's market cap is already in pounds.
  const currency = q.currency === "GBp" ? "GBP" : q.currency;
  const fx = currency === "USD" ? 1 : await perUsd(currency);

  return NextResponse.json({
    symbol, // the listing the cap is computed on
    adr: home !== listed ? listed : null, // the US line we looked through, if any
    currency,
    market_cap: q.cap,
    market_cap_usd: fx ? q.cap / fx : null,
    fx, // units of `currency` per 1 USD
    as_of: new Date().toISOString().slice(0, 16).replace("T", " "),
  });
}
