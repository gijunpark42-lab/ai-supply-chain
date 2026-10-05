"use client";

import { useEffect, useMemo, useState } from "react";
import { fetchJson } from "@/lib/data";
import type { Resolver } from "@/lib/company";
import {
  copyToClipboard,
  csvFilename,
  downloadCsv,
  sortRows,
  toCsv,
  useFlash,
  type CsvColumn,
} from "@/lib/table";
import CompanyLink from "./CompanyLink";
import CellText from "./CellText";
import { SourceBadge } from "./SignalText";
import { t, tr, name, useLang } from "@/lib/i18n";
import "./Tables.css";

// Capex & Backlog — the money view of the AI buildout. One side of the tab is
// what the buyers SPEND (capex, the top-of-funnel demand signal for every
// supplier below them in the graph); the other is what they have already SOLD
// (backlog / RPO / contracted revenue). All figures are hand-curated from
// earnings sources in chains/ — the component just renders capex_backlog.json.

interface Tile {
  label: string;
  value: string;
  delta?: string;
  detail?: string;
  source?: string;
}
interface CapexBar {
  name: string;
  busd: number; // the number the bar is drawn from, in $B
  display: string; // the figure as reported ("$195-205B")
  period?: string;
  metric?: string;
  growth?: string; // only present when the source stated it — never computed here
  detail?: string;
  source?: string;
}
interface BarBlock {
  title: string;
  unit: string;
  note?: string;
  bars: CapexBar[];
}
interface GroupRow {
  name: string;
  capex_q: string;
  capex_year: string;
  backlog: string;
  signal: string;
  source: string;
}
interface Group {
  title: string;
  rows: GroupRow[];
}
interface CapexBacklogData {
  updated: string;
  note?: string;
  tiles: Tile[];
  capex_bars: BarBlock;
  backlog_bars: BarBlock;
  groups: Group[];
  footnote?: string;
}

const COLS = ["Company", "Capex (latest qtr)", "Capex (annual / funding)", "Backlog / contracted", "Key signal", "Source"];

// The group tables' CSV (all groups in one file, with a Group column).
type FlatRow = GroupRow & { group: string };
const TABLE_CSV: CsvColumn<FlatRow>[] = [
  { header: "Group", get: (r) => r.group },
  { header: "Company", get: (r) => r.name },
  { header: "Capex (latest qtr)", get: (r) => r.capex_q },
  { header: "Capex (annual / funding)", get: (r) => r.capex_year },
  { header: "Backlog / contracted", get: (r) => r.backlog },
  { header: "Key signal", get: (r) => r.signal },
  { header: "Source", get: (r) => r.source },
];

const slug = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, "-");
const fmtNum = (n: number) => n.toLocaleString("en-US", { maximumFractionDigits: 1 });

