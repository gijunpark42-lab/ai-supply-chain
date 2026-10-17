"use client";

// WeekendPerps — the Markets → Weekend sub-tab (2026-10-17): where every company
// in the graph that has a Hyperliquid 24/7 perpetual trades right now, in one table.
//
//   Company   Perp      Perp price           Last close              Change  24h vol  Home exchange
//   Micron    xyz:MU    $856.22              $880.10 10-16-2026      −2.7%   $78.8M   NASDAQ Closed today
//   SK Hynix  xyz:SKHX  $890.62 ≈ ₩1,184,000 ₩1,272,000 10-16-2026   −6.8%   $73.2M   KOSPI  Closed today
//
// Same pieces and rules as the chip in the company panel (WeekendPerpPrice.tsx):
//   lib/hlSymbols.ts         which perp belongs to which graph node
//   /api/hl                  live perp prices, polled every 60 s while this tab is open
//   /api/quotes              each listing's last regular close (+ the FX rate of a non-USD
//                            listing), fetched once, in batches of 40 symbols
//   lib/exchangeCalendar.ts  is the home exchange shut all day today?
//   lib/perpQuotes.ts        the hide rules (< $50k 24 h volume, > 30% from the close) and formats
// Unlike the chip, the table also works on a trading day: a note at the top then
// says the official prices are live and the perp is compared with the previous close.

import { useEffect, useMemo, useState } from "react";
import type { GraphNode } from "@/lib/types";
import type { Resolver } from "@/lib/company";
import { useLang } from "@/lib/i18n";
import { yahooSymbol } from "@/lib/yahoo";
import { fmtDay } from "@/lib/companyFeeds";
import { sortRows, type CellValue, type SortDir } from "@/lib/table";
import { HL_VENUE, hlCandidates, pickPerp, type HlPrice, type HlResponse } from "@/lib/hlSymbols";
import { closedAllDay, exchangeTz } from "@/lib/exchangeCalendar";
import {
  LOCALE,
  MAX_GAP,
  MIN_VOLUME_USD,
  changeVsClose,
  compactUsd,
  fetchHl,
  getQuotesBatched,
  money,
  signedPct,
  usd,
} from "@/lib/perpQuotes";
import CompanyLink from "./CompanyLink";

const REFRESH_MS = 60_000; // poll /api/hl every 60 s while the tab is open

// A graph node that may have a perp: its candidates (lib/hlSymbols.ts) and its
// Yahoo symbol (for the last close).
interface Listing {
  id: string;
  exchange: string | null;
  candidates: string[];
  symbol: string | null;
}

// What /api/quotes told us about one listing, plus the FX rate to put it in USD.
interface CloseQuote {
  price: number; // Yahoo's latest official price: the last close on a closed day
  prev: number | null; // the close of the session before that
  time: number; // epoch ms of `price`
  currency: string;
  fx: number; // units of `currency` per 1 USD (1 for USD)
}

// One table row.
interface Row {
  id: string;
  exchange: string | null;
  perp: string; // Hyperliquid name, "xyz:NVDA"
  p: HlPrice;
  close: number | null; // the close the perp is compared with, in the listing's currency
  closeTime: number | null; // its time; null = "the previous session" (date not in the quote)
  currency: string;
  fx: number | null;
  change: number | null; // perp vs that close, both in USD (0.012 = +1.2%)
  local: number | null; // perp price in the listing's currency (non-USD listings only)
  closed: boolean; // home exchange shut all day today
}

type SortKey = "company" | "perp" | "price" | "close" | "change" | "volume" | "status";

/** "YYYY-MM-DD" of an instant in a time zone (the viewer's when tz is null). */
function dayIn(time: number, tz: string | null): string {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: tz || undefined,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date(time));
  const get = (type: string) => parts.find((x) => x.type === type)?.value || "";
  return `${get("year")}-${get("month")}-${get("day")}`;
}

/**
 * The last regular closes of these Yahoo symbols: one batched /api/quotes round
 * for the listings, then one for the FX pairs of the non-USD currencies seen
 * (KRW=X = won per 1 USD). null when nothing came back (retried on the next tick).
 */
async function loadCloses(symbols: string[]): Promise<Record<string, CloseQuote> | null> {
  const quotes = await getQuotesBatched(symbols);
  if (Object.keys(quotes).length === 0) return null;
  const currencies = [...new Set(Object.values(quotes).map((q) => q.currency || "USD"))].filter((c) => c !== "USD");
  const fx = currencies.length ? await getQuotesBatched(currencies.map((c) => `${c}=X`)) : {};
  const out: Record<string, CloseQuote> = {};
  for (const [symbol, q] of Object.entries(quotes)) {
    const currency = q.currency || "USD";
    const rate = currency === "USD" ? 1 : fx[`${currency}=X`]?.price ?? 0;
    if (!q.price || !q.quote_time || !rate) continue; // that row shows "—" for the close
    out[symbol] = { price: q.price, prev: q.prev_close, time: q.quote_time, currency, fx: rate };
  }
  return out;
}

