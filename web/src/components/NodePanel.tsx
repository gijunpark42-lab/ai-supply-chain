"use client";

import { memo, useEffect, useMemo, useRef, useState } from "react";
import type { VizNode, Contract, QuarterlyData } from "@/lib/types";
import { buildBadges, buildTimeline, sigDate, FLAG } from "@/lib/signals";
import { GROUP_NAMES, GROUP_COLORS, slugLabel } from "@/lib/taxonomy";
import { nodeExposure } from "@/lib/transitions";
import { fetchJson } from "@/lib/data";
import { yahooSymbol } from "@/lib/yahoo";
import ReportView from "./ReportView";
import TradingViewChart from "./TradingViewChart";
import LiveQuote from "./LiveQuote";
import Fundamentals from "./Fundamentals";
import { EvidenceButton } from "./Evidence";
import "./NodePanel.css";

const US = new Set(["NASDAQ", "NYSE"]);

// ── Source labels ───────────────────────────────────────────────────────────
// Every quarterly_data.quarter / contract.source is a label like
// "NVIDIA Q2 FY2027 (08-26-2026)". The date in parentheses is the date of the
// SOURCE DOCUMENT (call / filing / article), which is what we sort and show.
const LABEL_DATE = /\((\d{2}-\d{2}-\d{4})\)/;

function splitLabel(label: string): { text: string; date: string | null } {
  const m = LABEL_DATE.exec(label || "");
  if (!m) return { text: label || "", date: null };
  return { text: (label.slice(0, m.index) + label.slice(m.index + m[0].length)).trim(), date: m[1] };
}

// sigDate() gives a sortable YYYYMMDD number (or -1). Turn it back into the
// MM-DD-YYYY form the labels use, for display.
function fmtDate(key: number): string | null {
  if (key < 0) return null;
  const s = String(key);
  return `${s.slice(4, 6)}-${s.slice(6, 8)}-${s.slice(0, 4)}`;
}

const newestFirst = (a: { quarter: string }, b: { quarter: string }) =>
  sigDate(b.quarter) - sigDate(a.quarter);

const hasFigure = (f: string | undefined) => !!f && f !== "no specific figure";

// ── External links ──────────────────────────────────────────────────────────
// TradingView exchange codes for the exchanges in company_metadata. Best effort:
// an exchange missing here simply gets no TradingView button. Yahoo symbols come
// from lib/yahoo.ts (the same mapper the /api/quote route uses).
const TV_EXCHANGE: Record<string, string> = {
  NASDAQ: "NASDAQ",
  NYSE: "NYSE",
  TSE: "TSE",
  TWSE: "TWSE",
  KOSPI: "KRX",
  KRX: "KRX",
  KOSDAQ: "KRX",
  SZSE: "SZSE",
  SSE: "SSE",
  XETRA: "XETR",
  "Euronext Paris": "EURONEXT",
  EPA: "EURONEXT",
  "Euronext Amsterdam": "EURONEXT",
  AMS: "EURONEXT",
  MIL: "MIL",
  "OMX Stockholm": "OMXSTO",
  STO: "OMXSTO",
  OSE: "OSL",
  SIX: "SIX",
  HKEX: "HKEX",
  VIE: "VIE",
  LSE: "LSE",
  IDX: "IDX",
};

function tradingViewUrl(ticker: string | null, exchange: string | null): string | null {
  if (!ticker || !exchange) return null;
  const ex = TV_EXCHANGE[exchange];
  if (!ex) return null;
  // Non-US tickers are stored with their Yahoo suffix ("2382.TW"); TradingView
  // wants the bare code. HK codes additionally drop their leading zeros there.
  let base = US.has(exchange) ? ticker.trim() : ticker.split(".")[0].trim();
  if (ex === "HKEX") base = base.replace(/^0+(?=\d)/, "");
  if (!base) return null;
  return `https://www.tradingview.com/symbols/${encodeURIComponent(ex)}-${encodeURIComponent(base)}/`;
}

