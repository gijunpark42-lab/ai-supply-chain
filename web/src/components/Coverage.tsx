"use client";

import { useEffect, useMemo, useState } from "react";
import type { VizNode } from "@/lib/types";
import StatusBoard, { type Board } from "@/components/StatusBoard";
import { t, name, useLang } from "@/lib/i18n";

// Status tab (was "Coverage" until 2026-09-26) — the enrichment workflow dashboard.
// Top: the status board from enrich_status.py (which `enrich <market>` to run next and why).
// Below: one card per pipeline, then each tracked company's next/last earnings-call date
// (Yahoo, via /api/earnings) joined with the graph's own data freshness (lastData from
// source labels). A call that already happened with no newer data = "enrich now".

interface Earn {
  ts: number | null;
  start: number | null;
  end: number | null;
}

type Status = "due" | "upcoming" | "covered" | "unknown";

interface Row {
  id: string;
  ticker: string;
  call: Date | null;
  status: Status;
  days: number; // days until (upcoming) / since (due, covered); -1 when unknown
  lastData: string | null;
  stale: boolean;
  qd: number;
  node: VizNode;
}

// Per-pipeline status written by enrich_status.py (graph/enrich_status.json → /data).
// Answers: which enrich pipeline ran WHEN, what date range it covers, what is missing.
interface PendingRow {
  company: string | null;
  label: string | null;
  file: string | null;
}
interface Pipeline {
  id: string;
  name: string;
  command: string;
  source: string;
  files: number;
  in_graph: number;
  entries: number;
  pending: PendingRow[];
  no_data: { label: string; file: string; why: string | null }[];
  skipped: number;
  source_range: [string, string] | null;
  last_fetch: string | null;
  last_enriched: string | null;
  last_sync: string | null;
  enriched_days: { day: string; labels: number }[];
  extra: {
    waiting?: { symbol: string; name: string; report_date: string }[];
    no_media?: string[];
    runs?: { at: string; since: string; pages: number; oldest_seen: string; saved: number }[];
    done?: number;
    dropped?: number;
  };
}
interface EnrichStatus {
  generated: string;
  labels_total: number;
  pipelines: Pipeline[];
  board?: Board; // the market board (enrich_status.py, since 2026-09-26)
}

const STATUS_META: Record<Status, { chip: string; cls: string }> = {
  due: { chip: "🔴 Enrich now", cls: "due" },
  upcoming: { chip: "🗓 Upcoming", cls: "up" },
  covered: { chip: "✅ Covered", cls: "ok" },
  unknown: { chip: "—", cls: "na" },
};

const PRIO: Record<Status, number> = { due: 0, upcoming: 1, covered: 2, unknown: 3 };

type Filter = "all" | "due" | "up14" | "stale" | "nodata";
type SortKey = "prio" | "company" | "call" | "last" | "qd";