export default function WeekendPerps({
  nodes,
  resolve,
  onOpen,
}: {
  nodes: GraphNode[];
  resolve: Resolver;
  onOpen: (id: string) => void;
}) {
  const { t, lang, name, rev } = useLang();

  // Every node that could have a perp (US tickers + the non-US table in hlSymbols.ts).
  const listings = useMemo<Listing[]>(
    () =>
      nodes
        .filter((n) => n.ticker)
        .map((n) => ({
          id: n.id,
          exchange: n.exchange,
          candidates: hlCandidates(n.id, n.ticker, n.exchange),
          symbol: yahooSymbol(n.ticker, n.exchange),
        }))
        .filter((l) => l.candidates.length > 0),
    [nodes]
  );

  const [hl, setHl] = useState<HlResponse | null>(null);
  const [hlFailed, setHlFailed] = useState(false); // the last /api/hl poll got nothing
  const [closes, setCloses] = useState<Record<string, CloseQuote>>({});
  const [now, setNow] = useState(() => Date.now()); // re-read every tick: "Closed today" flips at midnight

  useEffect(() => {
    let alive = true; // ignore late responses after the tab closes
    let closesDone = false; // the last closes don't move on a closed day: fetch them once
    let closesPending = false;

    const tick = () => {
      setNow(Date.now());
      fetchHl()
        .then((d) => {
          if (!alive) return;
          if (!d || Object.keys(d.prices || {}).length === 0) {
            setHlFailed(true); // a failed poll keeps the last good prices on screen
            return;
          }
          setHlFailed(false);
          setHl(d);

          // The last closes, once, for the listings that have a live perp (~60 of
          // the ~260 US tickers that could have one → two batches, not seven).
          if (closesDone || closesPending) return;
          const symbols = [
            ...new Set(listings.filter((l) => l.symbol && pickPerp(l.candidates, d.prices)).map((l) => l.symbol!)),
          ];
          if (symbols.length === 0) return;
          closesPending = true;
          loadCloses(symbols)
            .then((c) => {
              if (!c) return; // try again on the next tick
              closesDone = true;
              if (alive) setCloses(c);
            })
            .catch(() => {})
            .finally(() => { closesPending = false; });
        })
        .catch(() => { if (alive) setHlFailed(true); });
    };

    tick();
    const timer = setInterval(tick, REFRESH_MS);
    return () => { alive = false; clearInterval(timer); };
  }, [listings]);

  // Every listing with a live perp → a row; then split by the chip's hide rules.
  const { shown, hidden } = useMemo(() => {
    const shown: Row[] = [];
    let hidden = 0;
    if (!hl) return { shown, hidden };
    for (const l of listings) {
      const hit = pickPerp(l.candidates, hl.prices);
      if (!hit) continue; // no live perp for this company right now
      const tz = exchangeTz(l.exchange);
      const q = l.symbol ? closes[l.symbol] : undefined;
      // On a closed day Yahoo's price IS the last regular close. When it is from
      // today's session (live, or today's close), the perp is compared with the
      // session before instead: "the previous close" in the trading-day note.
      let close: number | null = null;
      let closeTime: number | null = null;
      if (q && tz && dayIn(q.time, tz) === dayIn(now, tz)) close = q.prev;
      else if (q) [close, closeTime] = [q.price, q.time];
      const change = q && close ? changeVsClose(hit.p.mark, close, q.fx) : null;

      if (hit.p.day_volume_usd < MIN_VOLUME_USD || (change !== null && Math.abs(change) > MAX_GAP)) {
        hidden++;
        continue;
      }
      shown.push({
        id: l.id,
        exchange: l.exchange,
        perp: hit.name,
        p: hit.p,
        close,
        closeTime,
        currency: q?.currency || "USD",
        fx: q?.fx ?? null,
        change,
        local: q && q.currency !== "USD" ? hit.p.mark * q.fx : null,
        closed: closedAllDay(l.exchange, new Date(now)),
      });
    }
    return { shown, hidden };
  }, [hl, listings, closes, now]);

  // Sort: biggest move first by default (the Change column sorts by the SIZE of the move).
  const [sortKey, setSortKey] = useState<SortKey>("change");
  const [sortDir, setSortDir] = useState<SortDir>(-1);
  const onSort = (key: SortKey) => {
    if (key === sortKey) setSortDir((d) => (d === 1 ? -1 : 1));
    else {
      setSortKey(key);
      setSortDir(key === "company" || key === "perp" || key === "status" ? 1 : -1); // text A→Z, numbers biggest first
    }
  };
  const rows = useMemo(() => {
    const get = (r: Row): CellValue => {
      if (sortKey === "company") return name(r.id);
      if (sortKey === "perp") return r.perp;
      if (sortKey === "price") return r.p.mark;
      if (sortKey === "close") return r.close !== null && r.fx ? r.close / r.fx : null; // in USD
      if (sortKey === "change") return r.change === null ? null : Math.abs(r.change);
      if (sortKey === "volume") return r.p.day_volume_usd;
      return r.closed ? 0 : 1; // status: closed first
    };
    // Volume order first, so rows that tie (or have no close yet) stay most-traded first.
    const byVolume = sortRows(shown, (r) => r.p.day_volume_usd, -1);
    return sortRows(byVolume, get, sortDir);
  }, [shown, sortKey, sortDir, name, rev]); // rev: the local company names arrived / the language changed

  // A sortable header cell (same pattern as the Model benchmarks table).
  const sortTh = (k: SortKey, label: string) => (
    <th
      key={k}
      className={"tb-sortable" + (sortKey === k ? " active" : "")}
      aria-sort={sortKey === k ? (sortDir === 1 ? "ascending" : "descending") : "none"}
      tabIndex={0}
      title={t("Sort by {col}", { col: label })}
      onClick={() => onSort(k)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onSort(k);
        }
      }}
    >
      <span className="th-label">{label}</span>
      <span className="sort-arrow" aria-hidden="true">
        {sortKey === k ? (sortDir === 1 ? "▲" : "▼") : "↕"}
      </span>
    </th>
  );

  if (!hl) {
    if (hlFailed)
      return <p className="caption">{t("Hyperliquid prices are unavailable right now. The table retries every minute.")}</p>;
    return <div className="spinner">{t("Loading Hyperliquid prices…")}</div>;
  }

  const anyOpen = rows.some((r) => !r.closed);
  const venues = [...new Set(rows.map((r) => HL_VENUE[r.p.dex] || r.p.dex))].join(", ");
  const updated = new Intl.DateTimeFormat(LOCALE[lang], { hour: "numeric", minute: "2-digit" }).format(new Date(hl.as_of));

  return (
    <section className="mk-section">
      <h3>{t("Weekend perp prices")}</h3>
      {anyOpen && (
        <p className="mk-note" role="note">
          {t("Exchanges are open: official prices are live; this table compares the perp with the previous close.")}
        </p>
      )}
      <p className="caption">
        {t("{n} companies in the graph have a live Hyperliquid perp. Biggest moves first; click a column to sort.", {
          n: shown.length + hidden,
        })}{" "}
        {t("Updated {time}", { time: updated })}
      </p>

      <div className="tbl-wrap mk-tbl">
        <table className="data mk-table mk-perps">
          <thead>
            <tr>
              {sortTh("company", t("Company"))}
              {sortTh("perp", t("Perp"))}
              {sortTh("price", t("Perp price"))}
              {sortTh("close", t("Last close"))}
              {sortTh("change", t("Change"))}
              {sortTh("volume", t("24h volume"))}
              {sortTh("status", t("Home exchange"))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <td className="co">
                  <CompanyLink text={r.id} resolve={resolve} onOpen={onOpen} />
                  {/* phones only (Markets.css): the Perp column folds in here so Change fits on screen */}
                  <span className="mk-muted mk-perp-sub">{r.perp}</span>
                </td>
                <td
                  className="mk-perp"
                  title={[
                    HL_VENUE[r.p.dex] || r.p.dex,
                    r.p.funding_hr !== null && t("Funding {rate}/hr", { rate: (r.p.funding_hr * 100).toFixed(4) + "%" }),
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                >
                  {r.perp}
                </td>
                <td className="mk-num">
                  {usd(r.p.mark)}
                  {r.local !== null && r.fx !== null && (
                    <span
                      className="mk-muted mk-sub"
                      title={t("Converted at 1 USD = {rate} {cur}", {
                        rate: r.fx.toLocaleString(undefined, { maximumFractionDigits: 4 }),
                        cur: r.currency,
                      })}
                    >
                      {" "}≈ {money(r.local, r.currency)}
                    </span>
                  )}
                </td>
                <td className="mk-num">
                  {r.close === null ? (
                    "—"
                  ) : (
                    <>
                      {r.currency === "USD" ? usd(r.close) : money(r.close, r.currency)}{" "}
                      <span className="mk-muted mk-sub">
                        {r.closeTime === null ? t("previous session") : fmtDay(dayIn(r.closeTime, exchangeTz(r.exchange)))}
                      </span>
                    </>
                  )}
                </td>
                <td className={"mk-num mk-chg " + (r.change === null ? "" : r.change >= 0 ? "mk-up" : "mk-down")}>
                  {r.change === null ? "—" : signedPct(r.change)}
                </td>
                <td className="mk-num">{compactUsd(r.p.day_volume_usd)}</td>
                <td>
                  <span className="mk-muted">{r.exchange}</span>{" "}
                  {r.closed ? (
                    <span className="mk-badge mk-closed">{t("Closed today")}</span>
                  ) : (
                    <span className="mk-badge mk-ok">{t("Open")}</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {hidden > 0 && (
        <p className="caption mk-hidden-note">
          {t("{n} more perps hidden: under $50k traded in 24 h, or more than 30% from the last close.", { n: hidden })}
        </p>
      )}
      <p className="caption mk-attribution">
        {t("Perpetual futures on Hyperliquid ({venue}), trading 24/7 — not the official stock price; can diverge (funding, liquidity)", {
          venue: venues,
        })}
      </p>
    </section>
  );
}