// ── Screener slots ──────────────────────────────────────────────────────────
type Slot = NonNullable<QuarterlyData["slot"]>;
const SLOTS: { key: Slot; label: string }[] = [
  { key: "revenue_growth", label: "Revenue / growth" },
  { key: "guidance", label: "Guidance" },
  { key: "backlog_or_b2b", label: "Backlog / B2B" },
  { key: "supply_status", label: "Supply status" },
  { key: "next_catalyst", label: "Next catalyst" },
];
const SLOT_LABEL: Record<string, string> = Object.fromEntries(SLOTS.map((s) => [s.key, s.label]));

// The latest-dated slot-tagged entry per slot (same rule derive.py uses for the
// Screener: replace-with-latest). `>=` so that, on the same date, the entry that
// comes later in the file wins.
function latestBySlot(qd: QuarterlyData[]): { key: Slot; label: string; q: QuarterlyData }[] {
  const best = new Map<Slot, QuarterlyData>();
  for (const q of qd) {
    if (!q.slot) continue;
    const cur = best.get(q.slot);
    if (!cur || sigDate(q.quarter) >= sigDate(cur.quarter)) best.set(q.slot, q);
  }
  return SLOTS.flatMap((s) => {
    const q = best.get(s.key);
    return q ? [{ ...s, q }] : [];
  });
}

// ── Counterparties on file (quarterly_data entries with `counterparty`) ─────
// These are customers / suppliers named in a filing or call that are NOT graph
// nodes (they failed the litmus test, or are utilities, agencies …), so the deal
// was folded onto this company's own node. Grouped per counterparty here.
interface OnFile {
  name: string;
  role: "customer" | "supplier";
  entries: QuarterlyData[]; // newest first
  latest: number; // sigDate of the newest entry
}

function groupOnFile(qd: QuarterlyData[]): { customers: OnFile[]; suppliers: OnFile[] } {
  const m = new Map<string, OnFile>();
  for (const q of qd) {
    if (!q.counterparty) continue;
    const role: OnFile["role"] =
      q.counterparty_role === "supplier" || (!q.counterparty_role && /^Supplier /.test(q.signal))
        ? "supplier"
        : "customer";
    const key = role + "|" + q.counterparty;
    const g = m.get(key) || { name: q.counterparty, role, entries: [], latest: -1 };
    g.entries.push(q);
    g.latest = Math.max(g.latest, sigDate(q.quarter));
    m.set(key, g);
  }
  const all = [...m.values()];
  for (const g of all) g.entries.sort(newestFirst);
  all.sort(
    (a, b) => b.latest - a.latest || b.entries.length - a.entries.length || a.name.localeCompare(b.name)
  );
  return {
    customers: all.filter((g) => g.role === "customer"),
    suppliers: all.filter((g) => g.role === "supplier"),
  };
}

// ── Edge groups (one card per counterpart, all its contracts inside) ────────
interface Group {
  company: string;
  relationship: string;
  contracts: Contract[]; // newest first
  latest: number; // sigDate of the newest contract's source label, -1 if none
}

function groupEdges(list: { id: string; relationship: string; contracts: Contract[] }[]): Group[] {
  const m = new Map<string, Group>();
  for (const e of list) {
    const g = m.get(e.id) || { company: e.id, relationship: e.relationship, contracts: [], latest: -1 };
    for (const c of e.contracts || []) {
      g.contracts.push(c);
      g.latest = Math.max(g.latest, sigDate(c.source));
    }
    m.set(e.id, g);
  }
  const out = [...m.values()];
  for (const g of out) g.contracts.sort((a, b) => sigDate(b.source) - sigDate(a.source));
  // Most recently active counterpart first, then the one with more deals, then A→Z.
  out.sort(
    (a, b) =>
      b.latest - a.latest || b.contracts.length - a.contracts.length || a.company.localeCompare(b.company)
  );
  return out;
}

// ── Clipboard helper (mirrors the Coverage tab's 📋 button) ─────────────────
function useCopy() {
  const [copied, setCopied] = useState<string | null>(null);
  const copy = (key: string, text: string) => {
    try {
      navigator.clipboard?.writeText(text);
      setCopied(key);
      setTimeout(() => setCopied((c) => (c === key ? null : c)), 1400);
    } catch {}
  };
  return { copied, copy };
}

// ── Small presentational pieces ─────────────────────────────────────────────

