"use client";

import { memo, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import type { VizNode, Contract, QuarterlyData } from "@/lib/types";
import { SOURCE_KINDS, sourceDetail, sourceType, type SourceKind } from "@/lib/sourceKind";
import { buildBadges, buildTimeline, sigDate, FLAG } from "@/lib/signals";
import { GROUP_COLORS, groupName, slugLabel } from "@/lib/taxonomy";
import { t, tr, trJoined, name, useLang } from "@/lib/i18n";
import { nodeExposure } from "@/lib/transitions";
import { fetchJson } from "@/lib/data";
import { yahooSymbol } from "@/lib/yahoo";
import ReportView from "./ReportView";
import TradingViewChart from "./TradingViewChart";
import LiveQuote from "./LiveQuote";
import Fundamentals from "./Fundamentals";
import { EvidenceButton } from "./Evidence";
import { ExpandAllContext, SignalBody, SourceBadge, SourceText } from "./SignalText";
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

// The head row of every entry: source-type badge · date chip · what the source
// is ("Q2 FY2027", a release headline …). `viewer` is the panel's company — its
// own name is dropped from its own labels; another company's label stays whole.
// `children` (chain name, evidence button) follow on the same row.
function SourceHead({ label, viewer, children }: { label: string; viewer: string; children?: ReactNode }) {
  const { date } = splitLabel(label);
  const detail = sourceDetail(label, viewer);
  return (
    <div className="np-sig-head">
      <SourceBadge label={label} />
      {date && <span className="np-date">{date}</span>}
      {/* Cut to one line; when it is cut, click / Enter shows the full label. */}
      {detail && <SourceText label={label} short={detail} className="np-src np-src-1" />}
      {children}
    </div>
  );
}

// `company` → `target` is the edge's real direction (source → target), which is
// what the evidence key is built from; `viewer` is the panel's company.
function ContractLine({ c, company, target, viewer }: { c: Contract; company: string; target: string; viewer: string }) {
  const meta = [c.units, c.value, c.date_signed, c.type]
    .filter((x) => x && x !== "no specific figure" && x !== "not stated")
    .map(tr)
    .join(" · ");
  return (
    <div className="deal-contract">
      {c.source && (
        <SourceHead label={c.source} viewer={viewer}>
          <EvidenceButton kind="contract" company={company} target={target} label={c.source} signal={c.signal} />
        </SourceHead>
      )}
      {/* units · value · date · type is the deal's short summary → headline. */}
      <SignalBody headline={meta || undefined} text={tr(c.signal)} />
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
  viewer,
}: {
  g: Group;
  onNavigate: (id: string) => void;
  company: string; // edge source (for the evidence key)
  target: string; // edge target
  viewer: string; // the panel's company
}) {
  useLang(); // memo() rows still re-render on a language change
  const [all, setAll] = useState(false);
  const n = g.contracts.length;
  const shown = all ? g.contracts : g.contracts.slice(0, CONTRACTS_PREVIEW);
  const latest = fmtDate(g.latest);
  return (
    <div className="deal-group">
      <div className="np-deal-head">
        <div className="deal-co" onClick={() => onNavigate(g.company)}>
          {name(g.company)}
        </div>
        {n > 0 && (
          <span className="np-deal-meta">
            {t(n === 1 ? "{n} deal" : "{n} deals", { n })}
            {latest ? " · " + t("latest {date}", { date: latest }) : ""}
          </span>
        )}
      </div>
      <div className="deal-rel">{tr(g.relationship)}</div>
      {shown.map((c, i) => (
        <ContractLine c={c} key={i} company={company} target={target} viewer={viewer} />
      ))}
      {n > CONTRACTS_PREVIEW && (
        <button className="np-linkbtn" onClick={() => setAll((s) => !s)}>
          {all ? t("Show fewer") : t(n - CONTRACTS_PREVIEW === 1 ? "+{n} more deal" : "+{n} more deals", { n: n - CONTRACTS_PREVIEW })}
        </button>
      )}
    </div>
  );
});

