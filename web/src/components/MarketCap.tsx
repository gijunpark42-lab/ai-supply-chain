"use client";

// MarketCap — the live market-cap line under the price chart in the node panel.
// A non-USD listing shows two figures: the cap in its own currency and the USD value
// at the live FX rate. ADR nodes are valued on their home listing (TSM → 2330.TW).
// Data comes from /api/mcap, re-pulled every 30 s like the price and the ratios.
// Renders nothing while loading or when Yahoo has no market cap.

import { useEffect, useState } from "react";
import { CUR } from "./LiveQuote";
import { useLang } from "@/lib/i18n";

const REFRESH_MS = 30_000; // auto-refresh interval while the panel is open

interface MCap {
  symbol: string;
  adr: string | null;
  currency: string;
  market_cap: number;
  market_cap_usd: number | null;
  fx: number | null;
  as_of: string;
}

// 1.261e15 KRW → "₩1,261T", 2.112e12 USD → "$2.11T", 9.42e11 → "$942.4B".
function fmtCap(v: number, cur: string): string {
  const sym = CUR[cur] || cur + " ";
  const [n, unit] = v >= 1e12 ? [v / 1e12, "T"] : v >= 1e9 ? [v / 1e9, "B"] : [v / 1e6, "M"];
  const d = n >= 1000 ? 0 : n >= 100 ? 1 : 2;
  return sym + n.toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d }) + unit;
}

export default function MarketCap({
  ticker,
  exchange,
}: {
  ticker: string;
  exchange: string | null;
}) {
  const { t } = useLang();
  const [data, setData] = useState<MCap | null>(null);

  useEffect(() => {
    setData(null);
    const q = new URLSearchParams({ ticker, ...(exchange ? { exchange } : {}) });
    let alive = true; // ignore late responses after the panel switches company
    const load = () =>
      fetch(`/api/mcap?${q}`)
        .then((r) => (r.ok ? r.json() : null))
        .then((d: MCap | null) => { if (alive && d) setData(d); })
        .catch(() => {});
    load();
    const timer = setInterval(load, REFRESH_MS);
    return () => { alive = false; clearInterval(timer); };
  }, [ticker, exchange]);

  if (!data) return null;

  const foreign = data.currency !== "USD";
  const tip = [
    data.adr && t("Valued on the home listing {symbol}, not the US-listed {adr}", { symbol: data.symbol, adr: data.adr }),
    foreign && data.fx && t("USD at the live rate: 1 USD = {rate} {cur}", {
      rate: data.fx.toLocaleString(undefined, { maximumFractionDigits: 4 }),
      cur: data.currency,
    }),
    data.as_of,
  ].filter(Boolean).join(" · ");

  return (
    <div className="mcap" title={tip}>
      <span className="mcap-k">{t("Mkt cap")}</span>
      <span className="mcap-v">{fmtCap(data.market_cap, data.currency)}</span>
      {foreign && data.market_cap_usd != null && (
        <span className="mcap-v mcap-usd">≈ {fmtCap(data.market_cap_usd, "USD")}</span>
      )}
      {data.adr && <span className="mcap-src">{t("{symbol} home shares", { symbol: data.symbol })}</span>}
    </div>
  );
}
