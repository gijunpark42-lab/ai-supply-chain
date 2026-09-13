// fundamentals.ts — valuation metrics (P/E, forward P/E, P/B, ...) pulled from the
// data source local investors in each market actually use:
//
//   Korea  (.KS / .KQ / bare numeric)  → Naver Finance mobile JSON API
//   Japan  (.T)                        → Yahoo Finance Japan quote page (embedded JSON)
//   Taiwan (.TW)                       → TWSE + TPEx official open-data tables (PER/PBR/yield)
//   everything else                    → Yahoo Finance quoteSummary (cookie + crumb)
//
// Each provider returns a Partial<Fundamentals>; the route calls the local provider
// first, then lets Yahoo Finance fill whatever is still null (e.g. TWSE publishes
// no forward P/E). `sources` records who supplied data so the UI can show it.
// All sources are free and need no API key.

import type { Fundamentals } from "@/lib/types";

const UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36";
const LIVE = 30; // seconds — server cache for anything that moves with the price

// Every metric the UI knows about, all null. Providers overwrite what they have.
export function empty(symbol: string): Fundamentals {
  return {
    symbol, trailing_pe: null, forward_pe: null, peg: null, pb: null, ps: null,
    ev_ebitda: null, ev_revenue: null, trailing_eps: null, forward_eps: null,
    roe: null, revenue_growth: null, gross_margin: null, op_margin: null,
    dividend_yield: null, target_mean: null, analysts: null, market_cap: null,
    currency: null, sources: [], as_of: "",
  };
}

// "8.08배" / "224,313원" / "0.17%" / "34.82" → 8.08 / 224313 / 0.17 / 34.82. Anything
// without a digit ("N/A", "---", "") → null.
function num(s: unknown): number | null {
  if (s == null) return null;
  const m = String(s).replace(/,/g, "").match(/-?\d+(\.\d+)?/);
  if (!m) return null;
  const n = parseFloat(m[0]);
  return isFinite(n) ? n : null;
}

// Percent string/number → fraction (0.17 → 0.0017), matching Yahoo's convention.
function pctToFrac(s: unknown): number | null {
  const n = num(s);
  return n == null ? null : n / 100;
}

// ─────────────────────────────── Korea: Naver Finance ───────────────────────────────
// https://m.stock.naver.com/api/stock/<6-digit code>/integration
//   totalInfos[] carries {code, value}: per, cnsPer (consensus = forward), pbr, eps,
//   cnsEps, dividendYieldRatio, marketValue ("1,323조 6,522억")
//   consensusInfo.priceTargetMean = analyst mean target
export async function naver(symbol: string): Promise<Partial<Fundamentals> | null> {
  const code = symbol.split(".")[0];
  if (!/^\d{6}$/.test(code)) return null;
  try {
    const res = await fetch(`https://m.stock.naver.com/api/stock/${code}/integration`, {
      headers: { "User-Agent": UA },
      next: { revalidate: LIVE },
    });
    if (!res.ok) return null;
    const j = await res.json();
    const info: Record<string, string> = {};
    for (const t of j.totalInfos || []) info[t.code] = t.value;

    // Market cap arrives in Korean units: "1,323조 6,522억" → 1323e12 + 6522e8.
    let cap: number | null = null;
    if (info.marketValue) {
      const jo = info.marketValue.match(/([\d,]+)조/);
      const eok = info.marketValue.match(/([\d,]+)억/);
      cap = (jo ? (num(jo[1]) ?? 0) * 1e12 : 0) + (eok ? (num(eok[1]) ?? 0) * 1e8 : 0) || null;
    }
    return {
      trailing_pe: num(info.per),
      forward_pe: num(info.cnsPer),
      pb: num(info.pbr),
      trailing_eps: num(info.eps),
      forward_eps: num(info.cnsEps),
      dividend_yield: pctToFrac(info.dividendYieldRatio),
      target_mean: num(j.consensusInfo?.priceTargetMean),
      market_cap: cap,
      currency: "KRW",
      sources: ["Naver Finance"],
    };
  } catch {
    return null;
  }
}