// One signal (quarterly_data entry): source head, the figure as the headline,
// the signal clamped to two lines, tags on the More / Less row.
const SigRow = memo(function SigRow({ q, company }: { q: QuarterlyData; company: string }) {
  useLang();
  const topics = q.topics || [];
  const tags =
    q.slot || topics.length > 0 ? (
      <>
        {q.slot && <span className="np-tag slot">{SLOT_LABEL[q.slot] ? t(SLOT_LABEL[q.slot]) : q.slot}</span>}
        {topics.map((tp) => (
          <span className="np-tag" key={tp}>
            {slugLabel(tp)}
          </span>
        ))}
      </>
    ) : null;
  return (
    <div className="sig-item">
      <SourceHead label={q.quarter} viewer={company}>
        {q.chain && (
          <span className="np-chain" title={t("from chain: {chain}", { chain: slugLabel(q.chain) })}>
            {slugLabel(q.chain)}
          </span>
        )}
        <EvidenceButton kind="qd" company={company} label={q.quarter} signal={q.signal} />
      </SourceHead>
      <SignalBody headline={hasFigure(q.figure) ? tr(q.figure) : undefined} text={tr(q.signal)} footer={tags} />
    </div>
  );
});

// One counterparty row in "Customers & suppliers on file": collapsed = name,
// entry count, latest date, latest figure; expanded = every entry.
const OnFileRow = memo(function OnFileRow({ g, company }: { g: OnFile; company: string }) {
  useLang();
  const [open, setOpen] = useState(false);
  const n = g.entries.length;
  const top = g.entries[0];
  const latest = fmtDate(g.latest);
  // The signal repeats the counterparty ("Customer X: …"); the row header already
  // says X, so drop that prefix when it matches exactly.
  const prefix = (g.role === "customer" ? "Customer " : "Supplier ") + g.name + ":";
  // A translated signal is shown whole (the prefix is inside the translation).
  const body = (s: string) => (tr(s) !== s ? tr(s) : s.startsWith(prefix) ? s.slice(prefix.length).trim() : s);
  return (
    <div className="np-of-row">
      <button className="np-of-head" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        <span className="np-of-caret">{open ? "▾" : "▸"}</span>
        <span className="np-of-name">{g.name}</span>
        <span className="np-of-note">{t("not a graph node")}</span>
        <span className="np-of-meta">
          {t(n === 1 ? "{n} entry" : "{n} entries", { n })}
          {latest ? " · " + t("latest {date}", { date: latest }) : ""}
        </span>
      </button>
      {!open && top && hasFigure(top.figure) && <div className="np-of-fig">{tr(top.figure)}</div>}
      {open && (
        <div className="np-of-list">
          {g.entries.map((q, i) => (
            <div className="np-of-entry" key={i}>
              <SourceHead label={q.quarter} viewer={company} />
              <SignalBody headline={hasFigure(q.figure) ? tr(q.figure) : undefined} text={body(q.signal)} />
            </div>
          ))}
        </div>
      )}
    </div>
  );
});

// ── "At a glance" summary card (top of the panel, added 2026-10-01) ─────────
// With 818 companies the panel had become one long list. The card answers the
// first questions in one screen: what does the company make, what do the five
// screener slots say, and who are its biggest customers / suppliers. Everything
// below the card is the same detail as before, with long lists collapsed.

const GLANCE_PRODUCTS = 4; // product chips shown before "+N more"
const GLANCE_PARTNERS = 5; // top customers / suppliers shown per side
const GLANCE_SNIPPET = 140; // characters of a signal shown when the slot has no figure

// Cut a (translated) text to `max` characters on a word boundary, adding "…".
function snippet(text: string, max: number): string {
  if (text.length <= max) return text;
  const cut = text.slice(0, max);
  const space = cut.lastIndexOf(" ");
  return (space > max * 0.6 ? cut.slice(0, space) : cut).trimEnd() + "…";
}

// Biggest counterparts first: the most contracts on the edge, then the most
// recently active one, then A→Z. Takes the groups groupEdges() already built.
function topPartners(groups: Group[], max: number): Group[] {
  return [...groups]
    .sort(
      (a, b) =>
        b.contracts.length - a.contracts.length || b.latest - a.latest || a.company.localeCompare(b.company)
    )
    .slice(0, max);
}

