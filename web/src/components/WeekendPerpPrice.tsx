"use client";

// WeekendPerpPrice — a one-row chip under the price chart that shows where the
// stock is trading on Hyperliquid's 24/7 perpetual futures, ONLY on days its
// home exchange is shut all day (weekends, exchange holidays):
//
//   24/7 · Hyperliquid perp  $853.48  −2.9% vs Fri close        24h vol $77.3M
//   Perpetual futures on Hyperliquid (trade.xyz), trading 24/7 — not the official ...
//
// Pieces:
//   lib/hlSymbols.ts       which perp belongs to this company (or none → renders nothing)
//   lib/exchangeCalendar.ts is the home exchange closed for the whole local day?
//   /api/hl                live perp prices (polled every 60 s while the panel is open)
//   /api/quotes            the last regular close (Yahoo) the change is measured against,
//                          plus the FX rate for a non-USD listing (perps are quoted in USD)
//
// Testing on a weekday: add ?hl=1 to the URL to show the chip regardless of the calendar.

import { useEffect, useState } from "react";
import { useLang, type Lang } from "@/lib/i18n";
import { yahooSymbol } from "@/lib/yahoo";
import { HL_VENUE, hlCandidates, pickPerp, type HlResponse } from "@/lib/hlSymbols";
import { closedAllDay, exchangeTz } from "@/lib/exchangeCalendar";
import { CUR } from "./LiveQuote";
import "./WeekendPerpPrice.css";

const REFRESH_MS = 60_000; // poll /api/hl every 60 s while the panel is open
const MIN_VOLUME_USD = 50_000; // under $50k traded in 24 h the price says little → hide
// A perp more than 30% away from the last close is almost certainly a different
// instrument (or a units mix-up), not a real weekend move → hide rather than mislead.
const MAX_GAP = 0.3;

const LOCALE: Record<Lang, string> = { en: "en-US", ko: "ko-KR", zh: "zh-CN", ja: "ja-JP" };

// The fields of an /api/quotes entry this component reads.
interface Quote {
  price: number | null; // on a closed day this is the last regular close
  currency: string | null;
  quote_time: number | null; // epoch ms of that close
}

// The last regular close the perp is compared with.
interface LastClose {
  close: number; // in the listing's own currency
  currency: string; // "USD", "KRW", ...
  fx: number; // units of that currency per 1 USD (1 for USD)
  time: number; // epoch ms of the close
}

async function getQuotes(symbols: string[]): Promise<Record<string, Quote>> {
  const res = await fetch(`/api/quotes?symbols=${encodeURIComponent(symbols.join(","))}`);
  if (!res.ok) return {};
  return (await res.json())?.quotes || {};
}

// Yahoo's last close for the home listing, and (non-USD only) the FX rate from
// Yahoo's "<CUR>=X" pair (KRW=X = won per 1 USD) to put it in dollars.
async function loadLastClose(symbol: string): Promise<LastClose | null> {
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

// $853.48 · $6.367 (more decimals for cheap stocks, like Hyperliquid quotes them)
function usd(v: number): string {
  return "$" + v.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: v >= 100 ? 2 : v >= 1 ? 3 : 4,
  });
}

// ₩1,185,111 · ¥12,727 · HK$174.77
function money(v: number, currency: string): string {
  const sym = CUR[currency] || currency + " ";
  return sym + v.toLocaleString(undefined, { maximumFractionDigits: v >= 1000 ? 0 : 2 });
}

// 77308425 → "$77.3M"
function compactUsd(v: number): string {
  const [n, unit] = v >= 1e9 ? [v / 1e9, "B"] : v >= 1e6 ? [v / 1e6, "M"] : [v / 1e3, "K"];
  return "$" + n.toFixed(n >= 100 ? 0 : 1) + unit;
}

// The day of the last close in the exchange's time zone: "Fri" / "금요일" / "周五" / "金曜日".
// A close more than 6 days back (a long holiday) shows as a date instead.
function closeDay(time: number, tz: string | null, lang: Lang): string {
  const old = Date.now() - time > 6 * 86_400_000;
  const opts: Intl.DateTimeFormatOptions = old
    ? { month: "numeric", day: "numeric" }
    : { weekday: lang === "en" || lang === "zh" ? "short" : "long" };
  return new Intl.DateTimeFormat(LOCALE[lang], { ...opts, timeZone: tz || undefined }).format(new Date(time));
}