// ─────────────────────────────── Japan: Yahoo Finance Japan ─────────────────────────
// https://finance.yahoo.co.jp/quote/6857.T — a Next.js page whose server payload holds
// JSON fragments like  "name":"PER","subText":"（会社予想）", ... "value":"34.82"
// The quotes are escaped inside the payload (backslash-quote), so we unescape once,
// then regex.
//   PER（会社予想） = P/E on the company's own full-year guidance → forward_pe
//   PBR（実績）     = trailing P/B;  EPS（会社予想） = forward EPS;  ROE（実績） in %
export async function yahooJapan(symbol: string): Promise<Partial<Fundamentals> | null> {
  if (!symbol.endsWith(".T")) return null;
  try {
    const res = await fetch(`https://finance.yahoo.co.jp/quote/${encodeURIComponent(symbol)}`, {
      headers: { "User-Agent": UA, "Accept-Language": "ja" },
      next: { revalidate: LIVE },
    });
    if (!res.ok) return null;
    const html = (await res.text()).replace(/\\"/g, '"');
    // `sub` is a regex fragment: the JSON label is "（予想）" while the page shows
    // "（会社予想）", so we match on the tail ("予想）" / "実績）") to be safe.
    const pick = (name: string, sub: string): number | null => {
      const re = new RegExp(`"name":"${name}","subText":"[^"]*${sub}"[^}]*?"value":"([^"]*)"`);
      const m = html.match(re);
      return m ? num(m[1]) : null;
    };
    const fpe = pick("PER", "予想）");
    const pb = pick("PBR", "実績）");
    if (fpe == null && pb == null) return null; // page layout changed or symbol unknown
    const capM = html.match(/"name":"時価総額","value":"([^"]*)"/); // 百万円 = millions of yen
    const capNum = capM ? num(capM[1]) : null;
    return {
      forward_pe: fpe,
      pb,
      forward_eps: pick("EPS", "予想）"),
      roe: pctToFrac(pick("ROE", "実績）")),
      dividend_yield: pctToFrac(pick("配当利回り", "予想）")),
      market_cap: capNum ? capNum * 1e6 : null,
      currency: "JPY",
      sources: ["Yahoo Finance Japan"],
    };
  } catch {
    return null;
  }
}

// ─────────────────────────────── Taiwan: TWSE + TPEx open data ──────────────────────
// Official exchange tables, one row per listed stock, refreshed after each close:
//   TWSE (main board): https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_ALL
//                      {Code, PEratio, PBratio, DividendYield}
//   TPEx (OTC board):  https://www.tpex.org.tw/openapi/v1/tpex_mainboard_peratio_analysis
//                      {SecuritiesCompanyCode, PriceEarningRatio, PriceBookRatio, YieldRatio}
// Our metadata stores every Taiwan ticker as ".TW", so we look in TWSE first, then TPEx.
export async function taiwan(symbol: string): Promise<Partial<Fundamentals> | null> {
  if (!symbol.endsWith(".TW")) return null;
  const code = symbol.split(".")[0];
  const get = async (url: string): Promise<any[]> => {
    const res = await fetch(url, { headers: { "User-Agent": UA }, next: { revalidate: 1800 } });
    return res.ok ? await res.json() : [];
  };
  try {
    const twse = await get("https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_ALL");
    const r1 = twse.find((r) => r.Code === code);
    if (r1)
      return {
        trailing_pe: num(r1.PEratio),
        pb: num(r1.PBratio),
        dividend_yield: pctToFrac(r1.DividendYield),
        currency: "TWD",
        sources: ["TWSE"],
      };
    const tpex = await get("https://www.tpex.org.tw/openapi/v1/tpex_mainboard_peratio_analysis");
    const r2 = tpex.find((r) => r.SecuritiesCompanyCode === code);
    if (r2)
      return {
        trailing_pe: num(r2.PriceEarningRatio),
        pb: num(r2.PriceBookRatio),
        dividend_yield: pctToFrac(r2.YieldRatio),
        currency: "TWD",
        sources: ["TPEx"],
      };
    return null;
  } catch {
    return null;
  }
}

// ─────────────────────────────── Fallback / global: Yahoo Finance ───────────────────
// quoteSummary needs a "crumb": a short token Yahoo hands out once you carry its
// session cookie. Handshake (fc.yahoo.com → getcrumb) is cached per server instance.
let session: { cookie: string; crumb: string; fetchedAt: number } | null = null;
const SESSION_TTL_MS = 6 * 60 * 60 * 1000;