// One slot row of the card: label, the short figure (or a trimmed signal), the
// source date, and a toggle that shows the full signal in place.
const GlanceSlot = memo(function GlanceSlot({
  label,
  q,
  company,
}: {
  label: string;
  q: QuarterlyData;
  company: string;
}) {
  useLang();
  const [open, setOpen] = useState(false);
  const lab = splitLabel(q.quarter);
  const fig = hasFigure(q.figure);
  const signal = tr(q.signal);
  return (
    <div className="np-gl-slot">
      <div className="np-gl-slot-k">{t(label)}</div>
      <div className="np-gl-slot-body">
        <div className={"np-gl-slot-v" + (fig ? " fig" : "")}>{fig ? tr(q.figure) : snippet(signal, GLANCE_SNIPPET)}</div>
        <div className="np-gl-slot-d">
          <SourceBadge label={q.quarter} />
          {lab.date && <span className="np-date">{lab.date}</span>}
          <span className="np-src">{lab.text}</span>
          <button className="np-linkbtn np-gl-more" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
            {open ? t("Hide details") : t("Full signal")}
          </button>
        </div>
        {open && (
          <div className="np-gl-full">
            <div className="sig-s">{signal}</div>
            <div className="np-sig-head">
              <EvidenceButton kind="qd" company={company} label={q.quarter} signal={q.signal} />
            </div>
          </div>
        )}
      </div>
    </div>
  );
});