// "NVIDIA Q2 FY2027" + a date chip, from one source label.
function SourceLabel({ label }: { label: string }) {
  const { text, date } = splitLabel(label);
  return (
    <>
      <span className="np-src">{text}</span>
      {date && <span className="np-date">{date}</span>}
    </>
  );
}

// `company` → `target` is the edge's real direction (source → target), which is
// what the evidence key is built from.
function ContractLine({ c, company, target }: { c: Contract; company: string; target: string }) {
  const meta = [c.units, c.value, c.date_signed, c.type]
    .filter((x) => x && x !== "no specific figure" && x !== "not stated")
    .join(" · ");
  return (
    <div className="deal-contract">
      <div className="deal-sig">{c.signal}</div>
      {meta && <div className="deal-meta">{meta}</div>}
      {c.source && (
        <div className="deal-src np-sig-head">
          <SourceLabel label={c.source} />
          <EvidenceButton kind="contract" company={company} target={target} label={c.source} signal={c.signal} />
        </div>
      )}
    </div>
  );
}

const CONTRACTS_PREVIEW = 3;

// One counterpart card in "Customers →" / "← Suppliers". Shows the deal count and
// the latest deal date in the header, the newest 3 contracts, and a toggle for the rest.
const EdgeGroupCard = memo(function EdgeGroupCard({
  g,
  onNavigate,
  company,
  target,
}: {
  g: Group;
  onNavigate: (id: string) => void;
  company: string; // edge source (for the evidence key)
  target: string; // edge target
}) {
  const [all, setAll] = useState(false);
  const n = g.contracts.length;
  const shown = all ? g.contracts : g.contracts.slice(0, CONTRACTS_PREVIEW);
  const latest = fmtDate(g.latest);
  return (
    <div className="deal-group">
      <div className="np-deal-head">
        <div className="deal-co" onClick={() => onNavigate(g.company)}>
          {g.company}
        </div>
        {n > 0 && (
          <span className="np-deal-meta">
            {n} deal{n === 1 ? "" : "s"}
            {latest ? ` · latest ${latest}` : ""}
          </span>
        )}
      </div>
      <div className="deal-rel">{g.relationship}</div>
      {shown.map((c, i) => (
        <ContractLine c={c} key={i} company={company} target={target} />
      ))}
      {n > CONTRACTS_PREVIEW && (
        <button className="np-linkbtn" onClick={() => setAll((s) => !s)}>
          {all ? "Show fewer" : `+${n - CONTRACTS_PREVIEW} more deal${n - CONTRACTS_PREVIEW === 1 ? "" : "s"}`}
        </button>
      )}
    </div>
  );
});

// One signal (quarterly_data entry).
const SigRow = memo(function SigRow({ q, company }: { q: QuarterlyData; company: string }) {
  const topics = q.topics || [];
  return (
    <div className="sig-item">
      <div className="np-sig-head">
        <SourceLabel label={q.quarter} />
        {q.chain && (
          <span className="np-chain" title={`from chain: ${q.chain}`}>
            {slugLabel(q.chain)}
          </span>
        )}
        <EvidenceButton kind="qd" company={company} label={q.quarter} signal={q.signal} />
      </div>
      <div className="sig-s">{q.signal}</div>
      {hasFigure(q.figure) && <div className="sig-f">{q.figure}</div>}
      {(q.slot || topics.length > 0) && (
        <div className="np-tags">
          {q.slot && <span className="np-tag slot">{SLOT_LABEL[q.slot] || q.slot}</span>}
          {topics.map((t) => (
            <span className="np-tag" key={t}>
              {slugLabel(t)}
            </span>
          ))}
        </div>
      )}
    </div>
  );
});