function BarChart({
  block,
  color,
  resolve,
  onOpen,
}: {
  block: BarBlock;
  color: string;
  resolve: Resolver;
  onOpen: (id: string) => void;
}) {
  useLang();
  const [sortBy, setSortBy] = useState<"value" | "name">("value");
  const [flashed, flash] = useFlash();

  const max = Math.max(...block.bars.map((b) => b.busd));
  const bars = useMemo(
    () =>
      sortBy === "value"
        ? sortRows(block.bars, (b) => b.busd, -1)
        : sortRows(block.bars, (b) => b.name, 1),
    [block.bars, sortBy]
  );

  const csvText = () =>
    toCsv(bars, [
      { header: "Company", get: (b) => b.name },
      { header: `Chart value (${block.unit})`, get: (b) => b.busd },
      { header: "Reported", get: (b) => b.display },
      { header: "Basis", get: (b) => b.period || b.metric || "" },
      { header: "Growth", get: (b) => b.growth || "" },
      { header: "Detail", get: (b) => b.detail || "" },
      { header: "Source", get: (b) => b.source || "" },
    ]);
  const copyCsv = async () => {
    const ok = await copyToClipboard(csvText());
    flash(ok ? "csv" : "csv-fail");
  };

  return (
    <div className="cb-chart">
      <div className="tb-chart-head">
        <div className="cb-chart-title">{tr(block.title)}</div>
        <span className="tb-seg-label">{t("Sort")}</span>
        <div className="tb-seg" role="group" aria-label={t("Sort {title} bars", { title: tr(block.title) })}>
          <button
            type="button"
            className="tb-btn"
            aria-pressed={sortBy === "value"}
            onClick={() => setSortBy("value")}
          >
            {t("Value")}
          </button>
          <button
            type="button"
            className="tb-btn"
            aria-pressed={sortBy === "name"}
            onClick={() => setSortBy("name")}
          >
            {t("Name")}
          </button>
        </div>
        <button type="button" className="tb-btn" onClick={copyCsv} title={t("Copy these bars as CSV")}>
          {flashed === "csv" ? t("Copied ✓") : flashed === "csv-fail" ? t("Copy failed") : t("Copy CSV")}
        </button>
      </div>
      {block.note && <div className="caption">{tr(block.note)}</div>}
      <div className="cb-bars">
        {bars.map((b) => {
          // Bars scale linearly to the widest, with 112px reserved so the
          // value label always fits to the right of the longest bar.
          const frac = max > 0 ? b.busd / max : 0;
          const sub = tr(b.period || b.metric || "");
          const tipId = `tb-tip-${slug(block.title)}-${slug(b.name)}`;
          return (
            // The wrapper is focusable so the tooltip also opens from the
            // keyboard (and on a tap, which focuses it).
            <div className="tb-barrow" key={b.name} tabIndex={0} aria-describedby={tipId}>
              <div className="cb-row">
                <div className="cb-label">
                  <span className="cb-name">
                    <CompanyLink text={b.name} resolve={resolve} onOpen={onOpen} />
                  </span>
                  {sub && <span className="cb-sub">{sub}</span>}
                </div>
                <div className="cb-track">
                  <div
                    className="cb-bar"
                    style={{ width: `calc((100% - 112px) * ${frac.toFixed(4)})`, background: color }}
                  />
                  <span className="cb-val">
                    {tr(b.display)}
                    {b.growth && <span className="cb-growth"> {tr(b.growth)}</span>}
                  </span>
                </div>
              </div>
              {b.source && (
                <div className="tb-bar-src" title={b.source}>
                  {t("Source:")} {b.source}
                </div>
              )}
              <div className="tb-tip" role="tooltip" id={tipId}>
                <div className="tb-tip-title">
                  {name(resolve(b.name) || b.name)} — {tr(b.display)}
                  {sub ? ` (${sub})` : ""}
                </div>
                <span className="tb-tip-row">
                  <span className="tb-tip-k">{t("Chart value:")} </span>
                  {fmtNum(b.busd)} {block.unit}
                </span>
                {b.growth && (
                  <span className="tb-tip-row">
                    <span className="tb-tip-k">{t("Growth:")} </span>
                    {tr(b.growth)}
                  </span>
                )}
                {b.detail && <span className="tb-tip-row">{tr(b.detail)}</span>}
                {b.source && <span className="tb-tip-row tb-tip-k">{t("Source:")} {b.source}</span>}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default function CapexBacklog({
  resolve,
  onOpen,
}: {
  resolve: Resolver;
  onOpen: (id: string) => void;
}) {
  useLang(["capex"]);
  const [data, setData] = useState<CapexBacklogData | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [flashed, flash] = useFlash();

  useEffect(() => {
    fetchJson<CapexBacklogData>("/data/capex_backlog.json")
      .then(setData)
      .catch((e) => setErr(e?.message || String(e)));
  }, []);

  // Every group table's rows in one list, for the CSV export. (Hooks must run
  // before the early returns below, hence the `data ?` guard.)
  const flatRows = useMemo<FlatRow[]>(
    () => (data ? data.groups.flatMap((g) => g.rows.map((r) => ({ ...r, group: g.title }))) : []),
    [data]
  );
  const copyTable = async () => {
    const ok = await copyToClipboard(toCsv(flatRows, TABLE_CSV));
    flash(ok ? "table" : "table-fail");
  };
  const downloadTable = () =>
    downloadCsv(csvFilename("capex backlog"), toCsv(flatRows, TABLE_CSV));

  if (err)
    return (
      <p className="caption">
        {t("Failed to load capex_backlog.json — run")} <code>npm run sync</code>. ({err})
      </p>
    );
  if (!data) return <div className="spinner">{t("Loading capex & backlog…")}</div>;

  return (
    <div>
      <h3>💰 {t("Capex & Backlog")}</h3>
      <p className="caption">
        {t("What the AI buildout's buyers spend (capex — the demand signal for every supplier below them) and what they have already sold (backlog / RPO / contracted revenue). Hyperscalers and neoclouds, from earnings sources only. Updated {date}.", { date: data.updated })}
      </p>

      <div className="cb-tiles">
        {data.tiles.map((tile) => (
          <div
            className="cb-tile"
            key={tile.label}
            title={[tr(tile.detail), tile.source ? `${t("Source:")} ${tile.source}` : ""].filter(Boolean).join("\n")}
          >
            <div className="cb-tile-label">{tr(tile.label)}</div>
            <div className="cb-tile-value">{tr(tile.value)}</div>
            {tile.delta && <div className="cb-tile-delta">{tr(tile.delta)}</div>}
            {tile.source && <div className="tb-tile-src">{t("Source:")} {tile.source}</div>}
          </div>
        ))}
      </div>

      <div className="cb-charts">
        <BarChart block={data.capex_bars} color="#2997ff" resolve={resolve} onOpen={onOpen} />
        <BarChart
          block={data.backlog_bars}
          color="#2ea852"
          resolve={resolve}
          onOpen={onOpen}
        />
      </div>

      <div className="tb-toolbar" style={{ marginTop: "1.5rem", marginBottom: 0 }}>
        <span className="tb-rowcount">
          {t("{n} companies across {g} tables", { n: flatRows.length, g: data.groups.length })}
        </span>
        <div className="tb-actions">
          <button
            type="button"
            className="tb-btn"
            onClick={copyTable}
            disabled={flatRows.length === 0}
            title={t("Copy every table below as one CSV")}
          >
            {flashed === "table" ? t("Copied ✓") : flashed === "table-fail" ? t("Copy failed") : t("Copy table as CSV")}
          </button>
          <button
            type="button"
            className="tb-btn"
            onClick={downloadTable}
            disabled={flatRows.length === 0}
            title={t("Download every table below as one CSV file")}
          >
            {t("Download CSV")}
          </button>
        </div>
      </div>

      {data.groups.map((g) => (
        <div key={g.title} style={{ marginTop: "1rem" }}>
          <div className="cb-group-title">{tr(g.title)}</div>
          <div className="tbl-wrap">
            <table className="data screener capexbacklog">
              <thead>
                <tr>
                  {COLS.map((c) => (
                    <th key={c} className="tb-static">
                      {t(c)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {g.rows.map((r) => (
                  <tr key={r.name}>
                    <td data-label={t("Company")} className="co">
                      <div className="cell">
                        <CompanyLink text={r.name} resolve={resolve} onOpen={onOpen} />
                      </div>
                    </td>
                    {/* Every figure column carries `r.source` as the dialog's
                        footer, so opening a clipped cell always shows which
                        filing the number came from. */}
                    <td data-label={t("Capex (latest qtr)")}>
                      <CellText text={tr(r.capex_q)} label={t("Capex (latest qtr)")} subject={r.name}
                        detail={{ source: r.source }} />
                    </td>
                    <td data-label={t("Capex (annual / funding)")}>
                      <CellText text={tr(r.capex_year)} label={t("Capex (annual / funding)")} subject={r.name}
                        detail={{ source: r.source }} />
                    </td>
                    <td data-label={t("Backlog / contracted")}>
                      <CellText text={tr(r.backlog)} label={t("Backlog / contracted")} subject={r.name}
                        detail={{ source: r.source }} />
                    </td>
                    <td data-label={t("Key signal")}>
                      <CellText text={tr(r.signal)} label={t("Key signal")} subject={r.name}
                        detail={{ source: r.source }} />
                    </td>
                    <td data-label={t("Source")}>
                      <CellText text={r.source} label={t("Source")} subject={r.name} className="cb-source">
                        {r.source && <SourceBadge label={r.source} />} {r.source}
                      </CellText>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ))}

      {data.footnote && (
        <p className="caption" style={{ marginTop: "0.8rem" }}>
          {tr(data.footnote)}
        </p>
      )}
    </div>
  );
}
