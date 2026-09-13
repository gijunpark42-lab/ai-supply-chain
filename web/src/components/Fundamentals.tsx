"use client";

// Fundamentals — a one-row strip of valuation metrics (PE, Fwd PE, PB, EV/EBITDA, ...)
// shown under the price chart in the node panel. Data comes from /api/fundamentals
// (Naver / Yahoo Japan / TWSE / Yahoo Finance by market). Renders nothing while loading or if Yahoo has no data,
// so a company without coverage just shows the chart as before.

import { useEffect, useState } from "react";
import type { Fundamentals as F } from "@/lib/types";

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

export default function Fundamentals({
  ticker,
  exchange,
}: {
  ticker: string;
  exchange: string | null;
}) {
  const [data, setData] = useState<F | null>(null);

  useEffect(() => {
    setData(null);
    const q = new URLSearchParams({ ticker, ...(exchange ? { exchange } : {}) });
    let alive = true; // ignore late responses after the panel switches company
    const load = () =>
      fetch(`/api/fundamentals?${q}`)
        .then((r) => (r.ok ? r.json() : null))
        .then((d: F | null) => { if (alive && d) setData(d); })
        .catch(() => {});
    load();
    // Live refresh: P/E, P/B etc. move with the price, so re-pull every 30 s
    // while this panel stays open. Cleared when the company changes / panel closes.
    const timer = setInterval(load, REFRESH_MS);
    return () => { alive = false; clearInterval(timer); };
  }, [ticker, exchange]);

  if (!data) return null;

  const cells: [string, string, string][] = [
    ["P/E", x(data.trailing_pe), "Trailing 12-month P/E"],
    ["Fwd P/E", x(data.forward_pe), "Forward P/E (next fiscal year consensus EPS)"],
    ["PEG", data.peg == null ? "—" : data.peg.toFixed(2), "PEG ratio"],
    ["P/B", x(data.pb), "Price / book"],
    ["P/S", x(data.ps), "Price / sales (TTM)"],
    ["EV/EBITDA", x(data.ev_ebitda), "Enterprise value / EBITDA"],
    ["ROE", pct(data.roe), "Return on equity"],
    ["Rev g", pct(data.revenue_growth), "Revenue growth, latest quarter YoY"],
    ["GM", pct(data.gross_margin), "Gross margin (TTM)"],
    ["OPM", pct(data.op_margin), "Operating margin (TTM)"],
  ];
  if (data.dividend_yield) cells.push(["Div", pct(data.dividend_yield), "Dividend yield"]);
  if (data.target_mean != null)
    cells.push([
      "Target",
      data.target_mean.toLocaleString(undefined, { maximumFractionDigits: 0 }) +
        (data.analysts ? ` (${data.analysts})` : ""),
      "Analyst mean price target (number of analysts)",
    ]);

  return (
    <div className="fund">
      {cells.map(([k, v, tip]) => (
        <div className="fund-cell" key={k} title={tip}>
          <span className="fund-k">{k}</span>
          <span className="fund-v">{v}</span>
        </div>
      ))}
      <div className="fund-src">{data.sources.join(" + ")} · {data.as_of}</div>
    </div>
  );
}