export default function WeekendPerpPrice({
  id,
  ticker,
  exchange,
}: {
  id: string; // graph node id ("SK Hynix") — non-US names are mapped by id
  ticker: string;
  exchange: string | null;
}) {
  const { t, lang } = useLang();
  const [show, setShow] = useState(false); // is today a closed day (or ?hl=1)?
  const [hl, setHl] = useState<HlResponse | null>(null);
  const [last, setLast] = useState<LastClose | null>(null);

  useEffect(() => {
    setShow(false);
    setHl(null);
    setLast(null);
    if (hlCandidates(id, ticker, exchange).length === 0) return; // no perp for this company

    const force = new URLSearchParams(window.location.search).get("hl") === "1";
    const symbol = yahooSymbol(ticker, exchange);
    let alive = true; // ignore late responses after the panel switches company
    let closeDone = false; // the last close never changes on a closed day: fetch it once
    let closePending = false;

    const load = () => {
      // Re-checked on every tick, so the chip goes away by itself when Monday starts.
      const closed = force || closedAllDay(exchange);
      setShow(closed);
      if (!closed) return; // a trading day: the chart above is the real price

      fetch("/api/hl")
        .then((r) => (r.ok ? r.json() : null))
        .then((d: HlResponse | null) => { if (alive && d) setHl(d); })
        .catch(() => {});

      if (symbol && !closeDone && !closePending) {
        closePending = true;
        loadLastClose(symbol)
          .then((c) => {
            if (!c) return; // try again on the next tick
            closeDone = true;
            if (alive) setLast(c);
          })
          .catch(() => {})
          .finally(() => { closePending = false; });
      }
    };

    load();
    const timer = setInterval(load, REFRESH_MS);
    return () => { alive = false; clearInterval(timer); };
  }, [id, ticker, exchange]);

  if (!show || !hl) return null;
  const hit = pickPerp(hlCandidates(id, ticker, exchange), hl.prices);
  if (!hit || hit.p.day_volume_usd < MIN_VOLUME_USD) return null;
  const { name: hlName, p } = hit;

  // Change vs the last regular close, both in USD (a KRW close is divided by KRW=X).
  const change = last ? p.mark / (last.close / last.fx) - 1 : null;
  if (change !== null && Math.abs(change) > MAX_GAP) return null;
  // For a non-USD listing, the perp price in the home currency too (≈ ₩1,185,111).
  const local = last && last.currency !== "USD" ? p.mark * last.fx : null;

  const caption = t(
    "Perpetual futures on Hyperliquid ({venue}), trading 24/7 — not the official stock price; can diverge (funding, liquidity)",
    { venue: HL_VENUE[p.dex] || p.dex }
  );
  const tip = [
    caption,
    hlName,
    p.funding_hr !== null && t("Funding {rate}/hr", { rate: (p.funding_hr * 100).toFixed(4) + "%" }),
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <div className="wpp" title={tip}>
      <div className="wpp-row">
        <span className="wpp-tag">{t("24/7 · Hyperliquid perp")}</span>
        <span className="wpp-px">{usd(p.mark)}</span>
        {local !== null && last && (
          <span
            className="wpp-local"
            title={t("Converted at 1 USD = {rate} {cur}", {
              rate: last.fx.toLocaleString(undefined, { maximumFractionDigits: 4 }),
              cur: last.currency,
            })}
          >
            ≈ {money(local, last.currency)}
          </span>
        )}
        {change !== null && last && (
          <span
            className={"wpp-chg " + (change >= 0 ? "up" : "down")}
            title={t("Last regular close {close}", { close: money(last.close, last.currency) })}
          >
            {t("{pct} vs {day} close", {
              pct: (change >= 0 ? "+" : "−") + Math.abs(change * 100).toFixed(1) + "%",
              day: closeDay(last.time, exchangeTz(exchange), lang),
            })}
          </span>
        )}
        <span className="wpp-vol">{t("24h vol {v}", { v: compactUsd(p.day_volume_usd) })}</span>
      </div>
      <div className="wpp-cap">{caption}</div>
    </div>
  );
}
