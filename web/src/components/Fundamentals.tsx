"use client";

// Fundamentals — a one-row strip of valuation metrics (Mkt cap, PE, Fwd PE, PB, EV/EBITDA, ...)
// shown under the price chart in the node panel. Ratios come from /api/fundamentals
// (Naver / Yahoo Japan / TWSE / Yahoo Finance by market); the market cap box (first) and
// the ADR premium box (last, ADR nodes only) come from /api/mcap. Renders nothing while
// loading or if neither has data, so a company without coverage just shows the chart.

import { useEffect, useState } from "react";
import type { Fundamentals as F, MarketCap as M } from "@/lib/types";
import { CUR } from "./LiveQuote";
import { useLang } from "@/lib/i18n";

const REFRESH_MS = 30_000; // auto-refresh interval while the panel is open

// Format a ratio like 27.6 → "27.6x"; null → "—".
function x(v: number | null): string {
  if (v == null) return "—";
  if (Math.abs(v) >= 1000) return "n/m"; // not meaningful (loss-making, broken data)
  return v.toFixed(1) + "x";
}
// Format a fraction like 0.39 → "39%".
function pct(v: number | null): string {
  return v == null ? "—" : (v * 100).toFixed(0) + "%";
}
// Market cap: 1.261e15 KRW → "₩1,261T", 2.112e12 USD → "$2.11T", 9.42e11 → "$942.4B".
function cap(v: number, cur: string): string {
  const sym = CUR[cur] || cur + " ";
  const [n, unit] = v >= 1e12 ? [v / 1e12, "T"] : v >= 1e9 ? [v / 1e9, "B"] : [v / 1e6, "M"];
  const d = n >= 1000 ? 0 : n >= 100 ? 1 : 2;
  return sym + n.toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d }) + unit;
}

export default function Fundamentals({
  ticker,
  exchange,
}: {
  ticker: string;
  exchange: string | null;
}) {
  const { t } = useLang();
  const [data, setData] = useState<F | null>(null);
  const [mcap, setMcap] = useState<M | null>(null);

  useEffect(() => {
    setData(null);
    setMcap(null);
    const q = new URLSearchParams({ ticker, ...(exchange ? { exchange } : {}) });
    let alive = true; // ignore late responses after the panel switches company
    const load = () => {
      fetch(`/api/fundamentals?${q}`)
        .then((r) => (r.ok ? r.json() : null))
        .then((d: F | null) => { if (alive && d) setData(d); })
        .catch(() => {});
      fetch(`/api/mcap?${q}`)
        .then((r) => (r.ok ? r.json() : null))
        .then((d: M | null) => { if (alive && d) setMcap(d); })
        .catch(() => {});
    };
    load();
    // Live refresh: P/E, P/B etc. move with the price, so re-pull every 30 s
    // while this panel stays open. Cleared when the company changes / panel closes.
    const timer = setInterval(load, REFRESH_MS);
    return () => { alive = false; clearInterval(timer); };
  }, [ticker, exchange]);

  if (!data && !mcap) return null;

  // [label, value, tooltip, optional second line]
  const cells: [string, string, string, string?][] = [];
  if (mcap) {
    const foreign = mcap.currency !== "USD";
    const tip = [
      mcap.adr && t("Valued on the home listing {symbol}, not the US-listed {adr}", { symbol: mcap.symbol, adr: mcap.adr }),
      foreign && mcap.fx && t("USD at the live rate: 1 USD = {rate} {cur}", {
        rate: mcap.fx.toLocaleString(undefined, { maximumFractionDigits: 4 }),
        cur: mcap.currency,
      }),
    ].filter(Boolean).join(" · ");
    cells.push([
      "Mkt cap",
      cap(mcap.market_cap, mcap.currency),
      tip || t("Market capitalisation"),
      foreign && mcap.market_cap_usd != null ? "≈ " + cap(mcap.market_cap_usd, "USD") : undefined,
    ]);
  }
  if (data) cells.push(
    ["P/E", x(data.trailing_pe), t("Trailing 12-month P/E")],
    ["Fwd P/E", x(data.forward_pe), t("Forward P/E (next fiscal year consensus EPS)")],
    ["PEG", data.peg == null ? "—" : data.peg.toFixed(2), t("PEG ratio")],
    ["P/B", x(data.pb), t("Price / book")],
    ["P/S", x(data.ps), t("Price / sales (TTM)")],
    ["EV/EBITDA", x(data.ev_ebitda), t("Enterprise value / EBITDA")],
    ["ROE", pct(data.roe), t("Return on equity")],
    ["Rev g", pct(data.revenue_growth), t("Revenue growth, latest quarter YoY")],
    ["GM", pct(data.gross_margin), t("Gross margin (TTM)")],
    ["OPM", pct(data.op_margin), t("Operating margin (TTM)")],
  );
  if (data?.dividend_yield) cells.push(["Div", pct(data.dividend_yield), t("Dividend yield")]);
  if (data?.target_mean != null)
    cells.push([
      "Target",
      data.target_mean.toLocaleString(undefined, { maximumFractionDigits: 0 }) +
        (data.analysts ? ` (${data.analysts})` : ""),
      t("Analyst mean price target (number of analysts)"),
    ]);
  // Last, so every other box keeps its place across companies: only ADR nodes have it.
  if (mcap?.adr && mcap.adr_premium != null) {
    const p = mcap.adr_premium * 100;
    cells.push([
      "ADR premium",
      (p >= 0 ? "+" : "−") + Math.abs(p).toFixed(1) + "%",
      t("How far the US-listed {adr} trades above (+) or below (−) the home shares {symbol}, both in USD at the live rate", {
        adr: mcap.adr,
        symbol: mcap.symbol,
      }),
      t("vs {symbol}", { symbol: mcap.symbol }),
    ]);
  }

  const sources = [...(data?.sources || [])];
  if (mcap && !sources.includes("Yahoo Finance")) sources.push("Yahoo Finance");

  return (
    <div className="fund">
      {cells.map(([k, v, tip, sub]) => (
        <div className="fund-cell" key={k} title={tip}>
          <span className="fund-k">{t(k)}</span>
          <span className="fund-v">{v}</span>
          {sub && <span className="fund-sub">{sub}</span>}
        </div>
      ))}
      <div className="fund-src">{sources.join(" + ")} · {data?.as_of || mcap?.as_of}</div>
    </div>
  );
}
