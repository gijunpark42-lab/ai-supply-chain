// perpQuotes.ts — what the two Hyperliquid perp views share (2026-10-17):
//   components/WeekendPerpPrice.tsx  the 24/7 chip in the company panel
//   components/WeekendPerps.tsx      the Markets → Weekend table of every mapped company
// Both compare a perp's USD mark with the stock's last regular close (Yahoo, via
// /api/quotes) and hide a perp by the same two rules, so those rules live here.

import type { Lang } from "./i18n";
import type { HlResponse } from "./hlSymbols";
// The currency symbols the live-quote chart already uses (₩, ¥, HK$ ...).
import { CUR } from "@/components/LiveQuote";

export const MIN_VOLUME_USD = 50_000; // under $50k traded in 24 h the price says little → hide
// A perp more than 30% away from the last close is almost certainly a different
// instrument (or a units mix-up), not a real weekend move → hide rather than mislead.
export const MAX_GAP = 0.3;

// /api/quotes takes at most this many symbols per request (its MAX_SYMBOLS).
export const MAX_QUOTE_SYMBOLS = 40;

export const LOCALE: Record<Lang, string> = { en: "en-US", ko: "ko-KR", zh: "zh-CN", ja: "ja-JP" };

// The fields of an /api/quotes entry these views read.
export interface Quote {
  price: number | null; // on a closed day this is the last regular close
  prev_close: number | null; // the close of the session before `price`'s (read by the Weekend table)
  currency: string | null;
  quote_time: number | null; // epoch ms of that close
}

// The last regular close the perp is compared with.
export interface LastClose {
  close: number; // in the listing's own currency
  currency: string; // "USD", "KRW", ...
  fx: number; // units of that currency per 1 USD (1 for USD)
  time: number; // epoch ms of the close
}

export async function getQuotes(symbols: string[]): Promise<Record<string, Quote>> {
  const res = await fetch(`/api/quotes?symbols=${encodeURIComponent(symbols.join(","))}`);
  if (!res.ok) return {};
  return (await res.json())?.quotes || {};
}

/** getQuotes() for any number of symbols: one request per 40, sent in parallel, merged. */
export async function getQuotesBatched(symbols: string[]): Promise<Record<string, Quote>> {
  const parts: Promise<Record<string, Quote>>[] = [];
  for (let i = 0; i < symbols.length; i += MAX_QUOTE_SYMBOLS) {
    // A failed batch only loses its own symbols.
    parts.push(getQuotes(symbols.slice(i, i + MAX_QUOTE_SYMBOLS)).catch(() => ({})));
  }
  return Object.assign({}, ...(await Promise.all(parts)));
}

// Yahoo's last close for the home listing, and (non-USD only) the FX rate from
// Yahoo's "<CUR>=X" pair (KRW=X = won per 1 USD) to put it in dollars.
export async function loadLastClose(symbol: string): Promise<LastClose | null> {
  const q = (await getQuotes([symbol]))[symbol];
  if (!q?.price || !q.quote_time) return null;
  const currency = q.currency || "USD";
  let fx = 1;
  if (currency !== "USD") {
    const pair = `${currency}=X`;
    fx = (await getQuotes([pair]))[pair]?.price ?? 0;
    if (!fx) return null;
  }
  return { close: q.price, currency, fx, time: q.quote_time };
}

/** The live perp prices, or null when /api/hl cannot be reached. */
export async function fetchHl(): Promise<HlResponse | null> {
  const r = await fetch("/api/hl");
  return r.ok ? r.json() : null;
}

/** Perp mark (USD) vs a close in the listing's currency: both in USD (a KRW close is divided by KRW=X). */
export function changeVsClose(mark: number, close: number, fx: number): number {
  return mark / (close / fx) - 1;
}

// −0.029 → "−2.9%" · 0.012 → "+1.2%"
export function signedPct(change: number): string {
  return (change >= 0 ? "+" : "−") + Math.abs(change * 100).toFixed(1) + "%";
}

// $853.48 · $6.367 (more decimals for cheap stocks, like Hyperliquid quotes them)
export function usd(v: number): string {
  return "$" + v.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: v >= 100 ? 2 : v >= 1 ? 3 : 4,
  });
}

// ₩1,185,111 · ¥12,727 · HK$174.77
export function money(v: number, currency: string): string {
  const sym = CUR[currency] || currency + " ";
  return sym + v.toLocaleString(undefined, { maximumFractionDigits: v >= 1000 ? 0 : 2 });
}

// 77308425 → "$77.3M"
export function compactUsd(v: number): string {
  const [n, unit] = v >= 1e9 ? [v / 1e9, "B"] : v >= 1e6 ? [v / 1e6, "M"] : [v / 1e3, "K"];
  return "$" + n.toFixed(n >= 100 ? 0 : 1) + unit;
}

// The day of the last close in the exchange's time zone: "Fri" / "금요일" / "周五" / "金曜日".
// A close more than 6 days back (a long holiday) shows as a date instead.
export function closeDay(time: number, tz: string | null, lang: Lang): string {
  const old = Date.now() - time > 6 * 86_400_000;
  const opts: Intl.DateTimeFormatOptions = old
    ? { month: "numeric", day: "numeric" }
    : { weekday: lang === "en" || lang === "zh" ? "short" : "long" };
  return new Intl.DateTimeFormat(LOCALE[lang], { ...opts, timeZone: tz || undefined }).format(new Date(time));
}