// One side of "Key relationships": up to five clickable counterparts.
function GlancePartners({
  title,
  groups,
  total,
  onNavigate,
}: {
  title: string;
  groups: Group[];
  total: number;
  onNavigate: (id: string) => void;
}) {
  if (groups.length === 0) return null;
  return (
    <div className="np-gl-side">
      <div className="np-gl-sub">
        {title}
        {total > groups.length && <span> · {t("top {n} of {total}", { n: groups.length, total })}</span>}
      </div>
      <div className="np-gl-partners">
        {groups.map((g) => {
          const n = g.contracts.length;
          return (
            <button
              key={g.company}
              className="np-gl-partner"
              onClick={() => onNavigate(g.company)}
              title={tr(g.relationship)}
            >
              <span className="np-gl-partner-name">{name(g.company)}</span>
              {n > 0 && <span className="np-gl-partner-n">{t(n === 1 ? "{n} deal" : "{n} deals", { n })}</span>}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function GlanceCard({
  node,
  slots,
  customers,
  suppliers,
  onNavigate,
}: {
  node: VizNode;
  slots: { key: Slot; label: string; q: QuarterlyData }[];
  customers: Group[];
  suppliers: Group[];
  onNavigate: (id: string) => void;
}) {
  const [allProducts, setAllProducts] = useState(false);
  // Product line chips: one per (chain, product) placement, duplicates dropped.
  const products = useMemo(() => {
    const seen = new Set<string>();
    return node.products.filter((p) => {
      const k = p.chain + "|" + p.product;
      if (seen.has(k)) return false;
      seen.add(k);
      return true;
    });
  }, [node]);
  const topCustomers = useMemo(() => topPartners(customers, GLANCE_PARTNERS), [customers]);
  const topSuppliers = useMemo(() => topPartners(suppliers, GLANCE_PARTNERS), [suppliers]);
  const shownProducts = allProducts ? products : products.slice(0, GLANCE_PRODUCTS);

  if (products.length === 0 && slots.length === 0 && topCustomers.length === 0 && topSuppliers.length === 0)
    return null;

  return (
    <section className="np-glance" aria-label={t("At a glance")}>
      <div className="np-gl-head">{t("At a glance")}</div>

      {products.length > 0 && (
        <div className="np-gl-products">
          {shownProducts.map((p) => (
            <span className="np-gl-chip" key={p.chain + "|" + p.product} title={tr(p.product)}>
              <b>{slugLabel(p.chain)}</b>
              <span>{tr(p.product)}</span>
            </span>
          ))}
          {products.length > GLANCE_PRODUCTS && (
            <button className="np-linkbtn" onClick={() => setAllProducts((s) => !s)}>
              {allProducts ? t("show fewer") : t("+{n} more", { n: products.length - GLANCE_PRODUCTS })}
            </button>
          )}
        </div>
      )}

      {slots.length > 0 && (
        <div className="np-gl-slots">
          {slots.map((s) => (
            <GlanceSlot key={s.key} label={s.label} q={s.q} company={node.id} />
          ))}
        </div>
      )}

      {(topCustomers.length > 0 || topSuppliers.length > 0) && (
        <div className="np-gl-rel">
          <GlancePartners title={t("Top customers") + " →"} groups={topCustomers} total={customers.length} onNavigate={onNavigate} />
          <GlancePartners title={"← " + t("Top suppliers")} groups={topSuppliers} total={suppliers.length} onNavigate={onNavigate} />
        </div>
      )}
    </section>
  );
}

// ── Long lists below the card: newest LIST_PREVIEW items, then "Show all (N)" ─
const LIST_PREVIEW = 5;

function ShowAllToggle({ total, open, onToggle }: { total: number; open: boolean; onToggle: () => void }) {
  if (total <= LIST_PREVIEW) return null;
  return (
    <button className="np-linkbtn np-showall" onClick={onToggle} aria-expanded={open}>
      {open ? t("Show less") : t("Show all ({n})", { n: total })}
    </button>
  );
}

const SIG_PAGE = LIST_PREVIEW; // signals shown before "Show more" (was 8 before 2026-10-01)
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
  const { rev } = useLang();
  const [showReport, setShowReport] = useState(false);
  const [report, setReport] = useState<any>(null);
  const [topic, setTopic] = useState<string | null>(null); // active topic chip
  const [srcKind, setSrcKind] = useState<SourceKind | null>(null); // active source-type chip
  const [expandAll, setExpandAll] = useState(false); // every signal / deal in full
  const [filter, setFilter] = useState(""); // free-text signal filter
  const [sigLimit, setSigLimit] = useState(SIG_PAGE);
  const [allPlain, setAllPlain] = useState(false);
  // Which long lists the user expanded with "Show all (N)" (keys: "timeline",
  // "customers", "suppliers", "products", "onfile-c", "onfile-s").
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const isOpen = (key: string) => expanded.has(key);
  const toggleOpen = (key: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      next.has(key) ? next.delete(key) : next.add(key);
      return next;
    });
  // The first LIST_PREVIEW items of a list, or all of them once expanded.
  const preview = <T,>(key: string, list: T[]): T[] => (isOpen(key) ? list : list.slice(0, LIST_PREVIEW));
  const { copied, copy } = useCopy();
  const backdropRef = useRef<HTMLDivElement>(null);

  // Reset per-node view state.
  useEffect(() => {
    setShowReport(false);
    setTopic(null);
    setSrcKind(null);
    setExpandAll(false);
    setFilter("");
    setSigLimit(SIG_PAGE);
    setAllPlain(false);
    setExpanded(new Set());
    // Opening another company from inside the panel starts at its "At a glance"
    // card, not at the scroll position of the previous company.
    backdropRef.current?.scrollTo({ top: 0 });
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
  // Source-type chips (Earnings / Filings / Releases / Decks / Q&A …): how many
  // of the company's own signals come from each kind of document. Only kinds that
  // occur get a chip, in the fixed SOURCE_KINDS order.
  const sigKind = useMemo(() => new Map(ownSigs.map((q) => [q, sourceType(q.quarter).kind])), [ownSigs]);
  const kindCounts = useMemo(() => {
    const c = new Map<SourceKind, number>();
    for (const k of sigKind.values()) c.set(k, (c.get(k) || 0) + 1);
    return SOURCE_KINDS.filter((s) => c.has(s.kind)).map((s) => ({ ...s, n: c.get(s.kind) as number }));
  }, [sigKind]);
  const filteredSigs = useMemo(() => {
    const f = filter.trim().toLowerCase();
    // Search the English text and what is on screen (the translation).
    return ownSigs.filter(
      (q) =>
        (!topic || (q.topics || []).includes(topic)) &&
        (!srcKind || sigKind.get(q) === srcKind) &&
        (!f || `${q.quarter} ${q.signal} ${q.figure} ${tr(q.signal)} ${tr(q.figure)}`.toLowerCase().includes(f))
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ownSigs, sigKind, topic, srcKind, filter, rev]);
  // A new filter starts the list from the top again.
  useEffect(() => {
    setSigLimit(SIG_PAGE);
  }, [topic, srcKind, filter]);

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
    <ExpandAllContext.Provider value={expandAll}>
    <div className="panel-backdrop" onClick={onClose} ref={backdropRef}>
      <div
        className={"panel" + (glass ? " glass" : "")}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={name(node.id)}
      >
        {glass && <div className="pacc" style={{ background: accent }} />}
        <button className="panel-close" onClick={onClose} aria-label={t("Close (Esc)")} title={t("Close (Esc)")}>
          ✕
        </button>

        <div className="panel-head">
          {node.logo && (
            <span className={"logochip" + (node.logoBg === "dark" ? " dk" : "")}>
              <img src={node.logo} alt="" />
            </span>
          )}
          <h2 className="panel-title">
            {name(node.id)}
            {name(node.id) !== node.id && <span className="panel-title-en">{node.id}</span>}
          </h2>
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
          {node.status && <span className={"np-status " + node.status}>{t(node.status)}</span>}
          {node.lastData ? (
            <span className="muted">
              {t("last data {date}", { date: node.lastData })}
              {node.stale ? " · " + t("stale") : ""}
            </span>
          ) : (
            <span className="muted">{t("no signals yet")}</span>
          )}
        </div>

        <div className="np-actions">
          {node.ticker && (
            <button
              className="copy-btn"
              title={t("Copy ticker")}
              onClick={() => copy("ticker", node.ticker as string)}
            >
              {copied === "ticker" ? "✓ " + t("copied") : `📋 ${node.ticker}`}
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
            title={t("Copy \"Transcript:{id}\" — the enrichment command for Claude Code", { id: node.id })}
            onClick={() => copy("transcript", `Transcript:${node.id}`)}
          >
            {copied === "transcript" ? "✓ " + t("copied") : "📋 " + t("Transcript")}
          </button>
        </div>

        {isUS ? (
          <TradingViewChart symbol={`${node.exchange}:${node.ticker}`} />
        ) : node.ticker ? (
          <LiveQuote ticker={node.ticker} exchange={node.exchange} />
        ) : null}
        {node.ticker && <Fundamentals ticker={node.ticker} exchange={node.exchange} />}

        {/* "At a glance" sits under the price + chart (user, 2026-10-01). */}
        <GlanceCard node={node} slots={slots} customers={customers} suppliers={suppliers} onNavigate={onNavigate} />

        {/* Rendered only with a report, so an empty row adds no extra gap under the card. */}
        {node.hasReport && (
        <div className="panel-btns">
          {node.hasReport && (
            <button className="btn" onClick={() => setShowReport((s) => !s)}>
              📊 {showReport ? t("Hide Report") : t("Stock Report")}
            </button>
          )}
          {node.hasReport && (
            <button
              className="btn"
              onClick={() =>
                window.open(`/report/${encodeURIComponent(node.id)}`, "_blank", "noopener")
              }
            >
              📄 {t("Download PDF")}
            </button>
          )}
        </div>
        )}

        {showReport && (
          <div className="repbox">
            {report ? <ReportView report={report} /> : <p className="muted">{t("Loading report…")}</p>}
          </div>
        )}

        {/* "Latest by slot" lived here until 2026-10-01; the same five slots
            (same latest-dated rule) are now shown in the "At a glance" card at the top. */}

        {badges.length > 0 && (
          <div className="badge-row">
            {badges.map((b) => (
              <span key={b.key} className="status-badge" style={{ borderColor: b.color, color: b.color }}>
                {t(b.label)}
              </span>
            ))}
          </div>
        )}

        <div className="badge-row">
          {node.layers.map((l) => (
            <span key={l} className="pill filled" style={{ background: GROUP_COLORS[l] }}>
              {groupName(l)}
            </span>
          ))}
          {node.domains.map((d) => (
            <span key={d} className="pill filled" style={{ background: GROUP_COLORS[d] }}>
              {groupName(d)}
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
            {preview("products", node.products).map((p, i) => (
              <div className="prod-card" key={i}>
                <div className="prod-chain">{slugLabel(p.chain)}</div>
                <div className="prod-name">{tr(p.product)}</div>
              </div>
            ))}
            <ShowAllToggle total={node.products.length} open={isOpen("products")} onToggle={() => toggleOpen("products")} />
          </div>
        )}

        {exposure.length > 0 && (
          <div className="gen-exposure">
            <div className="pcol-head">{t("Generation exposure")}</div>
            {exposure.map((x) => (
              <div className="gen-exp-row" key={x.t.key}>
                <span>
                  {x.status === "retained" ? "✅" : x.status === "gained" ? "📈" : "⚠️"}
                </span>
                <span className="gen-exp-label">{t(x.t.label)}</span>
                <span className="gen-exp-note">
                  {x.status === "retained" &&
                    (x.productFrom && x.productTo && x.productFrom !== x.productTo ? (
                      <>
                        {trJoined(x.productFrom)} <span className="gen-arrow">→</span> {trJoined(x.productTo)}
                      </>
                    ) : (
                      t("retained")
                    ))}
                  {x.status === "gained" && <>{t("new entrant")} — {trJoined(x.productTo)}</>}
                  {x.status === "lost" && t("not in next-gen chain (lost socket, or not yet added)")}
                </span>
              </div>
            ))}
          </div>
        )}

        <div className="pgrid">
          <div className="pcol">
            {timeline.length > 0 && (
              <>
                <div className="pcol-head">{t("Product / Capacity Timeline")}</div>
                {preview("timeline", timeline).map((item, i) => (
                  <div className="tl-item" key={i}>
                    <span className="tl-when">{item.when}</span>
                    <span>{tr(item.text)}</span>
                  </div>
                ))}
                <ShowAllToggle total={timeline.length} open={isOpen("timeline")} onToggle={() => toggleOpen("timeline")} />
              </>
            )}
            {ownSigs.length > 0 && (
              <>
                <div className="pcol-head np-sig-title" style={{ marginTop: timeline.length ? "1rem" : 0 }}>
                  <span>{t("Signals")}</span>
                  {/* Long entries are clamped to two lines; this opens every
                      signal and deal in the panel at once (and closes them). */}
                  <button
                    type="button"
                    className="np-linkbtn np-expand"
                    aria-pressed={expandAll}
                    onClick={() => setExpandAll((v) => !v)}
                    title={t("Show every signal and deal in this panel in full")}
                  >
                    {expandAll ? t("Collapse all") : t("Expand all")}
                  </button>
                </div>
                <div className="np-sigtools">
                  <input
                    type="search"
                    className="np-filter"
                    placeholder={t("Filter {n} signals…", { n: ownSigs.length })}
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
                  {/* Source-type chips: only when the signals come from 2+ kinds of
                      document. Click one to keep only that kind; click again for all. */}
                  {kindCounts.length > 1 && (
                    <div className="np-chips np-kinds" role="group" aria-label={t("Filter signals by source type")}>
                      {kindCounts.map((k) => (
                        <button
                          key={k.kind}
                          type="button"
                          className={"np-chip np-kind sx-k-" + k.kind + (srcKind === k.kind ? " on" : "")}
                          aria-pressed={srcKind === k.kind}
                          onClick={() => setSrcKind(srcKind === k.kind ? null : k.kind)}
                        >
                          <i aria-hidden="true" />
                          {t(k.label)}
                          <b>{k.n}</b>
                        </button>
                      ))}
                    </div>
                  )}
                  {topicCounts.length > 0 && (
                    <div className="np-chips">
                      <button
                        className={"np-chip" + (topic === null ? " on" : "")}
                        onClick={() => setTopic(null)}
                      >
                        {t("All")}<b>{ownSigs.length}</b>
                      </button>
                      {topicCounts.map(([tp, n]) => (
                        <button
                          key={tp}
                          className={"np-chip" + (topic === tp ? " on" : "")}
                          onClick={() => setTopic(topic === tp ? null : tp)}
                          title={t("timeline topic: {topic}", { topic: slugLabel(tp) })}
                        >
                          {slugLabel(tp)}
                          <b>{n}</b>
                        </button>
                      ))}
                    </div>
                  )}
                </div>
                {(topic || srcKind || filter) && (
                  <div className="np-count">
                    {t("{n} of {total} signals match", { n: filteredSigs.length, total: ownSigs.length })}
                  </div>
                )}
                {shownSigs.map((q, i) => (
                  <SigRow q={q} company={node.id} key={q.quarter + "|" + i} />
                ))}
                {filteredSigs.length === 0 && <div className="np-empty">{t("No signals match this filter.")}</div>}
                {(hiddenSigs > 0 || sigLimit > SIG_PAGE) && (
                  <div className="np-more">
                    {hiddenSigs > 0 && (
                      <button className="btn np-btn-sm" onClick={() => setSigLimit((l) => l + SIG_STEP)}>
                        {t("Show {n} more ({hidden} hidden)", { n: Math.min(hiddenSigs, SIG_STEP), hidden: hiddenSigs })}
                      </button>
                    )}
                    {hiddenSigs > SIG_STEP && (
                      <button className="btn np-btn-sm" onClick={() => setSigLimit(filteredSigs.length)}>
                        {t("Show all ({n})", { n: filteredSigs.length })}
                      </button>
                    )}
                    {sigLimit > SIG_PAGE && (
                      <button className="btn np-btn-sm" onClick={() => setSigLimit(SIG_PAGE)}>
                        {t("Show less")}
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
                <div className="pcol-head">{t("Customers")} →</div>
                {preview("customers", customers).map((g) => (
                  <EdgeGroupCard g={g} key={g.company} onNavigate={onNavigate} company={node.id} target={g.company} viewer={node.id} />
                ))}
                <ShowAllToggle total={customers.length} open={isOpen("customers")} onToggle={() => toggleOpen("customers")} />
              </>
            )}
            {(dealSuppliers.length > 0 || plainAll.length > 0) && (
              <>
                <div className="pcol-head" style={{ marginTop: customers.length ? "1rem" : 0 }}>
                  ← {t("Suppliers")}
                </div>
                {preview("suppliers", dealSuppliers).map((g) => (
                  <EdgeGroupCard g={g} key={g.company} onNavigate={onNavigate} company={g.company} target={node.id} viewer={node.id} />
                ))}
                <ShowAllToggle total={dealSuppliers.length} open={isOpen("suppliers")} onToggle={() => toggleOpen("suppliers")} />
                {plainAll.length > 0 && (
                  <div className="deal-plain">
                    {plainSuppliers.map((s, i) => (
                      <span key={s.company}>
                        <span className="deal-link" onClick={() => onNavigate(s.company)}>
                          {name(s.company)}
                        </span>
                        {i < plainSuppliers.length - 1 ? ", " : ""}
                      </span>
                    ))}
                    {plainAll.length > PLAIN_SUPPLIERS && (
                      <>
                        {" "}
                        <button className="np-linkbtn" onClick={() => setAllPlain((s) => !s)}>
                          {allPlain ? t("show fewer") : t("+{n} more", { n: plainAll.length - PLAIN_SUPPLIERS })}
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
              {t("Customers & suppliers on file")}{" "}
              <span className="np-of-hint">
                — {t("named in this company's filings / calls, not graph nodes")}
              </span>
            </div>
            <div className="pgrid" style={{ marginTop: 0 }}>
              <div className="pcol">
                <div className="np-of-sub">{t("Customers")} ({onFile.customers.length})</div>
                {onFile.customers.length === 0 && <div className="np-empty">{t("none on file")}</div>}
                {preview("onfile-c", onFile.customers).map((g) => (
                  <OnFileRow g={g} key={g.name} company={node.id} />
                ))}
                <ShowAllToggle total={onFile.customers.length} open={isOpen("onfile-c")} onToggle={() => toggleOpen("onfile-c")} />
              </div>
              <div className="pcol">
                <div className="np-of-sub">{t("Suppliers")} ({onFile.suppliers.length})</div>
                {onFile.suppliers.length === 0 && <div className="np-empty">{t("none on file")}</div>}
                {preview("onfile-s", onFile.suppliers).map((g) => (
                  <OnFileRow g={g} key={g.name} company={node.id} />
                ))}
                <ShowAllToggle total={onFile.suppliers.length} open={isOpen("onfile-s")} onToggle={() => toggleOpen("onfile-s")} />
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
    </ExpandAllContext.Provider>
  );
}