const fmtDate = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(
    d.getDate()
  ).padStart(2, "0")}`;

export default function Coverage({
  nodes,
  onSelect,
}: {
  nodes: VizNode[];
  onSelect: (n: VizNode) => void;
}) {
  // Only the page chrome is translated: the pipeline / board text from
  // enrich_status.json is operator text and stays in English.
  useLang();
  const [dates, setDates] = useState<Record<string, Earn>>({});
  const [loaded, setLoaded] = useState(false);
  const [apiOk, setApiOk] = useState(true);
  const [filter, setFilter] = useState<Filter>("all");
  const [q, setQ] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("prio");
  const [sortDir, setSortDir] = useState<1 | -1>(1);
  const [copied, setCopied] = useState<string | null>(null);
  const [pipes, setPipes] = useState<EnrichStatus | null>(null);

  // Static file synced from graph/enrich_status.json; the section simply hides when absent.
  useEffect(() => {
    fetch("/data/enrich_status.json")
      .then((r) => (r.ok ? r.json() : null))
      .then((j) => setPipes(j))
      .catch(() => setPipes(null));
  }, []);

  const listed = useMemo(() => nodes.filter((n) => n.ticker), [nodes]);
  const unlisted = nodes.length - listed.length;

  useEffect(() => {
    const companies = listed.map((n) => ({
      id: n.id,
      ticker: n.ticker,
      exchange: n.exchange,
    }));
    if (!companies.length) {
      setLoaded(true);
      return;
    }
    fetch("/api/earnings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ companies }),
    })
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((j) => {
        setDates(j.dates || {});
        setApiOk(j.authOk !== false);
      })
      .catch(() => setApiOk(false))
      .finally(() => setLoaded(true));
  }, [listed]);

  const rows = useMemo<Row[]>(() => {
    const now = new Date();
    return listed.map((n) => {
      const e = dates[n.id];
      const ts = e?.ts ?? e?.start ?? null;
      const call = ts ? new Date(ts * 1000) : null;
      let status: Status = "unknown";
      let days = -1;
      if (call) {
        const diff = Math.round((call.getTime() - now.getTime()) / 86400e3);
        if (diff >= 0) {
          status = "upcoming";
          days = diff;
        } else {
          days = -diff;
          status = n.lastData && n.lastData >= fmtDate(call) ? "covered" : "due";
        }
      }
      return {
        id: n.id,
        ticker: n.ticker || "—",
        call,
        status,
        days,
        lastData: n.lastData,
        stale: n.stale,
        qd: n.quarterly_data.length,
        node: n,
      };
    });
  }, [listed, dates]);

  const counts = useMemo(
    () => ({
      due: rows.filter((r) => r.status === "due").length,
      up14: rows.filter((r) => r.status === "upcoming" && r.days <= 14).length,
      stale: rows.filter((r) => r.stale).length,
      nodata: rows.filter((r) => r.qd === 0).length,
    }),
    [rows]
  );

  const shown = useMemo(() => {
    const query = q.trim().toLowerCase();
    let out = rows.filter((r) => {
      if (query && !r.id.toLowerCase().includes(query) && !r.ticker.toLowerCase().includes(query) &&
          !name(r.id).toLowerCase().includes(query))
        return false;
      if (filter === "due") return r.status === "due";
      if (filter === "up14") return r.status === "upcoming" && r.days <= 14;
      if (filter === "stale") return r.stale;
      if (filter === "nodata") return r.qd === 0;
      return true;
    });
    const cmp = (a: Row, b: Row): number => {
      switch (sortKey) {
        case "company":
          return a.id.localeCompare(b.id);
        case "call": {
          const av = a.call?.getTime() ?? Infinity;
          const bv = b.call?.getTime() ?? Infinity;
          return av - bv;
        }
        case "last":
          return (a.lastData || "").localeCompare(b.lastData || "");
        case "qd":
          return a.qd - b.qd;
        default: {
          // priority queue: due (most recent call first) → upcoming (soonest)
          // → covered (most recent) → unknown
          if (PRIO[a.status] !== PRIO[b.status]) return PRIO[a.status] - PRIO[b.status];
          if (a.status === "due" || a.status === "covered") return a.days - b.days;
          if (a.status === "upcoming") return a.days - b.days;
          return a.id.localeCompare(b.id);
        }
      }
    };
    out.sort((a, b) => cmp(a, b) * sortDir);
    return out;
  }, [rows, filter, q, sortKey, sortDir]);

  const onSort = (k: SortKey) => {
    if (k === sortKey) setSortDir((d) => (d === 1 ? -1 : 1));
    else {
      setSortKey(k);
      setSortDir(1);
    }
  };

  const copy = (id: string) => {
    const text = `Transcript:${id}`;
    try {
      navigator.clipboard?.writeText(text);
      setCopied(id);
      setTimeout(() => setCopied((c) => (c === id ? null : c)), 1400);
    } catch {}
  };

  const stat = (f: Filter, label: string, n: number, cls: string) => (
    <button
      className={"cov-stat " + cls + (filter === f ? " on" : "")}
      onClick={() => setFilter(filter === f ? "all" : f)}
    >
      <b>{n}</b> {t(label)}
    </button>
  );

  const HEADERS: { key: SortKey | null; label: string }[] = [
    { key: "company", label: "Company" },
    { key: null, label: "Ticker" },
    { key: "call", label: "Earnings call" },
    { key: "prio", label: "Status" },
    { key: "last", label: "Last data" },
    { key: "qd", label: "Signals" },
    { key: null, label: "Enrich" },
  ];

  return (
    <div>
      <h3>📡 {t("Status")}</h3>
      <p className="caption">
        {t("Which enrich to run next, and why: what is fetched and waiting, which companies are overdue for a call or were never enriched, per home market. The 📋 buttons copy the command for Claude Code. Built by enrich_status.py on every graph build and at the end of every enrich run (the same page as ENRICH_STATUS.md in the repo).")}
      </p>

      {pipes?.board && (
        <StatusBoard board={pipes.board} generated={pipes.generated} nodes={nodes} onSelect={onSelect} />
      )}

      {pipes && pipes.pipelines.length > 0 && (
        <>
          <h4 style={{ margin: "1rem 0 0.2rem" }}>🛠 {t("Pipelines")}</h4>
          <p className="caption" style={{ marginTop: 0 }}>
            {t("One card per enrich pipeline: when it last synced, what reporting period its sources cover, and what is still missing. Generated by enrich_status.py on {date} · {n} source labels in the graph.", { date: pipes.generated, n: pipes.labels_total })}
          </p>
          <div className="pipe-grid">
            {pipes.pipelines.map((p) => {
              const pendingN = p.pending.length;
              const waiting = p.extra.waiting || [];
              const noMedia = p.extra.no_media || [];
              const lastRun = p.extra.runs?.[p.extra.runs.length - 1];
              return (
                <div key={p.id} className={"pipe-card" + (pendingN ? " has-pending" : "")}>
                  <h4>{p.name}</h4>
                  <div className="cmd">
                    <code>{p.command}</code> · {p.source}
                  </div>
                  <dl className="pipe-kv">
                    <dt>{t("Last sync")}</dt>
                    <dd>{p.last_sync || "—"}</dd>
                    <dt>{t("Last enriched")}</dt>
                    <dd className={p.last_enriched ? "" : "warn"}>{p.last_enriched || t("never")}</dd>
                    <dt>{t("Sources cover")}</dt>
                    <dd>{p.source_range ? `${p.source_range[0]} → ${p.source_range[1]}` : "—"}</dd>
                    <dt>{t("Files")}</dt>
                    <dd>
                      {t("{files} saved · {labels} labels in graph ({entries} entries)", { files: p.files, labels: p.in_graph, entries: p.entries })}
                      {p.id === "edgar" && p.extra.done != null && <> · {t("{n} read", { n: p.extra.done })}</>}
                    </dd>
                    <dt>{t("Pending")}</dt>
                    <dd className={pendingN ? "bad" : ""}>
                      {pendingN ? t("{n} not yet enriched", { n: pendingN }) : t("queue empty")}
                    </dd>
                    {p.no_data.length > 0 && (
                      <>
                        <dt>{t("No data")}</dt>
                        <dd className="warn">{t("{n} saved, nothing landed", { n: p.no_data.length })}</dd>
                      </>
                    )}
                    {p.skipped > 0 && (
                      <>
                        <dt>{t("Skipped")}</dt>
                        <dd>{t("{n} filings with no supply-chain content", { n: p.skipped })}</dd>
                      </>
                    )}
                    {waiting.length > 0 && (
                      <>
                        <dt>{t("Waiting")}</dt>
                        <dd className="warn">
                          {waiting.map((w) => `${w.name} (${w.report_date})`).join(", ")} — {t("call not posted yet")}
                        </dd>
                      </>
                    )}
                    {noMedia.length > 0 && (
                      <>
                        <dt>{t("No media")}</dt>
                        <dd className="warn">{t("{n} 法說會 without a replay video", { n: noMedia.length })}</dd>
                      </>
                    )}
                    {lastRun && (
                      <>
                        <dt>{t("Last run")}</dt>
                        <dd>
                          {t("{at} · {pages} pages back to {oldest} · {saved} saved", { at: lastRun.at, pages: lastRun.pages, oldest: lastRun.oldest_seen, saved: lastRun.saved })}
                        </dd>
                      </>
                    )}
                  </dl>
                  {pendingN > 0 && (
                    <details>
                      <summary>{t("Show the {n} pending", { n: pendingN })}</summary>
                      <ul>
                        {p.pending.map((r, i) => (
                          <li key={i}>
                            <b>{r.company || "?"}</b> — {r.label || r.file}
                          </li>
                        ))}
                      </ul>
                    </details>
                  )}
                  {p.no_data.length > 0 && (
                    <details>
                      <summary>{t("Show the {n} with no data", { n: p.no_data.length })}</summary>
                      <ul>
                        {p.no_data.map((r, i) => (
                          <li key={i}>
                            {r.label}
                            {r.why && <span className="muted"> · {r.why}</span>}
                          </li>
                        ))}
                      </ul>
                    </details>
                  )}
                  {p.enriched_days.length > 0 && (
                    <div className="pipe-days">
                      {t("Enriched on:")}{" "}
                      {p.enriched_days
                        .slice(-6)
                        .map((d) => `${d.day.slice(5)} (${d.labels})`)
                        .join(" · ")}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </>
      )}

      <h4 style={{ margin: "1rem 0 0.2rem" }}>🗓 {t("Companies — earnings calendar")}</h4>
      <p className="caption" style={{ marginTop: 0 }}>
        {t("Each listed company's next / most recent earnings call (Yahoo Finance) joined with the freshness of its data in the graph. A call that already happened with no newer data = Enrich now — the 📋 button copies the Transcript:<company> command.")}
        {unlisted > 0 && <> {t("{n} private/unlisted companies not shown.", { n: unlisted })}</>}
      </p>

      {!apiOk && loaded && (
        <p className="caption" style={{ color: "#d29922" }}>
          ⚠ {t("Earnings dates unavailable right now (Yahoo auth failed) — showing coverage from graph data only.")}
        </p>
      )}

      <div className="cov-stats">
        {stat("due", "enrich now", counts.due, "due")}
        {stat("up14", "upcoming ≤14d", counts.up14, "up")}
        {stat("stale", "stale (180d)", counts.stale, "st")}
        {stat("nodata", "no signals", counts.nodata, "na")}
        <span className="cov-total">{t("{n} listed companies tracked", { n: rows.length })}</span>
      </div>

      <div className="row" style={{ margin: "0.6rem 0 0.8rem" }}>
        <div className="grow" style={{ maxWidth: 340 }}>
          <input
            type="search"
            placeholder={t("Search company or ticker…")}
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
        </div>
      </div>

      {!loaded && <div className="spinner">{t("Loading earnings dates…")}</div>}

      {loaded && (
        <div className="tbl-wrap">
          <table className="data screener coverage">
            <colgroup>
              <col style={{ width: "20%" }} />
              <col style={{ width: "10%" }} />
              <col style={{ width: "17%" }} />
              <col style={{ width: "15%" }} />
              <col style={{ width: "14%" }} />
              <col style={{ width: "9%" }} />
              <col style={{ width: "15%" }} />
            </colgroup>
            <thead>
              <tr>
                {HEADERS.map((h) => (
                  <th
                    key={h.label}
                    className={h.key && sortKey === h.key ? "active" : ""}
                    style={h.key ? undefined : { cursor: "default" }}
                    onClick={h.key ? () => onSort(h.key!) : undefined}
                  >
                    <span className="th-label">{t(h.label)}</span>
                    {h.key && (
                      <span className="sort-arrow">
                        {sortKey === h.key ? (sortDir === 1 ? "▲" : "▼") : "↕"}
                      </span>
                    )}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {shown.map((r) => (
                <tr key={r.id} onClick={() => onSelect(r.node)} style={{ cursor: "pointer" }}>
                  <td data-label={t("Company")} className="co">
                    {/* The whole row already opens the panel; styling the name as
                        a link just makes that discoverable and matches the other
                        tabs. The row handler does the work, so this is inert. */}
                    <div className="cell">
                      <span className="co-link">{name(r.id)}</span>
                    </div>
                  </td>
                  <td data-label={t("Ticker")}>
                    <div className="cell nowrap">{r.ticker}</div>
                  </td>
                  <td data-label={t("Earnings call")}>
                    <div className="cell nowrap">
                      {r.call ? (
                        <>
                          {fmtDate(r.call)}{" "}
                          <span className="muted">
                            {r.status === "upcoming"
                              ? r.days === 0
                                ? "· " + t("today")
                                : "· " + t("in {n}d", { n: r.days })
                              : "· " + t("{n}d ago", { n: r.days })}
                          </span>
                        </>
                      ) : (
                        "—"
                      )}
                    </div>
                  </td>
                  <td data-label={t("Status")}>
                    <div className="cell nowrap">
                      <span className={"cov-chip " + STATUS_META[r.status].cls}>
                        {STATUS_META[r.status].chip === "—" ? "—" : t(STATUS_META[r.status].chip)}
                      </span>
                    </div>
                  </td>
                  <td data-label={t("Last data")}>
                    <div className="cell nowrap">
                      {r.lastData || "—"}
                      {r.stale && <span title={t("no data in 180d")}> 💤</span>}
                    </div>
                  </td>
                  <td data-label={t("Signals")}>
                    <div className="cell nowrap">{r.qd}</div>
                  </td>
                  <td data-label={t("Enrich")}>
                    <div className="cell nowrap">
                      <button
                        className="copy-btn"
                        title={t("Copy \"Transcript:{id}\"", { id: r.id })}
                        onClick={(e) => {
                          e.stopPropagation();
                          copy(r.id);
                        }}
                      >
                        {copied === r.id ? "✓ " + t("copied") : "📋 " + t("Transcript")}
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {loaded && (
        <p className="caption" style={{ marginTop: "0.6rem" }}>
          {t("{n} shown · dates from Yahoo Finance (best-effort; refreshed ~6h) · \"Covered\" = the graph has data on or after the call date.", { n: shown.length })}
        </p>
      )}
    </div>
  );
}
