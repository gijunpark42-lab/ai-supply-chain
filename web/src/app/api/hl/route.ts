// /api/hl — live prices of Hyperliquid's 24/7 stock perpetuals.
//
// On a Saturday the NYSE is shut, but the perpetual future xyz:NVDA keeps
// trading on Hyperliquid, so its price shows roughly where NVIDIA would trade.
// The node panel shows it on weekends and holidays (components/WeekendPerpPrice.tsx).
//
// One POST per dex to Hyperliquid's public info endpoint (no key needed):
//   {"type":"metaAndAssetCtxs","dex":"xyz"}
//   → [ {universe: [{name:"xyz:NVDA", ...}, ...]},  [{markPx, oraclePx, ...}, ...] ]
// The two arrays are parallel: universe[i] and ctxs[i] describe the same perp.
//
// Response: { as_of, prices: { "xyz:NVDA": {mark, oracle, prev_day, day_volume_usd,
// funding_hr, open_interest, dex}, ... } }. It never throws: on any error the
// affected dex is just missing (all of them → empty prices).

import { NextResponse } from "next/server";
import { HL_DEXES, type HlPrice, type HlResponse } from "@/lib/hlSymbols";

export const runtime = "nodejs";
export const revalidate = 0; // this route decides its own caching (see CACHE_MS)

const CACHE_MS = 30_000; // serve a memo for 30 s; the panel polls every 60 s
const TIMEOUT_MS = 8_000; // give up on a slow dex instead of hanging the request

// Memo lives on the warm lambda; a cold start just refetches.
let memo: { at: number; body: HlResponse } | null = null;

// Hyperliquid sends numbers as strings ("212.25"). null when missing / not a number.
function num(v: unknown): number | null {
  if (v === null || v === undefined || v === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

async function fetchDex(dex: string): Promise<Record<string, HlPrice>> {
  const out: Record<string, HlPrice> = {};
  try {
    const res = await fetch("https://api.hyperliquid.xyz/info", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ type: "metaAndAssetCtxs", dex }),
      cache: "no-store",
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
    if (!res.ok) return out;
    const data = await res.json();
    const universe: any[] = data?.[0]?.universe || [];
    const ctxs: any[] = data?.[1] || [];
    universe.forEach((u, i) => {
      const c = ctxs[i];
      // A delisted perp keeps a frozen last price with zero volume — never show it.
      if (!u?.name || !c || u.isDelisted) return;
      const mark = num(c.markPx);
      if (mark === null || mark <= 0) return;
      out[u.name] = {
        mark,
        oracle: num(c.oraclePx),
        prev_day: num(c.prevDayPx),
        day_volume_usd: num(c.dayNtlVlm) ?? 0,
        funding_hr: num(c.funding), // Hyperliquid funding is paid hourly
        open_interest: num(c.openInterest),
        dex,
      };
    });
  } catch {
    // network error, timeout or bad JSON: this dex is simply left out
  }
  return out;
}

export async function GET() {
  const now = Date.now();
  if (memo && now - memo.at < CACHE_MS) {
    return NextResponse.json(memo.body, { headers: { "Cache-Control": "no-store" } });
  }

  // fetchDex never rejects, so Promise.all always resolves.
  const parts = await Promise.all(HL_DEXES.map(fetchDex));
  const prices: Record<string, HlPrice> = Object.assign({}, ...parts);
  const body: HlResponse = { as_of: new Date().toISOString(), prices };

  // Only remember a good answer, so a failed fetch is retried on the next request.
  if (Object.keys(prices).length > 0) memo = { at: now, body };

  return NextResponse.json(body, { headers: { "Cache-Control": "no-store" } });
}
