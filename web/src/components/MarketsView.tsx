"use client";

// MarketsView — the market-level "Markets" tab group (2026-10-17).
//
// Five sections, each shown on its own sub-tab (page.tsx picks one with the
// `section` prop) and drawn from one daily file the nightly collectors write
// (market/*.py → graph/*.json → /data/*.json). No model tokens are involved and
// none of this is a "signal": it never touches quarterly_data or the chains.
//   memory    Memory prices      /data/memory_prices.json
//   gpu       GPU rental prices  /data/gpu_prices.json
//   earnings  Earnings calendar  /data/hyperscaler_cash.json → "calendar"
//   labs      AI labs            /data/ai_labs.json → labs (revenue, funding, deals)
//   models    Model benchmarks   /data/ai_labs.json → models
// Any file may be missing (collector not run yet, source down): that sub-tab
// then shows a one-line "no data yet" note. Every row links back to its source.

import { useEffect, useMemo, useState } from "react";
import type { Resolver } from "@/lib/company";
import {
  loadMarketJson,
  type AiLab,
  type AiLabsFile,
  type EarningsDate,
  type HyperscalerCash,
  type LabDeal,
  type MarketSeries,
  type ModelScores,
  type SeriesFile,
} from "@/lib/marketTypes";
import { sortRows, type CellValue, type SortDir } from "@/lib/table";
import { useLang } from "@/lib/i18n";
import { fmtDay, isRunRate } from "@/lib/companyFeeds";
import CompanyLink from "./CompanyLink";
import CellText from "./CellText";
import SeriesChart, { MAX_LINES, fmtValue, type ChartLine } from "./SeriesChart";
import "./Tables.css";
import "./Markets.css";

// ── Small formatting helpers ───────────────────────────────────────────────

/** Dollars, shortened: $1.25T, $40.0B, $350M, $12,000. */
export function fmtUsd(n: number | null | undefined): string {
  if (n === null || n === undefined || !Number.isFinite(n)) return "—";
  const a = Math.abs(n);
  const sign = n < 0 ? "-" : "";
  if (a >= 1e12) return `${sign}$${(a / 1e12).toLocaleString("en-US", { maximumFractionDigits: 2 })}T`;
  if (a >= 1e9) return `${sign}$${(a / 1e9).toLocaleString("en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 })}B`;
  if (a >= 1e6) return `${sign}$${(a / 1e6).toLocaleString("en-US", { maximumFractionDigits: 0 })}M`;
  return `${sign}$${a.toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
}

/** A change rounded to one decimal; -0.03 counts as 0 (no "-0.0%" in red). */
const roundPct = (n: number) => {
  const r = Math.round(n * 10) / 10;
  return r === 0 ? 0 : r; // also turns -0 into 0
};

/** "+1.2%" / "-0.8%" / "0.0%". */
function fmtPct(n: number): string {
  const r = roundPct(n);
  return `${r > 0 ? "+" : ""}${r.toFixed(1)}%`;
}

/** "2026-10-17" → "10-17-2026" (the site's date form), kept on one line. */
function Day({ iso }: { iso: string | null | undefined }) {
  if (!iso) return <>—</>;
  return <span className="mk-nowrap">{fmtDay(iso)}</span>;
}

const ISO_DAY = /^\d{4}-\d{2}-\d{2}$/;

/** A benchmark score: one decimal (two for small numbers). */
function fmtScore(n: number | undefined): string {
  if (n === undefined || !Number.isFinite(n)) return "—";
  return n.toLocaleString("en-US", { maximumFractionDigits: Math.abs(n) < 10 ? 2 : 1 });
}

/** Today in the viewer's time zone as "YYYY-MM-DD". */
function localToday(): string {
  const d = new Date();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${d.getFullYear()}-${mm}-${dd}`;
}

/** Whole days from `from` to `to` (both "YYYY-MM-DD"). */
function daysBetween(from: string, to: string): number {
  return Math.round((Date.parse(to + "T00:00:00Z") - Date.parse(from + "T00:00:00Z")) / 86_400_000);
}

