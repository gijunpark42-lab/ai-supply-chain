"use client";

// SeriesChart — a small hand-written SVG chart for several daily time series
// that share ONE unit (one y-axis; never two scales on one chart).
//
// Same approach as LiveQuote.tsx: each series is a list of [date, value]
// points, scaled into an SVG path, with a crosshair + readout on hover. The
// differences: several lines, a legend that doubles as the readout (latest
// values by default, the hovered day's values while hovering), and the SVG is
// drawn at the container's real pixel width so the axis text stays readable on
// a phone instead of shrinking with a viewBox.
//
// Colours follow the series' POSITION in `lines` (slot 1 = first line), so the
// caller must keep that order stable; at most MAX_LINES lines are drawn.

import { useLayoutEffect, useMemo, useRef, useState } from "react";
import { useLang } from "@/lib/i18n";
import "./SeriesChart.css";

export interface ChartLine {
  id: string;
  label: string;
  points: [string, number][];
}

// Categorical palette stepped for a dark surface, in a fixed CVD-checked order.
// A ninth series never gets a generated colour: split it into another chart.
export const SERIES_COLORS = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"];
export const MAX_LINES = SERIES_COLORS.length;

const H = 220;
const PAD = { l: 8, r: 58, t: 12, b: 24 };

/** Default number format: fewer decimals for bigger numbers. */
export function fmtValue(v: number): string {
  const a = Math.abs(v);
  const digits = a >= 1000 ? 0 : a >= 1 ? 2 : 4;
  return v.toLocaleString("en-US", { maximumFractionDigits: digits });
}

// "2026-10-17" → milliseconds (UTC midnight, so no time-zone drift).
const dayMs = (d: string) => Date.parse(d + "T00:00:00Z");

// About four round-numbered y ticks ("nice" steps of 1, 2 or 5 × 10^n).
function niceTicks(lo: number, hi: number): { lo: number; hi: number; ticks: number[] } {
  if (hi === lo) {
    const pad = Math.abs(lo) * 0.05 || 1;
    lo -= pad;
    hi += pad;
  }
  const raw = (hi - lo) / 4;
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const n = raw / mag;
  const step = (n < 1.5 ? 1 : n < 3 ? 2 : n < 7 ? 5 : 10) * mag;
  const start = Math.floor(lo / step) * step;
  const end = Math.ceil(hi / step) * step;
  const ticks: number[] = [];
  for (let v = start; v <= end + step / 2; v += step) ticks.push(Number(v.toPrecision(12)));
  return { lo: start, hi: end, ticks };
}

