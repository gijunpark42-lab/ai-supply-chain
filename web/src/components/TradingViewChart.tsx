"use client";

import { useEffect, useRef } from "react";
import { useLang, type Lang } from "@/lib/i18n";

// The widget's own UI language for each site language.
const TV_LOCALE: Record<Lang, string> = { en: "en", ko: "kr", zh: "zh_CN", ja: "ja" };

// TradingView "Symbol Overview" widget for US-listed tickers (client-side, no
// server fetch). Mirrors app.py mountTV: dark area chart, blue line, range tabs.
export default function TradingViewChart({
  symbol,
}: {
  symbol: string; // e.g. "NASDAQ:NVDA"
}) {
  const { lang } = useLang();
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.innerHTML = "";
    const container = document.createElement("div");
    container.className = "tradingview-widget-container";
    const widget = document.createElement("div");
    widget.className = "tradingview-widget-container__widget";
    container.appendChild(widget);
    el.appendChild(container);

    const script = document.createElement("script");
    script.src =
      "https://s3.tradingview.com/external-embedding/embed-widget-symbol-overview.js";
    script.async = true;
    script.innerHTML = JSON.stringify({
      symbols: [[symbol]],
      chartOnly: false,
      width: "100%",
      height: 300,
      locale: TV_LOCALE[lang],
      colorTheme: "dark",
      isTransparent: true,
      autosize: false,
      showVolume: false,
      lineColor: "rgba(41,151,255,1)",
      topColor: "rgba(41,151,255,0.25)",
      bottomColor: "rgba(41,151,255,0)",
      dateRanges: ["1d|1", "1w|30", "1m|1D", "12m|1D", "60m|1W", "all|1M"],
      fontColor: "#9aa0a8",
      gridLineColor: "rgba(255,255,255,0.06)",
    });
    container.appendChild(script);

    return () => {
      el.innerHTML = "";
    };
  }, [symbol, lang]);

  return <div ref={ref} style={{ height: 300 }} />;
}
