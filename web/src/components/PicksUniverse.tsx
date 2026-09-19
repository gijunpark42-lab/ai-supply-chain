"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { fetchJson } from "@/lib/data";
import { ENTRY_DATE, money, pct, tone, type Quotes } from "@/lib/picks";

// One screened company in /data/picks_universe.json — every listed name the
// screen scored, not just the 15 that made a basket.
interface URow {
  company: string; // graph node id → a click opens its NodePanel
  ticker: string;
  symbol: string; // Yahoo symbol
  market: "US" | "KR";
  currency: "USD" | "KRW";
  entry: number; // 2026-09-18 close
  hi: number; // % versus the 6-month high on the entry date
  score: number; // 0-10 one-quarter score from the screen
}

const CHUNK = 40; // /api/quotes takes at most 40 symbols a call
const REFRESH_MS = 5 * 60_000; // 200+ symbols: refresh gently, not every minute

type SortKey = "score" | "ret";

export default function PicksUniverse({
  basketKey,
  pickSymbols,
  onOpen,
}: {
  basketKey: string; // "us" → US names only, "global" → US + Korea
  pickSymbols: Set<string>; // the current basket's 15, to badge them in the list
  onOpen: (company: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [all, setAll] = useState<URow[] | null>(null);
  const [err, setErr] = useState(false);
  const [quotes, setQuotes] = useState<Quotes>({});
  const [priced, setPriced] = useState(0); // progress while the chunks come in
  const [sort, setSort] = useState<SortKey>("score");
  const loading = useRef(false);

  const list = useMemo(
    () => (all ? all.filter((r) => basketKey === "global" || r.market === "US") : []),
    [all, basketKey]
  );
  const total = basketKey === "global" ? 213 : 178; // shown on the button before the file loads

  // The list itself is a static file, fetched the first time the panel opens.
  useEffect(() => {
    if (!open || all) return;
    fetchJson<{ rows: URow[] }>("/data/picks_universe.json")
      .then((j) => setAll(j.rows))
      .catch(() => setErr(true));
  }, [open, all]);

  // Live prices, one chunk after another so a 213-name list is six modest
  // requests rather than one burst of 213 upstream fetches.
  const loadQuotes = useCallback(async (rows: URow[]) => {
    if (loading.current || rows.length === 0) return;
    loading.current = true;
    try {
      const symbols = rows.map((r) => r.symbol);
      for (let i = 0; i < symbols.length; i += CHUNK) {
        const res = await fetch(`/api/quotes?symbols=${symbols.slice(i, i + CHUNK).join(",")}`, {
          cache: "no-store",
        });
        if (!res.ok) continue;
        const j = await res.json();
        setQuotes((prev) => ({ ...prev, ...(j.quotes || {}) }));
        setPriced(Math.min(i + CHUNK, symbols.length));
      }
    } finally {
      loading.current = false;
    }
  }, []);

  useEffect(() => {
    if (!open || list.length === 0) return;
    loadQuotes(list);
    const timer = setInterval(() => loadQuotes(list), REFRESH_MS);
    return () => clearInterval(timer);
  }, [open, list, loadQuotes]);

  const rows = useMemo(() => {
    const out = list.map((r, i) => {
      const price = quotes[r.symbol]?.price ?? null;
      return { r, pos: i + 1, price, ret: price != null ? ((price - r.entry) / r.entry) * 100 : null };
    });
    if (sort === "ret") out.sort((a, b) => (b.ret ?? -Infinity) - (a.ret ?? -Infinity));
    return out; // the file is already ordered by score
  }, [list, quotes, sort]);

  return (
    <div className="pk-uni">
      <button
        className="pk-uni-toggle"
        aria-expanded={open}
        aria-controls="pk-uni-panel"
        onClick={() => setOpen((o) => !o)}
      >
        <span>{open ? "Hide" : "Show"} all {total} screened companies</span>
        <span className={"pk-uni-caret" + (open ? " open" : "")} aria-hidden="true">▾</span>
      </button>

      {open && (
        <div id="pk-uni-panel">
          {err && <div className="pk-state" role="alert">We couldn&apos;t load the screened list. Try again in a moment.</div>}
          {!err && !all && <div className="pk-state" role="status">Loading the full list…</div>}
          {all && (
            <>
              <p className="pk-blurb pk-uni-blurb">
                Every company the screen scored, best first. <strong>Score</strong> is the 0–10
                one-quarter rating; <strong>Off high</strong> is how far the stock sat below its
                6-month high at the {ENTRY_DATE} close.
                {priced < list.length && ` Pricing ${priced} of ${list.length}…`}
              </p>
              <div className="pk-tablewrap pk-uni-wrap">
                <table className="pk-table">
                  <thead>
                    <tr>
                      <th className="pk-num">#</th>
                      <th>Company</th>
                      <th className="pk-hide-sm">Ticker</th>
                      <th className="pk-r">
                        <button className={"pk-sort" + (sort === "score" ? " on" : "")} onClick={() => setSort("score")}>
                          Score
                        </button>
                      </th>
                      <th className="pk-r pk-hide-sm">Entry ({ENTRY_DATE.slice(5)})</th>
                      <th className="pk-r">Last</th>
                      <th className="pk-r">
                        <button className={"pk-sort" + (sort === "ret" ? " on" : "")} onClick={() => setSort("ret")}>
                          vs entry
                        </button>
                      </th>
                      <th className="pk-r pk-hide-sm">Off high</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map(({ r, pos, price, ret }) => (
                      <tr key={r.company} onClick={() => onOpen(r.company)} tabIndex={0}
                          onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onOpen(r.company); } }}
                          title={`Open ${r.company}`}>
                        <td className="pk-num">{pos}</td>
                        <td className="pk-co">
                          <span className="co-link">{r.company}</span>
                          {r.market === "KR" && <span className="pk-flag">KR</span>}
                          {pickSymbols.has(r.symbol) && <span className="pk-flag pk-flag-top">TOP 15</span>}
                        </td>
                        <td className="pk-hide-sm pk-mono">{r.ticker}</td>
                        <td className="pk-r pk-mono pk-score">{r.score.toFixed(1)}</td>
                        <td className="pk-r pk-mono pk-hide-sm">{money(r.entry, r.currency)}</td>
                        <td className="pk-r pk-mono">{money(price, r.currency)}</td>
                        <td className={"pk-r pk-mono pk-ret" + tone(ret)}>{pct(ret)}</td>
                        <td className="pk-r pk-mono pk-hide-sm">{pct(r.hi, 0)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
