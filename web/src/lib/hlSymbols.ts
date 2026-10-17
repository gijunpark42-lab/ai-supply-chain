// hlSymbols.ts — which Hyperliquid perpetual (if any) tracks a graph node's stock.
//
// Hyperliquid "builder dexes" list perpetual futures on stocks that trade 24/7.
// Each perp is named "<dex>:<SYMBOL>" (xyz:NVDA, para:COHR, io:SNDK). /api/hl
// returns their live prices keyed by that name; this file decides which name
// belongs to which company in our graph. When to SHOW the price is decided in
// lib/exchangeCalendar.ts (only while the stock's own exchange is shut all day).
//
// Two rules:
//   1. US-listed nodes (NASDAQ / NYSE) match by EXACT ticker on any dex:
//      node ticker "MU" → xyz:MU. New perps are picked up automatically.
//   2. Non-US nodes use the explicit NON_US table below, because Hyperliquid
//      gives them custom symbols (SK hynix = SKHX, Samsung = SMSN).
//
// Checked 2026-10-17 (a Saturday) against Yahoo's Friday close: all 47 US-ticker
// matches were within 0..−5% of Friday's close (that Friday was a chip selloff),
// so none is a different company that happens to share a ticker.

// The dexes that list single-stock perps that are still trading. As of 2026-10-17:
//   xyz  (trade.xyz)  — ~130 perps: US mega-caps + KR / JP / CN / HK names
//   para (Paragon)    — mid-caps (COHR, CIEN, STX, TER, CRDO, VST, SMCI ...)
//   io   (EntropyIO)  — a few (SNDK, NBIS, Tencent, Xiaomi)
// Not included: flx, km, mkts, cash, vntl, hyna, abcd — every stock perp on them
// is delisted (frozen price, zero volume) or they list only crypto / indexes.
export const HL_DEXES = ["xyz", "para", "io"];

// Readable venue name for each dex, shown in the caption.
export const HL_VENUE: Record<string, string> = {
  xyz: "trade.xyz",
  para: "Paragon",
  io: "EntropyIO",
};

// One perp as /api/hl returns it.
export interface HlPrice {
  mark: number; // mark price (USD) — what the chip shows
  oracle: number | null; // the dex's oracle / index price (USD)
  prev_day: number | null; // the perp's own price 24 hours ago (NOT the stock's close)
  day_volume_usd: number; // traded notional over the last 24 h, in USD
  funding_hr: number | null; // hourly funding rate as a fraction (0.0001 = 0.01%/h)
  open_interest: number | null; // open interest in contracts (1 contract = 1 share)
  dex: string; // "xyz", "para", "io"
}

export interface HlResponse {
  as_of: string; // ISO time the prices were read
  prices: Record<string, HlPrice>; // keyed by Hyperliquid name, e.g. "xyz:NVDA"
}

const US_EXCHANGES = new Set(["NASDAQ", "NYSE", "NYSE American"]);

// Hyperliquid symbols that are NOT a single stock: commodities, FX, indexes,
// rates, volatility, GPU rental prices. An exact-ticker match against one of
// these would be wrong (xyz:CL is crude oil, not Colgate-Palmolive), so they
// never match. ETFs (SMH, EWY, SOXL ...) are not companies in our graph, so
// they can't match anything and need no entry here.
const NOT_A_STOCK = new Set([
  // commodities
  "GOLD", "SILVER", "COPPER", "PLATINUM", "PALLADIUM", "ALUMINIUM", "URANIUM",
  "CL", "BRENTOIL", "NATGAS", "HO", "TTF", "CORN", "WHEAT", "OIL", "GAS", "WTI",
  "USOIL", "SOY",
  // FX
  "JPY", "EUR", "GBP", "KRW", "DXY",
  // indexes / volatility / rates
  "XYZ100", "SP500", "JP225", "JPN225", "KR200", "NIFTY", "IBOV", "VIX", "VOL", "BVIV",
  "US500", "USA500", "USA100", "USTECH", "SMALL2000", "USBOND", "USENERGY", "SEMI",
  "GLDMINE", "10Y", "2Y", "30Y", "TOTAL2", "OTHERS", "BTCD",
  // compute prices
  "H100",
]);

// Non-US listings → the exact Hyperliquid perp. Every perp here is quoted in USD
// per ONE home share, so it compares to the home close converted at the live FX
// rate. Each was checked on 2026-10-17 by name and by price (perp vs Friday close
// in USD; the gaps match that Friday's US chip selloff after Asia had closed):
const NON_US: Record<string, string> = {
  "SK Hynix": "xyz:SKHX", // 000660.KS ₩1,272,000 ÷ 1,329.6 = $956.7 vs $891.3 (−6.8%).
  //                         (xyz:SKHY is the US ADR, a different instrument — not used.)
  Samsung: "xyz:SMSN", // 005930.KS ₩215,500 → $162.1 vs $152.3 (−6.0%)
  Kioxia: "xyz:KIOXIA", // 285A.T ¥13,375 → $84.7 vs $80.6 (−4.8%)
  SoftBank: "xyz:SOFTBANK", // 9984.T ¥4,944 → $31.3 vs $29.8 (−4.8%)
  CXMT: "xyz:CXMT", // 688825.SS ¥45.02 → $6.74 vs $6.37 (−5.6%)
  GigaDevice: "xyz:GIGADEV", // 603986.SS ¥281.86 → $42.2 vs $39.6 (−6.2%)
  Cambricon: "xyz:CAMBRICON", // 688256.SS ¥915 → $137.0 vs $132.9 (−3.0%)
  MiniMax: "xyz:MINIMAX", // 0100.HK HK$182.1 → $23.2 vs $22.3 (−4.0%)
  "Zhipu AI": "xyz:ZHIPU", // 2513.HK HK$518 → $66.0 vs $62.6 (−5.1%)
  Tencent: "io:TCNT", // 0700.HK HK$417.8 → $53.2 vs $53.0 (−0.4%)
  //                     (km:TENCENT / para:TENCENT are delisted and quoted differently — not used.)
  Xiaomi: "io:XIAOMI", // 1810.HK HK$26.66 → $3.40 vs $3.38 (−0.4%)
  // TSMC, UMC, Nokia, ASML, Alibaba are stored with their US ticker (TSM, UMC, NOK,
  // ASML, BABA) and so match by rule 1; their perp tracks the US listing.
  // Delisted on every dex as of 2026-10-17 (so not mapped): Ibiden, Innolight, AMEC, Naver.
};

/**
 * The Hyperliquid names that could track this node's stock. Several dexes can
 * list the same US ticker (xyz:AVGO and para:AVGO), so this returns every
 * candidate and pickPerp() chooses the most liquid one that is live.
 */
export function hlCandidates(id: string, ticker: string | null, exchange: string | null): string[] {
  if (NON_US[id]) return [NON_US[id]];
  if (!ticker || !exchange || !US_EXCHANGES.has(exchange)) return [];
  if (NOT_A_STOCK.has(ticker)) return [];
  return HL_DEXES.map((dex) => `${dex}:${ticker}`);
}

/** Of the candidates present in `prices`, the one with the most 24 h volume. */
export function pickPerp(
  candidates: string[],
  prices: Record<string, HlPrice>
): { name: string; p: HlPrice } | null {
  let best: { name: string; p: HlPrice } | null = null;
  for (const name of candidates) {
    const p = prices[name];
    if (p && (!best || p.day_volume_usd > best.p.day_volume_usd)) best = { name, p };
  }
  return best;
}