/** The newest item of a dated list (by its "date" field), or null. */
function newest<T extends { date: string }>(items: T[] | undefined, keep: (x: T) => boolean = () => true): T | null {
  let best: T | null = null;
  for (const x of items || []) if (keep(x) && (!best || x.date > best.date)) best = x;
  return best;
}

/** The bare host of a URL ("www.sec.gov"), or the URL itself if it does not parse. */
function hostOf(url: string): string {
  try {
    return new URL(url).hostname;
  } catch {
    return url;
  }
}

/** A source link ("DRAMeXchange ↗"); plain text when there is no URL. */
function SrcLink({ name, url }: { name: string; url?: string | null }) {
  if (!url) return <span className="mk-src">{name || "—"}</span>;
  return (
    <a className="mk-src" href={url} target="_blank" rel="noopener noreferrer">
      {name || hostOf(url)} ↗
    </a>
  );
}

/** Column widths (in relative units) for a fixed-layout table. */
function Cols({ w }: { w: number[] }) {
  const sum = w.reduce((a, b) => a + b, 0);
  return (
    <colgroup>
      {w.map((x, i) => (
        <col key={i} style={{ width: `${((x / sum) * 100).toFixed(2)}%` }} />
      ))}
    </colgroup>
  );
}

// ── What counts as "has data" (a section with nothing renders nothing) ──────

const hasSeries = (f: SeriesFile | null): f is SeriesFile =>
  !!f && ((f.series || []).some((s) => (s.points || []).length > 0 || s.latest) || (f.tables || []).some((tb) => tb.rows.length > 0));

function upcomingDates(cash: HyperscalerCash | null, today: string): EarningsDate[] {
  const list = (cash?.calendar || []).filter((c) => c.date && c.date >= today);
  return list.sort((a, b) => (a.date === b.date ? a.id.localeCompare(b.id) : a.date < b.date ? -1 : 1));
}

// A lab's display / lookup name: its graph node when it is on the map.
const labName = (l: AiLab) => l.node_id || l.id;
const labHasData = (l: AiLab) => (l.revenue || []).length + (l.funding || []).length + (l.deals || []).length > 0;
// ai_labs.json feeds two sub-tabs: the labs (revenue, funding, deals) and the model benchmarks.
const hasLabs = (f: AiLabsFile | null): f is AiLabsFile => !!f && (f.labs || []).some(labHasData);
const hasModels = (f: AiLabsFile | null): f is AiLabsFile => !!f && (f.models || []).length > 0;

// ── The tab ─────────────────────────────────────────────────────────────────

/** Which section a Markets sub-tab shows (page.tsx maps each sub-tab to one). */
export type MarketSection = "memory" | "gpu" | "earnings" | "labs" | "models";

interface Files {
  memory: SeriesFile | null;
  gpu: SeriesFile | null;
  cash: HyperscalerCash | null;
  labs: AiLabsFile | null;
}

// page.tsx keeps this component mounted while the user moves between the Markets
// sub-tabs (only `section` changes), so the four files load once and switching
// sub-tabs redraws at once. loadMarketJson caches each request for the page load too.
export default function MarketsView({
  section,
  resolve,
  onOpen,
}: {
  section: MarketSection;
  resolve: Resolver;
  onOpen: (id: string) => void;
}) {
  const { t } = useLang();
  const [files, setFiles] = useState<Files | null>(null);

  useEffect(() => {
    let alive = true;
    Promise.all([
      loadMarketJson<SeriesFile>("memory_prices.json"),
      loadMarketJson<SeriesFile>("gpu_prices.json"),
      loadMarketJson<HyperscalerCash>("hyperscaler_cash.json"),
      loadMarketJson<AiLabsFile>("ai_labs.json"),
    ]).then(([memory, gpu, cash, labs]) => {
      if (alive) setFiles({ memory, gpu, cash, labs });
    });
    return () => {
      alive = false;
    };
  }, []);

  if (!files) return <div className="spinner">{t("Loading market data…")}</div>;

  // The chosen section, or null when its file has nothing to show yet.
  const today = localToday();
  const upcoming = upcomingDates(files.cash, today);
  let body: React.ReactNode = null;
  if (section === "memory" && hasSeries(files.memory)) body = <SeriesSection file={files.memory} heading="Memory prices" />;
  if (section === "gpu" && hasSeries(files.gpu)) body = <SeriesSection file={files.gpu} heading="GPU rental prices" />;
  if (section === "earnings" && upcoming.length > 0)
    body = <EarningsCalendar rows={upcoming} today={today} updated={files.cash?.updated} resolve={resolve} onOpen={onOpen} />;
  if (section === "labs" && hasLabs(files.labs)) body = <AiLabsSection file={files.labs} resolve={resolve} onOpen={onOpen} />;
  if (section === "models" && hasModels(files.labs)) body = <AiModelsSection file={files.labs} resolve={resolve} onOpen={onOpen} />;
  if (!body)
    return <p className="caption">{t("No market data has been published yet. The nightly collectors fill this view.")}</p>;

  return <div className="mk">{body}</div>;
}

