"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { LiveQuote as LQ } from "@/lib/types";

const RANGES = ["1D", "1W", "1M", "YTD", "1Y", "5Y", "All"];
const REFRESH_MS = 30_000; // auto-refresh interval while the panel is open
const CUR: Record<string, string> = {
  USD: "$", EUR: "€", GBP: "£", JPY: "¥", KRW: "₩", TWD: "NT$", HKD: "HK$", CNY: "¥",
};

const W = 560;
const H = 220;
const PAD = { l: 6, r: 46, t: 10, b: 20 };

function fmtCap(v: number | null, sym: string): string {
  if (!v) return "—";
  if (v >= 1e12) return `${sym}${(v / 1e12).toFixed(2)}T`;
  if (v >= 1e9) return `${sym}${(v / 1e9).toFixed(2)}B`;
  if (v >= 1e6) return `${sym}${(v / 1e6).toFixed(1)}M`;
  return `${sym}${v.toFixed(0)}`;
}

export default function LiveQuote({
  ticker,
  exchange,
}: {
  ticker: string;
  exchange: string | null;
}) {
  const [data, setData] = useState<LQ | null>(null);
  const [state, setState] = useState<"loading" | "ok" | "err">("loading");
  const [range, setRange] = useState("1Y");
  const [hover, setHover] = useState<{ i: number } | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);

  useEffect(() => {
    setState("loading");
    setData(null);
    const q = new URLSearchParams({ ticker, ...(exchange ? { exchange } : {}) });
    let alive = true;
    let first = true;
    const load = () =>
      fetch(`/api/quote?${q}`)
        .then((r) => (r.ok ? r.json() : Promise.reject()))
        .then((d: LQ) => {
          if (!alive) return;
          setData(d);
          setState("ok");
          if (first) {
            first = false;
            // default to 1Y if present, else first available range (first load only —
            // later refreshes must not reset the range the user picked)
            const avail = RANGES.filter((r) => d.series[r]?.length >= 2);
            setRange(avail.includes("1Y") ? "1Y" : avail[avail.length - 1] || "1Y");
          }
        })
        .catch(() => { if (alive && first) setState("err"); });
    load();
    // Live refresh every 30 s while the panel is open.
    const timer = setInterval(load, REFRESH_MS);
    return () => { alive = false; clearInterval(timer); };
  }, [ticker, exchange]);

  const sym = CUR[data?.currency || "USD"] || (data?.currency ? data.currency + " " : "$");
  const series = data?.series[range] || [];

  const geom = useMemo(() => {
    if (series.length < 2) return null;
    const xs = series.map((p) => p[0]);
    const ys = series.map((p) => p[1]);
    const x0 = Math.min(...xs), x1 = Math.max(...xs);
    const y0 = Math.min(...ys), y1 = Math.max(...ys);
    const iw = W - PAD.l - PAD.r;
    const ih = H - PAD.t - PAD.b;
    const px = (x: number) => PAD.l + ((x - x0) / (x1 - x0 || 1)) * iw;
    const py = (y: number) => PAD.t + (1 - (y - y0) / (y1 - y0 || 1)) * ih;
    const pts = series.map((p) => [px(p[0]), py(p[1])] as [number, number]);
    const line = pts.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1)).join(" ");
    const area = `${line} L${pts[pts.length - 1][0].toFixed(1)} ${H - PAD.b} L${pts[0][0].toFixed(1)} ${H - PAD.b} Z`;
    return { pts, line, area, y0, y1, py };
  }, [series]);

  const rangeAvail = (r: string) => (data?.series[r]?.length || 0) >= 2;

  function onMove(e: React.MouseEvent) {
    if (!geom || !svgRef.current) return;
    const rect = svgRef.current.getBoundingClientRect();
    const x = ((e.clientX - rect.left) / rect.width) * W;
    let best = 0, bd = Infinity;
    geom.pts.forEach((p, i) => {
      const d = Math.abs(p[0] - x);
      if (d < bd) { bd = d; best = i; }
    });
    setHover({ i: best });
  }

  const up = (data?.change_pct ?? 0) >= 0;
  const hoverPt = hover && series[hover.i];

  return (
    <div className="lq">
      {state === "loading" && <div className="lq-msg">Loading live quote…</div>}
      {state === "err" && <div className="lq-msg">Live quote unavailable.</div>}
      {state === "ok" && data && (
        <>
          <div className="lq-card">
            <div className="lq-price">
              {sym}
              {data.price?.toLocaleString(undefined, { maximumFractionDigits: 2 })}
            </div>
            {data.change_pct != null && (
              <div className={"lq-chg " + (up ? "up" : "down")}>
                {up ? "▲" : "▼"} {Math.abs(data.change_pct).toFixed(2)}%
              </div>
            )}
            <div className="lq-live">● LIVE · {data.as_of}</div>
            <div className="lq-stats">
              <span>Mkt cap {fmtCap(data.market_cap, sym)}</span>
              {data.year_low != null && data.year_high != null && (
                <span>
                  52-wk {sym}{data.year_low} – {sym}{data.year_high}
                </span>
              )}
            </div>
          </div>

          <div className="lq-ranges">
            {RANGES.map((r) => (
              <button
                key={r}
                className={"lq-rbtn" + (r === range ? " on" : "")}
                disabled={!rangeAvail(r)}
                onClick={() => { setRange(r); setHover(null); }}
              >
                {r}
              </button>
            ))}
          </div>

          {geom && (
            <svg
              ref={svgRef}
              viewBox={`0 0 ${W} ${H}`}
              className="lq-svg"
              onMouseMove={onMove}
              onMouseLeave={() => setHover(null)}
            >
              <defs>
                <linearGradient id="lqgrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="rgba(41,151,255,0.28)" />
                  <stop offset="100%" stopColor="rgba(41,151,255,0)" />
                </linearGradient>
              </defs>
              <path d={geom.area} fill="url(#lqgrad)" />
              <path d={geom.line} fill="none" stroke="#2997ff" strokeWidth={1.6} />
              {/* y-axis ticks */}
              <text x={W - PAD.r + 4} y={PAD.t + 4} className="lq-axt">{sym}{geom.y1.toFixed(0)}</text>
              <text x={W - PAD.r + 4} y={H - PAD.b} className="lq-axt">{sym}{geom.y0.toFixed(0)}</text>
              {hoverPt && geom && (
                <>
                  <line
                    x1={geom.pts[hover!.i][0]} x2={geom.pts[hover!.i][0]}
                    y1={PAD.t} y2={H - PAD.b}
                    stroke="rgba(255,255,255,0.25)" strokeWidth={1}
                  />
                  <circle cx={geom.pts[hover!.i][0]} cy={geom.pts[hover!.i][1]} r={3.5} fill="#2997ff" />
                  <text
                    x={Math.min(geom.pts[hover!.i][0] + 6, W - PAD.r - 60)}
                    y={PAD.t + 14}
                    className="lq-hov"
                  >
                    {sym}{hoverPt[1]} · {new Date(hoverPt[0]).toLocaleDateString()}
                  </text>
                </>
              )}
            </svg>
          )}
        </>
      )}
    </div>
  );
}
