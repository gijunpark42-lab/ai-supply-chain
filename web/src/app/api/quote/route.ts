// /api/quote — server-side Yahoo Finance proxy for NON-US listings (the yfinance
// replacement). US tickers use the TradingView client widget instead. Returns the
// same shape app.py's _fetch_quote produced: { price, change_pct, market_cap,
// year_high, year_low, currency, series{range:[[ms,close]]}, as_of }.

import { NextRequest, NextResponse } from "next/server";
import { yahooSymbol } from "@/lib/yahoo";

export const runtime = "nodejs";
export const revalidate = 30; // cache 30 s (panel polls every 30 s for live updates)

interface YResult {
  meta?: any;
  timestamp?: number[];
  indicators?: { quote?: { close?: (number | null)[] }[] };
}

async function yahooChart(symbol: string, range: string, interval: string): Promise<YResult | null> {
  const url = `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(
    symbol
  )}?range=${range}&interval=${interval}`;
  try {
    const res = await fetch(url, {
      headers: { "User-Agent": "Mozilla/5.0 (compatible; supply-chain-app/1.0)" },
      next: { revalidate: 30 },
    });
    if (!res.ok) return null;
    const j = await res.json();
    return j?.chart?.result?.[0] ?? null;
  } catch {
    return null;
  }
}

function toSeries(r: YResult | null): [number, number][] {
  if (!r || !r.timestamp || !r.indicators?.quote?.[0]?.close) return [];
  const ts = r.timestamp;
  const close = r.indicators.quote[0].close!;
  const out: [number, number][] = [];
  for (let i = 0; i < ts.length; i++) {
    const c = close[i];
    if (c === null || c === undefined || isNaN(c)) continue;
    out.push([ts[i] * 1000, Math.round(c * 100) / 100]);
  }
  return out;
}

export async function GET(req: NextRequest) {
  const params = req.nextUrl.searchParams;
  const symbol = yahooSymbol(
    params.get("ticker") || params.get("symbol") || "",
    params.get("exchange")
  );
  if (!symbol) return NextResponse.json({ error: "no symbol" }, { status: 400 });

  const charts = (sym: string) =>
    Promise.all([
      yahooChart(sym, "1d", "5m"),
      yahooChart(sym, "5d", "30m"),
      yahooChart(sym, "1y", "1d"),
      yahooChart(sym, "max", "1wk"),
    ]);
  let [r1d, r1w, rDaily, rWeekly] = await charts(symbol);
  // Taiwan OTC names (Phison 8299, GlobalWafers 6488, ...) are stored as ".TW" in our
  // metadata but live under ".TWO" on Yahoo. If ".TW" returns nothing, retry ".TWO".
  if (!r1d && !r1w && !rDaily && !rWeekly && symbol.endsWith(".TW")) {
    [r1d, r1w, rDaily, rWeekly] = await charts(symbol.replace(/\.TW$/, ".TWO"));
  }

  const s1d = toSeries(r1d);
  const s1w = toSeries(r1w);
  const daily = toSeries(rDaily);
  const weekly = toSeries(rWeekly);

  const now = Date.now();
  const jan1 = new Date(new Date().getFullYear(), 0, 1).getTime();
  const s1m = daily.filter((p) => p[0] >= now - 31 * 86400 * 1000);
  const sytd = daily.filter((p) => p[0] >= jan1);
  const s5y = weekly.filter((p) => p[0] >= now - 5 * 365 * 86400 * 1000);

  const series: Record<string, [number, number][]> = {};
  for (const [k, ser] of [
    ["1D", s1d], ["1W", s1w], ["1M", s1m], ["YTD", sytd],
    ["1Y", daily], ["5Y", s5y], ["All", weekly],
  ] as [string, [number, number][]][]) {
    if (ser.length >= 2) series[k] = ser;
  }
  if (Object.keys(series).length === 0)
    return NextResponse.json({ error: "no data" }, { status: 404 });

  // Prefer the 1d-range meta: its chartPreviousClose is the PRIOR TRADING DAY close
  // (a wider range's chartPreviousClose is the close before that whole range, e.g. a
  // year ago, which would make the day change absurd).
  const meta = r1d?.meta || rDaily?.meta || rWeekly?.meta || {};
  const last = meta.regularMarketPrice ?? null;
  const prev = meta.previousClose ?? meta.chartPreviousClose ?? null;
  const round2 = (x: number | null) => (x == null ? null : Math.round(x * 100) / 100);

  return NextResponse.json({
    price: round2(last),
    change_pct: last != null && prev ? Math.round(((last - prev) / prev) * 10000) / 100 : null,
    market_cap: meta.marketCap ?? null,
    year_high: round2(meta.fiftyTwoWeekHigh ?? null),
    year_low: round2(meta.fiftyTwoWeekLow ?? null),
    currency: meta.currency ?? null,
    series,
    as_of: new Date().toISOString().slice(0, 16).replace("T", " "),
  });
}