// One counterparty row in "Customers & suppliers on file": collapsed = name,
// entry count, latest date, latest figure; expanded = every entry.
const OnFileRow = memo(function OnFileRow({ g }: { g: OnFile }) {
  const [open, setOpen] = useState(false);
  const n = g.entries.length;
  const top = g.entries[0];
  const latest = fmtDate(g.latest);
  // The signal repeats the counterparty ("Customer X: …"); the row header already
  // says X, so drop that prefix when it matches exactly.
  const prefix = (g.role === "customer" ? "Customer " : "Supplier ") + g.name + ":";
  const body = (s: string) => (s.startsWith(prefix) ? s.slice(prefix.length).trim() : s);
  return (
    <div className="np-of-row">
      <button className="np-of-head" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        <span className="np-of-caret">{open ? "▾" : "▸"}</span>
        <span className="np-of-name">{g.name}</span>
        <span className="np-of-note">not a graph node</span>
        <span className="np-of-meta">
          {n} entr{n === 1 ? "y" : "ies"}
          {latest ? ` · latest ${latest}` : ""}
        </span>
      </button>
      {!open && top && hasFigure(top.figure) && <div className="np-of-fig">{top.figure}</div>}
      {open && (
        <div className="np-of-list">
          {g.entries.map((q, i) => (
            <div className="np-of-entry" key={i}>
              <div className="np-sig-head">
                <SourceLabel label={q.quarter} />
              </div>
              <div className="sig-s">{body(q.signal)}</div>
              {hasFigure(q.figure) && <div className="sig-f">{q.figure}</div>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
});

const SIG_PAGE = 8; // signals shown before "Show more"
const SIG_STEP = 12; // how many each click adds
const PLAIN_SUPPLIERS = 18; // no-deal suppliers listed before "+N more"

export default function NodePanel({
  node,
  glass,
  onClose,
  onNavigate,
}: {
  node: VizNode;
  glass: boolean;
  onClose: () => void;
  onNavigate: (id: string) => void;
}) {
  const [showReport, setShowReport] = useState(false);
  const [report, setReport] = useState<any>(null);
  const [topic, setTopic] = useState<string | null>(null); // active topic chip
  const [filter, setFilter] = useState(""); // free-text signal filter
  const [sigLimit, setSigLimit] = useState(SIG_PAGE);
  const [allPlain, setAllPlain] = useState(false);
  const { copied, copy } = useCopy();

  // Reset per-node view state.
  useEffect(() => {
    setShowReport(false);
    setTopic(null);
    setFilter("");
    setSigLimit(SIG_PAGE);
    setAllPlain(false);
  }, [node.id]);

  // Esc closes the panel. The handler lives on `window` for the panel's whole
  // life; a ref hands it the CURRENT onClose so we never re-subscribe just because
  // the parent passed a fresh arrow function.
  const onCloseRef = useRef(onClose);
  useEffect(() => {
    onCloseRef.current = onClose;
  });
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onCloseRef.current();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // Lazy-load the reports bundle once, when a report is first opened.
  useEffect(() => {
    if (!showReport || report) return;
    fetchJson<Record<string, any>>("/data/reports.bundle.json").then((rb) =>
      setReport(rb[node.id] || null)
    );
  }, [showReport, report, node.id]);

  const badges = useMemo(() => buildBadges(node.quarterly_data), [node]);
  const timeline = useMemo(() => buildTimeline(node.quarterly_data), [node]);
  const slots = useMemo(() => latestBySlot(node.quarterly_data), [node]);
  const onFile = useMemo(() => groupOnFile(node.quarterly_data), [node]);
  // The company's OWN signals: counterparty entries are shown in their own
  // section below, so they are left out here to keep long nodes readable.
  const ownSigs = useMemo(
    () => node.quarterly_data.filter((q) => !q.counterparty).sort(newestFirst),
    [node]
  );
  const topicCounts = useMemo(() => {
    const c = new Map<string, number>();
    for (const q of ownSigs) for (const t of q.topics || []) c.set(t, (c.get(t) || 0) + 1);
    return [...c.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  }, [ownSigs]);
  const filteredSigs = useMemo(() => {
    const f = filter.trim().toLowerCase();
    return ownSigs.filter(
      (q) =>
        (!topic || (q.topics || []).includes(topic)) &&
        (!f || `${q.quarter} ${q.signal} ${q.figure}`.toLowerCase().includes(f))
    );
  }, [ownSigs, topic, filter]);
  // A new filter starts the list from the top again.
  useEffect(() => {
    setSigLimit(SIG_PAGE);
  }, [topic, filter]);

  const customers = useMemo(
    () =>
      groupEdges(
        node.outgoing.map((e) => ({ id: e.target, relationship: e.relationship, contracts: e.contracts }))
      ),
    [node]
  );
  const suppliers = useMemo(
    () =>
      groupEdges(
        node.incoming.map((e) => ({ id: e.source, relationship: e.relationship, contracts: e.contracts }))
      ),
    [node]
  );
  const exposure = useMemo(() => nodeExposure(node), [node]);
  const dealSuppliers = suppliers.filter((s) => s.contracts.length > 0);
  const plainAll = suppliers.filter((s) => s.contracts.length === 0);
  const plainSuppliers = allPlain ? plainAll : plainAll.slice(0, PLAIN_SUPPLIERS);

  const isUS = node.exchange && US.has(node.exchange) && node.ticker;
  const accent = GROUP_COLORS[node.primary] || "#94a3b8";
  const tvUrl = tradingViewUrl(node.ticker, node.exchange);
  const ySym = yahooSymbol(node.ticker, node.exchange);
  const yahooUrl = ySym ? `https://finance.yahoo.com/quote/${encodeURIComponent(ySym)}/` : null;

  const shownSigs = filteredSigs.slice(0, sigLimit);
  const hiddenSigs = filteredSigs.length - shownSigs.length;
  const onFileCount = onFile.customers.length + onFile.suppliers.length;

  return (
    <div className="panel-backdrop" onClick={onClose}>
      <div
        className={"panel" + (glass ? " glass" : "")}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={node.id}
      >
        {glass && <div className="pacc" style={{ background: accent }} />}
        <button className="panel-close" onClick={onClose} aria-label="Close (Esc)" title="Close (Esc)">
          ✕
        </button>

        <div className="panel-head">
          {node.logo && (
            <span className={"logochip" + (node.logoBg === "dark" ? " dk" : "")}>
              <img src={node.logo} alt="" />
            </span>
          )}
          <h2 className="panel-title">{node.id}</h2>
        </div>

        <div className="panel-meta">
          {node.ticker && (
            <span className="tag">
              {node.ticker}
              {node.exchange ? ` · ${node.exchange}` : ""}
            </span>
          )}
          {node.country && (
            <span title={node.country}>
              {FLAG[node.country] ? `${FLAG[node.country]} ${node.country}` : node.country}
            </span>
          )}
          {node.status && <span className={"np-status " + node.status}>{node.status}</span>}
          {node.lastData ? (
            <span className="muted">
              last data {node.lastData}
              {node.stale ? " · stale" : ""}
            </span>
          ) : (
            <span className="muted">no signals yet</span>
          )}
        </div>

        <div className="np-actions">
          {node.ticker && (
            <button
              className="copy-btn"
              title="Copy ticker"
              onClick={() => copy("ticker", node.ticker as string)}
            >
              {copied === "ticker" ? "✓ copied" : `📋 ${node.ticker}`}
            </button>
          )}
          {tvUrl && (
            <a className="copy-btn" href={tvUrl} target="_blank" rel="noopener noreferrer">
              ↗ TradingView
            </a>
          )}
          {yahooUrl && (
            <a className="copy-btn" href={yahooUrl} target="_blank" rel="noopener noreferrer">
              ↗ Yahoo Finance
            </a>
          )}
          <button
            className="copy-btn"
            title={`Copy "Transcript:${node.id}" — the enrichment command for Claude Code`}
            onClick={() => copy("transcript", `Transcript:${node.id}`)}
          >
            {copied === "transcript" ? "✓ copied" : "📋 Transcript"}
          </button>
        </div>

        {isUS ? (
          <TradingViewChart symbol={`${node.exchange}:${node.ticker}`} />
        ) : node.ticker ? (
          <LiveQuote ticker={node.ticker} exchange={node.exchange} />
        ) : null}
        {node.ticker && <Fundamentals ticker={node.ticker} exchange={node.exchange} />}

        <div className="panel-btns">
          {node.hasReport && (
            <button className="btn" onClick={() => setShowReport((s) => !s)}>
              📊 {showReport ? "Hide" : "Stock"} Report
            </button>
          )}
          {node.hasReport && (
            <button
              className="btn"
              onClick={() =>
                window.open(`/report/${encodeURIComponent(node.id)}`, "_blank", "noopener")
              }
            >
              📄 Download PDF
            </button>
          )}
        </div>

        {showReport && (
          <div className="repbox">
            {report ? <ReportView report={report} /> : <p className="muted">Loading report…</p>}
          </div>
        )}

        {slots.length > 0 && (
          <>
            <div className="pcol-head">Latest by slot</div>
            <div className="np-slots">
              {slots.map((s) => {
                const lab = splitLabel(s.q.quarter);
                const fig = hasFigure(s.q.figure);
                return (
                  <div className="np-slot" key={s.key} title={`${s.q.signal}\n\n${s.q.quarter}`}>
                    <div className="np-slot-k">{s.label}</div>
                    <div className={"np-slot-v" + (fig ? " fig" : "")}>{fig ? s.q.figure : s.q.signal}</div>
                    <div className="np-slot-d">
                      {lab.date ? `${lab.date} · ` : ""}
                      {lab.text}
                    </div>
                  </div>
                );
              })}
            </div>
          </>
        )}

        {badges.length > 0 && (
          <div className="badge-row">
            {badges.map((b) => (
              <span key={b.key} className="status-badge" style={{ borderColor: b.color, color: b.color }}>
                {b.label}
              </span>
            ))}
          </div>
        )}

        <div className="badge-row">
          {node.layers.map((l) => (
            <span key={l} className="pill filled" style={{ background: GROUP_COLORS[l] }}>
              {GROUP_NAMES[l] || l}
            </span>
          ))}
          {node.domains.map((d) => (
            <span key={d} className="pill filled" style={{ background: GROUP_COLORS[d] }}>
              {GROUP_NAMES[d] || d}
            </span>
          ))}
        </div>
        <div className="badge-row">
          {node.chains.map((c) => (
            <span key={c} className="pill outline">
              {slugLabel(c)}
            </span>
          ))}
        </div>

        {node.products.length > 0 && (
          <div className="prod-cards">
            {node.products.map((p, i) => (
              <div className="prod-card" key={i}>
                <div className="prod-chain">{slugLabel(p.chain)}</div>
                <div className="prod-name">{p.product}</div>
              </div>
            ))}
          </div>
        )}

        {exposure.length > 0 && (
          <div className="gen-exposure">
            <div className="pcol-head">Generation exposure</div>
            {exposure.map((x) => (
              <div className="gen-exp-row" key={x.t.key}>
                <span>
                  {x.status === "retained" ? "✅" : x.status === "gained" ? "📈" : "⚠️"}
                </span>
                <span className="gen-exp-label">{x.t.label}</span>
                <span className="gen-exp-note">
                  {x.status === "retained" &&
                    (x.productFrom && x.productTo && x.productFrom !== x.productTo ? (
                      <>
                        {x.productFrom} <span className="gen-arrow">→</span> {x.productTo}
                      </>
                    ) : (
                      "retained"
                    ))}
                  {x.status === "gained" && <>new entrant — {x.productTo}</>}
                  {x.status === "lost" && "not in next-gen chain (lost socket, or not yet added)"}
                </span>
              </div>
            ))}
          </div>
        )}

        <div className="pgrid">
          <div className="pcol">
            {timeline.length > 0 && (
              <>
                <div className="pcol-head">Product / Capacity Timeline</div>
                {timeline.map((t, i) => (
                  <div className="tl-item" key={i}>
                    <span className="tl-when">{t.when}</span>
                    <span>{t.text}</span>
                  </div>
                ))}
              </>
            )}
            {ownSigs.length > 0 && (
              <>
                <div className="pcol-head" style={{ marginTop: timeline.length ? "1rem" : 0 }}>
                  Signals
                </div>
                <div className="np-sigtools">
                  <input
                    type="search"
                    className="np-filter"
                    placeholder={`Filter ${ownSigs.length} signals…`}
                    value={filter}
                    onChange={(e) => setFilter(e.target.value)}
                    onKeyDown={(e) => {
                      // Esc with text in the box clears the box; the panel only
                      // closes on a second Esc (stopPropagation keeps this one local).
                      if (e.key === "Escape" && filter) {
                        e.stopPropagation();
                        setFilter("");
                      }
                    }}
                  />
                  {topicCounts.length > 0 && (
                    <div className="np-chips">
                      <button
                        className={"np-chip" + (topic === null ? " on" : "")}
                        onClick={() => setTopic(null)}
                      >
                        All<b>{ownSigs.length}</b>
                      </button>
                      {topicCounts.map(([t, n]) => (
                        <button
                          key={t}
                          className={"np-chip" + (topic === t ? " on" : "")}
                          onClick={() => setTopic(topic === t ? null : t)}
                          title={`timeline topic: ${t}`}
                        >
                          {slugLabel(t)}
                          <b>{n}</b>
                        </button>
                      ))}
                    </div>
                  )}
                </div>
                {(topic || filter) && (
                  <div className="np-count">
                    {filteredSigs.length} of {ownSigs.length} signals match
                  </div>
                )}
                {shownSigs.map((q, i) => (
                  <SigRow q={q} company={node.id} key={q.quarter + "|" + i} />
                ))}
                {filteredSigs.length === 0 && <div className="np-empty">No signals match this filter.</div>}
                {(hiddenSigs > 0 || sigLimit > SIG_PAGE) && (
                  <div className="np-more">
                    {hiddenSigs > 0 && (
                      <button className="btn np-btn-sm" onClick={() => setSigLimit((l) => l + SIG_STEP)}>
                        Show {Math.min(hiddenSigs, SIG_STEP)} more ({hiddenSigs} hidden)
                      </button>
                    )}
                    {sigLimit > SIG_PAGE && (
                      <button className="btn np-btn-sm" onClick={() => setSigLimit(SIG_PAGE)}>
                        Show less
                      </button>
                    )}
                  </div>
                )}
              </>
            )}
          </div>

          <div className="pcol">
            {customers.length > 0 && (
              <>
                <div className="pcol-head">Customers →</div>
                {customers.map((g) => (
                  <EdgeGroupCard g={g} key={g.company} onNavigate={onNavigate} company={node.id} target={g.company} />
                ))}
              </>
            )}
            {(dealSuppliers.length > 0 || plainAll.length > 0) && (
              <>
                <div className="pcol-head" style={{ marginTop: customers.length ? "1rem" : 0 }}>
                  ← Suppliers
                </div>
                {dealSuppliers.map((g) => (
                  <EdgeGroupCard g={g} key={g.company} onNavigate={onNavigate} company={g.company} target={node.id} />
                ))}
                {plainAll.length > 0 && (
                  <div className="deal-plain">
                    {plainSuppliers.map((s, i) => (
                      <span key={s.company}>
                        <span className="deal-link" onClick={() => onNavigate(s.company)}>
                          {s.company}
                        </span>
                        {i < plainSuppliers.length - 1 ? ", " : ""}
                      </span>
                    ))}
                    {plainAll.length > PLAIN_SUPPLIERS && (
                      <>
                        {" "}
                        <button className="np-linkbtn" onClick={() => setAllPlain((s) => !s)}>
                          {allPlain ? "show fewer" : `+${plainAll.length - PLAIN_SUPPLIERS} more`}
                        </button>
                      </>
                    )}
                  </div>
                )}
              </>
            )}
          </div>
        </div>

        {onFileCount > 0 && (
          <div className="np-onfile">
            <div className="pcol-head">
              Customers &amp; suppliers on file{" "}
              <span className="np-of-hint">
                — named in this company&apos;s filings / calls, not graph nodes
              </span>
            </div>
            <div className="pgrid" style={{ marginTop: 0 }}>
              <div className="pcol">
                <div className="np-of-sub">Customers ({onFile.customers.length})</div>
                {onFile.customers.length === 0 && <div className="np-empty">none on file</div>}
                {onFile.customers.map((g) => (
                  <OnFileRow g={g} key={g.name} />
                ))}
              </div>
              <div className="pcol">
                <div className="np-of-sub">Suppliers ({onFile.suppliers.length})</div>
                {onFile.suppliers.length === 0 && <div className="np-empty">none on file</div>}
                {onFile.suppliers.map((g) => (
                  <OnFileRow g={g} key={g.name} />
                ))}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