// ── 1) + 2) Price series ────────────────────────────────────────────────────

interface ChartBlock {
  key: string;
  title: string;
  unit: string;
  series: MarketSeries[];
}

// True when a series has readings on at least two different days (= a line).
const hasLine = (s: MarketSeries) => new Set(s.points.map((p) => p[0])).size >= 2;

// One chart per (group, unit): a chart never mixes units. A group with more
// lines than the palette has is split into several charts. A chart needs at
// least one series with two days of readings to draw a line, so a group without
// one gets no chart yet (its numbers are still in the "latest" table).
function chartBlocks(series: MarketSeries[]): ChartBlock[] {
  const byKey = new Map<string, MarketSeries[]>();
  for (const s of series) {
    if (!(s.points || []).length) continue;
    const k = `${s.group || ""}\u0000${s.unit || ""}`;
    byKey.set(k, [...(byKey.get(k) || []), s]);
  }
  const out: ChartBlock[] = [];
  for (const [k, list] of byKey) {
    const [group, unit] = k.split("\u0000");
    const parts = Math.ceil(list.length / MAX_LINES);
    for (let i = 0; i < parts; i++) {
      const part = list.slice(i * MAX_LINES, (i + 1) * MAX_LINES);
      if (!part.some(hasLine)) continue;
      out.push({
        key: `${k}-${i}`,
        title: (group || list[0].label) + (parts > 1 ? ` (${i + 1}/${parts})` : ""),
        unit,
        series: part,
      });
    }
  }
  return out;
}

/** A table cell: numbers rounded to 2 decimals at most, dates as MM-DD-YYYY, URLs as links (never broken
 *  mid-host), null as a dash. `link` makes a text cell a link (a Title cell whose row has a URL column). */
