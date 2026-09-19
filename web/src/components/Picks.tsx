"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { BASKETS, ENTRY_DATE, ALL_SYMBOLS, money, pct, tone, type Pick, type Quotes } from "@/lib/picks";
import PicksUniverse from "./PicksUniverse";
import "./Picks.css";

const REFRESH_MS = 60_000;

type SortKey = "rank" | "ret" | "day";

export default function Picks({ onOpen }: { onOpen: (company: string) => void }) {
  const [basketKey, setBasketKey] = useState(BASKETS[1].key); // default: the combined list
  const [quotes, setQuotes] = useState<Quotes>({});
  const [state, setState] = useState<"loading" | "ok" | "err">("loading");
  const [updated, setUpdated] = useState<Date | null>(null);
  const [busy, setBusy] = useState(false);
  const [sort, setSort] = useState<SortKey>("rank");
  const firstLoad = useRef(true);

  const load = useCallback(async () => {
    setBusy(true);
    try {
      const res = await fetch(`/api/quotes?symbols=${ALL_SYMBOLS.join(",")}`, {
        cache: "no-store",
      });
      if (!res.ok) throw new Error("quotes failed");
      const j = await res.json();
      setQuotes(j.quotes || {});
      setUpdated(new Date());
      setState("ok");
      firstLoad.current = false;
    } catch {
      if (firstLoad.current) setState("err");
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    load();
    const timer = setInterval(load, REFRESH_MS);
    // A tab left open in the background stops getting timers on some browsers;
    // refresh the moment it comes back so the numbers are never quietly stale.
    const onVisible = () => {
      if (document.visibilityState === "visible") load();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [load]);

  const basket = BASKETS.find((b) => b.key === basketKey) || BASKETS[0];

  const rows = useMemo(() => {
    const list = basket.picks.map((p: Pick) => {
      const q = quotes[p.symbol];
      const price = q?.price ?? null;
      const ret = price != null ? ((price - p.entry) / p.entry) * 100 : null;
      return { p, q, price, ret };
    });
    const dir = (a: number | null, b: number | null) =>
      (b ?? -Infinity) - (a ?? -Infinity); // nulls last
    if (sort === "ret") list.sort((a, b) => dir(a.ret, b.ret));
    else if (sort === "day") list.sort((a, b) => dir(a.q?.day_pct ?? null, b.q?.day_pct ?? null));
    else list.sort((a, b) => a.p.rank - b.p.rank);
    return list;
  }, [basket, quotes, sort]);

  // Equal-weight basket return: the average of the individual returns, which is
  // what you would get putting the same amount into each name on 2026-09-18.
  const stats = useMemo(() => {
    const priced = rows.filter((r) => r.ret != null) as { p: Pick; ret: number }[];
    if (priced.length === 0) return null;
    const avg = priced.reduce((s, r) => s + r.ret, 0) / priced.length;
    const sorted = [...priced].sort((a, b) => b.ret - a.ret);
    return {
      avg,
      n: priced.length,
      up: priced.filter((r) => r.ret > 0).length,
      down: priced.filter((r) => r.ret < 0).length,
      best: sorted[0],
      worst: sorted[sorted.length - 1],
    };
  }, [rows]);

  // Yahoo's chart meta only sometimes carries marketState, so fall back to the
  // freshness of the last trade: a quote stamped within the last 10 minutes
  // means some exchange on this list is still trading.
  const live = useMemo(() => {
    const qs = Object.values(quotes);
    if (qs.some((q) => q?.market_state === "REGULAR")) return true;
    if (qs.some((q) => q?.market_state && q.market_state !== "REGULAR")) return false;
    const now = Date.now();
    return qs.some((q) => q?.quote_time != null && now - q.quote_time < 10 * 60_000);
  }, [quotes]);

  return (
    <div className="pk">
      <div className="pk-bar">
        <div className="pk-tabs" role="tablist" aria-label="Basket">
          {BASKETS.map((b) => (
            <button
              key={b.key}
              role="tab"
              aria-selected={b.key === basketKey}
              className={"pk-tab" + (b.key === basketKey ? " on" : "")}
              onClick={() => setBasketKey(b.key)}
            >
              {b.label}
            </button>
          ))}
        </div>
        <div className="pk-meta">
          <span className={"pk-dot" + (live ? " live" : "")} aria-hidden="true" />
          <span>
            {live ? "Market open" : "Market closed"}
            {updated && ` · updated ${updated.toLocaleTimeString()}`}
          </span>
          <button className="pk-refresh" onClick={load} disabled={busy}>
            {busy ? "Refreshing…" : "Refresh"}
          </button>
        </div>
      </div>

      <p className="pk-blurb">
        {basket.blurb} Entry price is the <strong>{ENTRY_DATE} close</strong>; every return
        below is measured against it and updates while the market is open.
      </p>

      {state === "err" && (
        <div className="pk-state" role="alert">
          <h3>We couldn&apos;t reach the quote feed.</h3>
          <p>The entry prices below are unaffected. Try again in a moment.</p>
          <button className="pk-refresh" onClick={load}>Try again</button>
        </div>
      )}
      {state === "loading" && <div className="pk-state" role="status">Loading live prices…</div>}

      {state === "ok" && stats && (
        <div className="pk-cards">
          <div className={"pk-card big" + tone(stats.avg)}>
            <span className="pk-card-k">Basket return</span>
            <span className="pk-card-v">{pct(stats.avg)}</span>
            <span className="pk-card-s">equal weight · {stats.n} of {basket.picks.length} priced</span>
          </div>
          <div className="pk-card">
            <span className="pk-card-k">Up / down</span>
            <span className="pk-card-v">
              <span className="up">{stats.up}</span> / <span className="down">{stats.down}</span>
            </span>
            <span className="pk-card-s">since {ENTRY_DATE}</span>
          </div>
          <div className={"pk-card" + tone(stats.best.ret)}>
            <span className="pk-card-k">Best</span>
            <span className="pk-card-v">{pct(stats.best.ret)}</span>
            <span className="pk-card-s">{stats.best.p.company}</span>
          </div>
          <div className={"pk-card" + tone(stats.worst.ret)}>
            <span className="pk-card-k">Worst</span>
            <span className="pk-card-v">{pct(stats.worst.ret)}</span>
            <span className="pk-card-s">{stats.worst.p.company}</span>
          </div>
        </div>
      )}

      <div className="pk-tablewrap">
        <table className="pk-table">
          <thead>
            <tr>
              <th className="pk-num">
                <button className={"pk-sort" + (sort === "rank" ? " on" : "")} onClick={() => setSort("rank")}>
                  #
                </button>
              </th>
              <th>Company</th>
              <th className="pk-hide-sm">Ticker</th>
              <th className="pk-r">Entry ({ENTRY_DATE.slice(5)})</th>
              <th className="pk-r">Last</th>
              <th className="pk-r">
                <button className={"pk-sort" + (sort === "ret" ? " on" : "")} onClick={() => setSort("ret")}>
                  vs entry
                </button>
              </th>
              <th className="pk-r pk-hide-sm">
                <button className={"pk-sort" + (sort === "day" ? " on" : "")} onClick={() => setSort("day")}>
                  Day
                </button>
              </th>
              <th className="pk-hide-md">Why it is on the list</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(({ p, q, price, ret }) => (
              <tr key={p.symbol} onClick={() => onOpen(p.company)} tabIndex={0}
                  onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onOpen(p.company); } }}
                  title={`Open ${p.company}`}>
                <td className="pk-num">{p.rank}</td>
                <td className="pk-co">
                  <span className="co-link">{p.company}</span>
                  {p.currency === "KRW" && <span className="pk-flag">KR</span>}
                </td>
                <td className="pk-hide-sm pk-mono">{p.ticker}</td>
                <td className="pk-r pk-mono">{money(p.entry, p.currency)}</td>
                <td className="pk-r pk-mono">{money(price, p.currency)}</td>
                <td className={"pk-r pk-mono pk-ret" + tone(ret)}>{pct(ret)}</td>
                <td className={"pk-r pk-mono pk-hide-sm" + tone(q?.day_pct)}>{pct(q?.day_pct)}</td>
                <td className="pk-note pk-hide-md">{p.note}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <PicksUniverse
        basketKey={basket.key}
        pickSymbols={new Set(basket.picks.map((p) => p.symbol))}
        onOpen={onOpen}
      />

      <p className="pk-foot">
        Click any row to open that company&apos;s panel — live chart, the signals on file, and
        its place in the supply chain. Korean names are measured in won, so the basket return
        ignores the currency move. Research, not investment advice.
      </p>
    </div>
  );
}