export default function SeriesChart({
  lines,
  unit,
  label,
  format = fmtValue,
}: {
  lines: ChartLine[];
  /** Shown after every value ("USD/hr"). */
  unit: string;
  /** What the chart shows, for screen readers. */
  label: string;
  format?: (v: number) => string;
}) {
  const { t } = useLang();
  // Memoised so the geometry below is only rebuilt when the data changes.
  const shown = useMemo(() => lines.slice(0, MAX_LINES), [lines]);

  // Draw at the container's real width (falls back to 640 before measuring).
  const wrapRef = useRef<HTMLDivElement>(null);
  const [W, setW] = useState(640);
  useLayoutEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const measure = () => setW(Math.max(260, Math.round(el.clientWidth)));
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Index into `dates` of the hovered day (null = not hovering).
  const [hover, setHover] = useState<number | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);

  const geom = useMemo(() => {
    // Every day that has at least one reading, oldest first.
    const dates = [...new Set(shown.flatMap((l) => l.points.map((p) => p[0])))].sort();
    if (dates.length < 2) return null;
    const values = shown.flatMap((l) => l.points.map((p) => p[1]));
    const y = niceTicks(Math.min(...values), Math.max(...values));
    const x0 = dayMs(dates[0]);
    const x1 = dayMs(dates[dates.length - 1]);
    const iw = W - PAD.l - PAD.r;
    const ih = H - PAD.t - PAD.b;
    const px = (d: string) => PAD.l + ((dayMs(d) - x0) / (x1 - x0 || 1)) * iw;
    const py = (v: number) => PAD.t + (1 - (v - y.lo) / (y.hi - y.lo || 1)) * ih;
    const paths = shown.map((l) => {
      const pts = [...l.points].sort((a, b) => (a[0] < b[0] ? -1 : 1));
      const d = pts.map((p, i) => (i ? "L" : "M") + px(p[0]).toFixed(1) + " " + py(p[1]).toFixed(1)).join(" ");
      // Value per day, for the hover readout.
      const byDate = new Map(pts.map((p) => [p[0], p[1]] as const));
      return { id: l.id, d, single: pts.length === 1 ? pts[0] : null, byDate };
    });
    const xs = dates.map(px);
    return { dates, xs, paths, px, py, y };
  }, [shown, W]);

  // Nearest day to the pointer.
  function pickAt(clientX: number) {
    if (!geom || !svgRef.current) return;
    const rect = svgRef.current.getBoundingClientRect();
    const x = ((clientX - rect.left) / rect.width) * W;
    let best = 0;
    let bd = Infinity;
    geom.xs.forEach((gx, i) => {
      const d = Math.abs(gx - x);
      if (d < bd) {
        bd = d;
        best = i;
      }
    });
    setHover(best);
  }

  // Arrow keys walk the days when the chart has focus.
  function onKey(e: React.KeyboardEvent) {
    if (!geom) return;
    const last = geom.dates.length - 1;
    if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
      e.preventDefault();
      const cur = hover ?? last;
      setHover(Math.max(0, Math.min(last, cur + (e.key === "ArrowRight" ? 1 : -1))));
    } else if (e.key === "Escape") {
      setHover(null);
    }
  }

  // The legend row: the hovered day's values, or each line's latest value.
  const hoverDate = geom && hover !== null ? geom.dates[hover] : null;
  const readout = shown.map((l, i) => {
    let value: number | null = null;
    let date: string | null = null;
    if (hoverDate) {
      const v = geom?.paths[i].byDate.get(hoverDate);
      if (v !== undefined) {
        value = v;
        date = hoverDate;
      }
    } else if (l.points.length) {
      const lastPt = l.points.reduce((a, b) => (b[0] > a[0] ? b : a));
      value = lastPt[1];
      date = lastPt[0];
    }
    return { id: l.id, label: l.label, color: SERIES_COLORS[i], value, date };
  });

  return (
    <div className="sc" ref={wrapRef}>
      <div className="sc-legend" aria-live="polite">
        <span className="sc-legend-date">{hoverDate || t("Latest")}</span>
        {readout.map((r) => (
          <span className="sc-legend-item" key={r.id}>
            <span className="sc-swatch" style={{ background: r.color }} aria-hidden="true" />
            <span className="sc-legend-label">{r.label}</span>
            <span className="sc-legend-value">
              {r.value === null ? "—" : `${format(r.value)} ${unit}`}
            </span>
          </span>
        ))}
      </div>

      {!geom && <p className="caption sc-empty">{t("The chart appears once two days of readings are recorded.")}</p>}

      {geom && (
        <svg
          ref={svgRef}
          className="sc-svg"
          width={W}
          height={H}
          viewBox={`0 0 ${W} ${H}`}
          role="img"
          aria-label={label}
          tabIndex={0}
          onPointerMove={(e) => pickAt(e.clientX)}
          onPointerDown={(e) => pickAt(e.clientX)}
          onPointerLeave={() => setHover(null)}
          onKeyDown={onKey}
          onBlur={() => setHover(null)}
        >
          {/* Recessive grid + right-hand y labels. */}
          {geom.y.ticks.map((v) => (
            <g key={v}>
              <line x1={PAD.l} x2={W - PAD.r} y1={geom.py(v)} y2={geom.py(v)} className="sc-grid" />
              <text x={W - PAD.r + 6} y={geom.py(v) + 3.5} className="sc-axt">
                {format(v)}
              </text>
            </g>
          ))}
          {/* First / middle / last day under the plot. */}
          <text x={PAD.l} y={H - 6} className="sc-axt">{geom.dates[0]}</text>
          {W >= 420 && geom.dates.length > 2 && (
            <text x={geom.xs[Math.floor(geom.dates.length / 2)]} y={H - 6} className="sc-axt" textAnchor="middle">
              {geom.dates[Math.floor(geom.dates.length / 2)]}
            </text>
          )}
          <text x={W - PAD.r} y={H - 6} className="sc-axt" textAnchor="end">
            {geom.dates[geom.dates.length - 1]}
          </text>

          {geom.paths.map((p, i) =>
            p.single ? (
              <circle key={p.id} cx={geom.px(p.single[0])} cy={geom.py(p.single[1])} r={4} fill={SERIES_COLORS[i]} />
            ) : (
              <path key={p.id} d={p.d} fill="none" stroke={SERIES_COLORS[i]} strokeWidth={2}
                strokeLinejoin="round" strokeLinecap="round" />
            )
          )}

          {hoverDate && hover !== null && (
            <>
              <line x1={geom.xs[hover]} x2={geom.xs[hover]} y1={PAD.t} y2={H - PAD.b} className="sc-cross" />
              {geom.paths.map((p, i) => {
                const v = p.byDate.get(hoverDate);
                return v === undefined ? null : (
                  <circle key={p.id} cx={geom.xs[hover]} cy={geom.py(v)} r={4} fill={SERIES_COLORS[i]}
                    className="sc-dot" />
                );
              })}
            </>
          )}
        </svg>
      )}
      {lines.length > MAX_LINES && (
        <p className="caption">{t("{n} more series are listed in the table below.", { n: lines.length - MAX_LINES })}</p>
      )}
    </div>
  );
}