function TableCell({ v, link }: { v: string | number | null; link?: string | null }) {
  if (v === null || v === undefined || v === "") return <>—</>;
  if (typeof v === "number") return <>{v.toLocaleString("en-US", { maximumFractionDigits: Math.abs(v) >= 1000 ? 0 : 2 })}</>;
  if (link) return <SrcLink name={v} url={link} />;
  if (/^https?:\/\//.test(v))
    return (
      <span className="mk-nowrap">
        <SrcLink name={hostOf(v)} url={v} />
      </span>
    );
  if (ISO_DAY.test(v)) return <Day iso={v} />;
  return <>{v}</>;
}

/** A generic table's layout: when it has both a "Title" and a "URL" column, the title becomes the link and
 *  the URL column is not shown. */
function tableLayout(columns: string[]) {
  const title = columns.indexOf("Title");
  const url = columns.indexOf("URL");
  const linked = title >= 0 && url >= 0;
  return { title, url: linked ? url : -1, shown: columns.map((_, i) => !(linked && i === url)) };
}

function SeriesSection({ file, heading }: { file: SeriesFile; heading: string }) {
  // `heading` is the English key ("Memory prices"): shown through t(), compared in English with file.title.
  const { t } = useLang();
  const blocks = useMemo(() => chartBlocks(file.series || []), [file]);
  const latestRows = (file.series || []).filter((s) => s.latest);
  const tables = (file.tables || []).filter((tb) => tb.rows.length > 0);
  const title = t(heading);

  return (
    <section className="mk-section">
      <h3>{title}</h3>
      <p className="caption">
        {file.title && file.title.toLowerCase() !== heading.toLowerCase() ? `${file.title}. ` : ""}
        {t("Updated {date}.", { date: fmtDay(file.updated) })}
      </p>

      {blocks.length === 0 && (file.series || []).some((s) => (s.points || []).length > 0) && (
        <p className="caption">{t("The chart appears once two days of readings are recorded.")}</p>
      )}
      {blocks.length > 0 && (
        <div className="mk-charts">
          {blocks.map((b) => {
            // Each distinct source of this chart's lines, once.
            const sources = [...new Map(b.series.map((s) => [s.source + "|" + s.source_url, s])).values()];
            const lines: ChartLine[] = b.series.map((s) => ({ id: s.id, label: s.label, points: s.points }));
            return (
              <div className="mk-chart" key={b.key}>
                <div className="mk-chart-title">
                  {b.title}
                  {b.unit && <span className="mk-unit"> · {b.unit}</span>}
                </div>
                <SeriesChart lines={lines} unit={b.unit} label={`${title}: ${b.title} (${b.unit})`} />
                <div className="mk-sources">
                  {t("Source:")}{" "}
                  {sources.map((s, i) => (
                    <span key={s.id}>
                      {i > 0 && ", "}
                      <SrcLink name={s.source} url={s.source_url} />
                    </span>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      )}
      {file.attribution && <p className="caption mk-attribution">{file.attribution}</p>}

      {latestRows.length > 0 && (
        <div className="tbl-wrap mk-tbl">
          <table className="data screener mk-table">
            <Cols w={[3, 2, 1.6, 1, 1.2, 1.8]} />
            <thead>
              <tr>
                {["Series", "Group", "Latest", "Change", "As of", "Source"].map((c) => (
                  <th key={c} className="tb-static">{t(c)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {latestRows.map((s) => {
                const l = s.latest!;
                const chg = l.change_pct;
                return (
                  <tr key={s.id}>
                    <td data-label={t("Series")} className="co">{s.label}</td>
                    <td data-label={t("Group")}>{s.group}</td>
                    <td data-label={t("Latest")} className="mk-num">
                      {fmtValue(l.value)} <span className="mk-unit">{s.unit}</span>
                    </td>
                    <td
                      data-label={t("Change")}
                      className={"mk-num " + (chg === null || chg === undefined ? "" : roundPct(chg) > 0 ? "mk-up" : roundPct(chg) < 0 ? "mk-down" : "")}
                    >
                      {chg === null || chg === undefined ? "—" : fmtPct(chg)}
                    </td>
                    <td data-label={t("As of")} className="mk-num"><Day iso={l.date} /></td>
                    <td data-label={t("Source")}><SrcLink name={s.source} url={s.source_url} /></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {tables.map((tb) => {
        const layout = tableLayout(tb.columns);
        return (
          <div key={tb.id} className="mk-subtable">
            <div className="mk-sub-title">{tb.title}</div>
            <div className="tbl-wrap mk-tbl">
              <table className="data mk-table">
                <thead>
                  <tr>
                    {tb.columns.map((c, j) => (layout.shown[j] ? <th key={c} className="tb-static">{c}</th> : null))}
                  </tr>
                </thead>
                <tbody>
                  {tb.rows.map((r, i) => (
                    <tr key={i}>
                      {r.map((v, j) => {
                        if (!layout.shown[j]) return null;
                        const link = j === layout.title && layout.url >= 0 ? (r[layout.url] as string | null) : null;
                        return (
                          <td key={j} className={typeof v === "number" ? "mk-num" : undefined}>
                            <TableCell v={v} link={link} />
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="mk-sources">
              {/* a table whose rows each carry their own page (provider list prices) has no table-level URL */}
              {t("Source:")} <SrcLink name={tb.source} url={tb.source_url} />
              {tb.asof && <> · {t("as of {date}", { date: fmtDay(tb.asof) })}</>}
            </div>
          </div>
        );
      })}

      {(file.notes || []).length > 0 && (
        <ul className="caption mk-notes">
          {file.notes.map((n, i) => (
            <li key={i}>{n}</li>
          ))}
        </ul>
      )}
    </section>
  );
}

// ── 3) Earnings calendar ────────────────────────────────────────────────────

const TIME_LABEL: Record<EarningsDate["time"], string> = {
  bmo: "Before market open",
  amc: "After market close",
  unknown: "Time not announced",
};

function EarningsCalendar({
  rows,
  today,
  updated,
  resolve,
  onOpen,
}: {
  rows: EarningsDate[];
  today: string;
  updated?: string;
  resolve: Resolver;
  onOpen: (id: string) => void;
}) {
  const { t } = useLang();
  const when = (date: string) => {
    const n = daysBetween(today, date);
    return n === 0 ? t("Today") : n === 1 ? t("Tomorrow") : t("in {n} days", { n });
  };
  return (
    <section className="mk-section">
      <h3>{t("Earnings calendar")}</h3>
      <p className="caption">
        {t("Upcoming earnings dates. An unconfirmed date is an estimate until the company announces it.")}
        {updated ? " " + t("Updated {date}.", { date: fmtDay(updated) }) : ""}
      </p>
      <div className="tbl-wrap mk-tbl">
        <table className="data screener mk-table">
          <Cols w={[1.6, 1.8, 1, 1.6, 1.3, 2]} />
          <thead>
            <tr>
              {["Date", "Company", "Ticker", "Time", "Status", "Sources"].map((c) => (
                <th key={c} className="tb-static">{t(c)}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={`${r.id}-${r.date}`}>
                <td data-label={t("Date")} className="mk-num">
                  <Day iso={r.date} /> <span className="mk-muted">{when(r.date)}</span>
                </td>
                <td data-label={t("Company")} className="co">
                  <CompanyLink text={r.id} resolve={resolve} onOpen={onOpen} />
                </td>
                <td data-label={t("Ticker")}>{r.ticker}</td>
                <td data-label={t("Time")}>{t(TIME_LABEL[r.time] || TIME_LABEL.unknown)}</td>
                <td data-label={t("Status")}>
                  {r.confirmed ? (
                    <span className="mk-badge mk-ok">✓ {t("Confirmed")}</span>
                  ) : (
                    <span className="mk-badge mk-est">≈ {t("Unconfirmed")}</span>
                  )}
                </td>
                <td data-label={t("Sources")}>
                  {(r.sources || []).length === 0
                    ? "—"
                    : r.sources.map((s, i) => (
                        <span key={s.url || i}>
                          {i > 0 && ", "}
                          <SrcLink name={s.name} url={s.url} />
                        </span>
                      ))}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

// ── 4) AI labs ──────────────────────────────────────────────────────────────

function AiLabsSection({ file, resolve, onOpen }: { file: AiLabsFile; resolve: Resolver; onOpen: (id: string) => void }) {
  const { t } = useLang();

  // Labs table: latest annualized revenue + last funding round, biggest first.
  const labRows = useMemo(() => {
    // A full-year total is not an annualized run-rate: the column shows the newest run-rate / ARR point
    // (any newest point only when a lab has no run-rate at all).
    const rows = (file.labs || []).filter(labHasData).map((l) => ({
      lab: l,
      revenue:
        newest(l.revenue, (r) => r.annualized_usd !== null && isRunRate(r.type)) ||
        newest(l.revenue, (r) => r.annualized_usd !== null),
      funding: newest(l.funding),
    }));
    return sortRows(rows, (r) => r.revenue?.annualized_usd ?? null, -1);
  }, [file]);
  const showLabs = labRows.some((r) => r.revenue || r.funding);

  // Every lab's deals in one list, newest first.
  const deals = useMemo(() => {
    const all: (LabDeal & { lab: string })[] = [];
    for (const l of file.labs || []) for (const d of l.deals || []) all.push({ ...d, lab: labName(l) });
    return all.sort((a, b) => (a.date < b.date ? 1 : a.date > b.date ? -1 : 0));
  }, [file]);

  return (
    <section className="mk-section">
      <h3>{t("AI labs")}</h3>
      <p className="caption">
        {t("Revenue run-rates, funding rounds and compute deals of the AI labs, from public reports.")}{" "}
        {t("Updated {date}.", { date: file.updated })}
      </p>

      {showLabs && (
        <>
          <div className="mk-sub-title">{t("Labs")}</div>
          <div className="tbl-wrap mk-tbl">
            <table className="data screener mk-table">
              <Cols w={[1.5, 1.4, 1.1, 1.4, 1.1, 1.3, 2]} />
              <thead>
                <tr>
                  {["Lab", "Annualized revenue", "Revenue as of", "Last funding round", "Raised", "Post-money valuation", "Sources"].map((c) => (
                    <th key={c} className="tb-static">{t(c)}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {labRows.map(({ lab, revenue, funding }) => (
                  <tr key={lab.id}>
                    <td data-label={t("Lab")} className="co">
                      <CompanyLink text={labName(lab)} resolve={resolve} onOpen={onOpen} />
                    </td>
                    <td data-label={t("Annualized revenue")} className="mk-num">
                      {fmtUsd(revenue?.annualized_usd)}
                      {revenue?.type && <span className="mk-muted"> {revenue.type}</span>}
                    </td>
                    <td data-label={t("Revenue as of")} className="mk-num"><Day iso={revenue?.date} /></td>
                    <td data-label={t("Last funding round")}>
                      {funding ? (
                        <>
                          {funding.round || "—"} <span className="mk-muted"><Day iso={funding.date} /></span>
                        </>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td data-label={t("Raised")} className="mk-num">{fmtUsd(funding?.amount_usd)}</td>
                    <td data-label={t("Post-money valuation")} className="mk-num">{fmtUsd(funding?.post_money_usd)}</td>
                    <td data-label={t("Sources")}>
                      {revenue && <SrcLink name={revenue.source} url={revenue.url} />}
                      {revenue && funding && ", "}
                      {funding && <SrcLink name={funding.source} url={funding.url} />}
                      {!revenue && !funding && "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {deals.length > 0 && (
        <>
          <div className="mk-sub-title">{t("Deals")}</div>
          <div className="tbl-wrap mk-tbl">
            <table className="data screener mk-table">
              <Cols w={[1.1, 1.3, 1.5, 3.2, 0.8, 1.1, 1.6]} />
              <thead>
                <tr>
                  {["Date", "Lab", "Counterparty", "Deal", "GW", "Deal value", "Source"].map((c) => (
                    <th key={c} className="tb-static">{t(c)}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {deals.map((d, i) => (
                  <tr key={`${d.lab}-${d.date}-${i}`}>
                    <td data-label={t("Date")} className="mk-num"><Day iso={d.date} /></td>
                    <td data-label={t("Lab")} className="co">
                      <CompanyLink text={d.lab} resolve={resolve} onOpen={onOpen} />
                    </td>
                    <td data-label={t("Counterparty")}>
                      <CompanyLink text={d.counterparty} resolve={resolve} onOpen={onOpen} />
                    </td>
                    <td data-label={t("Deal")}>
                      <CellText text={d.what} label={t("Deal")} subject={d.lab} detail={{ source: d.source }} />
                    </td>
                    <td data-label={t("GW")} className="mk-num">
                      {d.gw === null || d.gw === undefined ? "—" : d.gw.toLocaleString("en-US", { maximumFractionDigits: 2 })}
                    </td>
                    <td data-label={t("Deal value")} className="mk-num">{fmtUsd(d.value_usd)}</td>
                    <td data-label={t("Source")}><SrcLink name={d.source} url={d.url} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {/* The revenue and funding rows come from Epoch AI's data set, so its credit line shows here too. */}
      {file.attribution && <p className="caption mk-attribution">{file.attribution}</p>}
    </section>
  );
}

// ── 5) Model benchmarks ─────────────────────────────────────────────────────

// The model table sorts by a fixed column or by one benchmark ("b:<id>").
type ModelSort = "model" | "lab" | "release_date" | `b:${string}`;

function AiModelsSection({ file, resolve, onOpen }: { file: AiLabsFile; resolve: Resolver; onOpen: (id: string) => void }) {
  const { t } = useLang();
  const benchmarks = file.benchmarks || [];

  // Model table sort: best score first on the first benchmark by default.
  const firstBench = benchmarks[0];
  const [sortKey, setSortKey] = useState<ModelSort>(firstBench ? `b:${firstBench.id}` : "release_date");
  const [sortDir, setSortDir] = useState<SortDir>(firstBench && !firstBench.higher_is_better ? 1 : -1);
  const defaultDir = (key: ModelSort): SortDir => {
    if (key === "release_date") return -1; // newest first
    if (key.startsWith("b:")) return benchmarks.find((b) => `b:${b.id}` === key)?.higher_is_better === false ? 1 : -1;
    return 1; // names A→Z
  };
  const onSort = (key: ModelSort) => {
    if (key === sortKey) setSortDir((d) => (d === 1 ? -1 : 1));
    else {
      setSortKey(key);
      setSortDir(defaultDir(key));
    }
  };
  const models = useMemo(() => {
    const get = (m: ModelScores): CellValue =>
      sortKey.startsWith("b:") ? m.scores?.[sortKey.slice(2)] ?? null : (m[sortKey as "model" | "lab" | "release_date"] ?? null);
    return sortRows(file.models || [], get, sortDir);
  }, [file, sortKey, sortDir]);

  // A sortable header cell (same pattern as the Screener). A plain function,
  // not a component, so React keeps the same <th> (and its keyboard focus)
  // when a click re-sorts the table.
  const sortTh = (k: ModelSort, label: string, title?: string) => (
    <th
      key={k}
      className={"tb-sortable" + (sortKey === k ? " active" : "")}
      aria-sort={sortKey === k ? (sortDir === 1 ? "ascending" : "descending") : "none"}
      tabIndex={0}
      title={title || t("Sort by {col}", { col: label })}
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

  return (
    <section className="mk-section">
      <h3>{t("Model benchmarks")}</h3>
      <p className="caption">
        {t("Benchmark scores of recent models from the AI labs.")}{" "}
        {t("Updated {date}.", { date: file.updated })}
      </p>
      <p className="caption">{t("Click a column to sort. ▲ / ▼ shows the direction; the first click puts the best score on top.")}</p>
      <div className="tbl-wrap mk-tbl">
        <table className="data mk-table mk-bench">
          <thead>
            <tr>
              {sortTh("model", t("Model"))}
              {sortTh("lab", t("Lab"))}
              {sortTh("release_date", t("Released"))}
              {benchmarks.map((b) =>
                sortTh(`b:${b.id}`, b.label, `${b.label}: ${b.higher_is_better ? t("higher is better") : t("lower is better")}`)
              )}
              <th className="tb-static">{t("Source")}</th>
            </tr>
          </thead>
          <tbody>
            {models.map((m, i) => (
              <tr key={`${m.lab}-${m.model}-${i}`}>
                <td className="co">{m.model}</td>
                <td>
                  <CompanyLink text={m.lab} resolve={resolve} onOpen={onOpen} />
                </td>
                <td className="mk-num"><Day iso={m.release_date} /></td>
                {benchmarks.map((b) => (
                  <td key={b.id} className={"mk-num" + (sortKey === `b:${b.id}` ? " mk-sorted" : "")}>
                    {fmtScore(m.scores?.[b.id])}
                  </td>
                ))}
                <td><SrcLink name={m.source} url={m.url} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {file.attribution && <p className="caption mk-attribution">{file.attribution}</p>}
    </section>
  );
}