async function yahooSession(): Promise<{ cookie: string; crumb: string } | null> {
  if (session && Date.now() - session.fetchedAt < SESSION_TTL_MS) return session;
  try {
    const r1 = await fetch("https://fc.yahoo.com", {
      headers: { "User-Agent": UA }, redirect: "manual", cache: "no-store",
    });
    const cookie = (r1.headers.get("set-cookie") || "").split(";")[0]; // "A3=d=..."
    if (!cookie) return null;
    const r2 = await fetch("https://query2.finance.yahoo.com/v1/test/getcrumb", {
      headers: { "User-Agent": UA, Cookie: cookie }, cache: "no-store",
    });
    const crumb = (await r2.text()).trim();
    if (!r2.ok || !crumb || crumb.includes("<")) return null;
    session = { cookie, crumb, fetchedAt: Date.now() };
    return session;
  } catch {
    return null;
  }
}

// Yahoo wraps every number as { raw: 27.6, fmt: "27.60" }. Pull out `raw`.
function raw(obj: any, key: string): number | null {
  const v = obj?.[key];
  if (v == null) return null;
  const n = typeof v === "object" ? v.raw : v;
  return typeof n === "number" && isFinite(n) ? n : null;
}

export async function yahoo(symbol: string): Promise<Partial<Fundamentals> | null> {
  const out = await yahooOnce(symbol);
  // Taiwan OTC names (Phison 8299, GlobalWafers 6488, ...) are stored as ".TW" in our
  // metadata but live under ".TWO" on Yahoo. If ".TW" finds nothing, try ".TWO".
  if (!out && symbol.endsWith(".TW")) return yahooOnce(symbol.replace(/\.TW$/, ".TWO"));
  return out;
}

async function yahooOnce(symbol: string): Promise<Partial<Fundamentals> | null> {
  const s = await yahooSession();
  if (!s) return null;
  try {
    const url =
      `https://query2.finance.yahoo.com/v10/finance/quoteSummary/${encodeURIComponent(symbol)}` +
      `?modules=summaryDetail,defaultKeyStatistics,financialData&crumb=${encodeURIComponent(s.crumb)}`;
    const res = await fetch(url, {
      headers: { "User-Agent": UA, Cookie: s.cookie },
      next: { revalidate: LIVE },
    });
    if (res.status === 401) session = null; // stale crumb → next call re-handshakes
    if (!res.ok) return null;
    const r = (await res.json())?.quoteSummary?.result?.[0];
    if (!r) return null;
    const sd = r.summaryDetail || {};
    const ks = r.defaultKeyStatistics || {};
    const fd = r.financialData || {};
    return {
      trailing_pe: raw(sd, "trailingPE") ?? raw(ks, "trailingPE"),
      forward_pe: raw(sd, "forwardPE") ?? raw(ks, "forwardPE"),
      peg: raw(ks, "pegRatio"),
      pb: raw(ks, "priceToBook"),
      ps: raw(sd, "priceToSalesTrailing12Months"),
      ev_ebitda: raw(ks, "enterpriseToEbitda"),
      ev_revenue: raw(ks, "enterpriseToRevenue"),
      trailing_eps: raw(ks, "trailingEps"),
      forward_eps: raw(ks, "forwardEps"),
      roe: raw(fd, "returnOnEquity"),
      revenue_growth: raw(fd, "revenueGrowth"),
      gross_margin: raw(fd, "grossMargins"),
      op_margin: raw(fd, "operatingMargins"),
      dividend_yield: raw(sd, "dividendYield"),
      target_mean: raw(fd, "targetMeanPrice"),
      analysts: raw(fd, "numberOfAnalystOpinions"),
      market_cap: raw(sd, "marketCap"),
      currency: fd.financialCurrency ?? sd.currency ?? null,
      sources: ["Yahoo Finance"],
    };
  } catch {
    return null;
  }
}

// Pick the local provider for a Yahoo-style symbol ("000660.KS", "6857.T", "2330.TW").
export function localProvider(symbol: string) {
  if (/^\d{6}(\.K[SQ])?$/.test(symbol)) return naver;
  if (symbol.endsWith(".T")) return yahooJapan;
  if (symbol.endsWith(".TW")) return taiwan;
  return null;
}

// Copy every non-null field of `add` into `base` where base is still null, and
// record the source only if it contributed at least one number.
export function fill(base: Fundamentals, add: Partial<Fundamentals> | null): Fundamentals {
  if (!add) return base;
  let used = false;
  for (const k of Object.keys(add) as (keyof Fundamentals)[]) {
    if (k === "sources" || k === "symbol" || k === "as_of") continue;
    if (base[k] == null && add[k] != null) {
      (base as any)[k] = add[k];
      if (k !== "currency") used = true;
    }
  }
  if (used) base.sources = [...base.sources, ...(add.sources || [])];
  return base;
}
