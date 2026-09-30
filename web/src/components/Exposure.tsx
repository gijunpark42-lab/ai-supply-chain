"use client";

// Exposure.tsx — the "who benefits" tab.
//
// Pick a chain (or a generation transition) and see its members ranked by an
// explainable exposure score that derive.py computes once per build and writes to
// graph/exposure.json (served as /data/exposure.json). Everything on screen is read
// from that file plus the VizNodes the page already holds; the browser never
// recomputes the score, it only sorts, filters and explains it.
//
// Score (see derive.py, section 4):
//   role weight (3 chip-level / 2 one step removed or buyer / 1 far away)
//   + 0.5 × min(contracts on the company's edges in this chain, 10)
//   + 0.5 × min(edges in this chain, 8)
//   + freshness (+2 newest source ≤ 90 days, +1 ≤ 180 days)

import { useEffect, useMemo, useState } from "react";
import type { VizNode } from "@/lib/types";
import {
  CHAIN_COLORS,
  GROUP_COLORS,
  GROUP_NAMES,
  LAYER_ORDER,
  DOMAIN_ORDER,
  chainColor,
  groupName,
  slugLabel,
} from "@/lib/taxonomy";
import {
  TRANSITIONS,
  computeTransition,
  nodeExposure,
  type Transition,
  type GenStatus,
} from "@/lib/transitions";
import {
  loadExposure,
  tradingViewSymbol,
  daysSince,
  freshnessOf,
  scoreBreakdown,
  csvLine,
  labelDate,
  type ExposureData,
  type ExposureCompany,
  type ExposureSlot,
  type ConcentrationFact,
} from "@/lib/exposure";
import CellText from "./CellText";
import { t, tr, trJoined, name, useLang } from "@/lib/i18n";
import "./Exposure.css";

interface Props {
  nodes: VizNode[];
  byId: Map<string, VizNode>;
  onOpen: (id: string) => void; // opens the NodePanel for a company id
}

// ── Selection ─────────────────────────────────────────────────────────────
// The selector value is a short string so it can live in a <select>:
//   "c:<chain slug>" = one chain      "t:<transition key>" = one generation transition
type Selection =
  | { kind: "chain"; value: string; chain: string; chains: string[] }
  | { kind: "transition"; value: string; t: Transition; chains: string[] };

function parseSelection(value: string): Selection {
  if (value.startsWith("t:")) {
    const t = TRANSITIONS.find((x) => x.key === value.slice(2)) ?? TRANSITIONS[0];
    return { kind: "transition", value: `t:${t.key}`, t, chains: [...t.from, ...t.to] };
  }
  const chain = value.slice(2);
  return { kind: "chain", value, chain, chains: [chain] };
}

// chains/ sub-folder → <optgroup> label.
const CHAIN_GROUP_LABEL: Record<string, string> = {
  accelerators: "Accelerator generations",
  components: "Components",
  manufacturing: "Manufacturing",
};

const STATUS_META: Record<GenStatus, { icon: string; word: string }> = {
  gained: { icon: "📈", word: "new in next gen" },
  retained: { icon: "✅", word: "retained" },
  lost: { icon: "⚠️", word: "not in next gen" },
};

// ── Rows ──────────────────────────────────────────────────────────────────
interface Row {
  id: string;
  c: ExposureCompany;
  chain: string; // the chain every number in this row comes from
  status: GenStatus | null; // transition mode only
  product: string;
  sector: string;
  group: string; // layer / domain slug of the role in that chain
  score: number | null; // null = not in the next-gen chain ("lost" in transition mode)
  roleWeight: number;
  edges: number;
  contracts: number;
  counterparties: number;
  latest: string | null;
  days: number | null;
  ticker: string | null;
  exchange: string | null;
  tv: string | null; // TradingView symbol, when the exchange maps
  signal: string; // newest screener-slot text
  signalLabel: string; // and the source label it came from
  rank: number; // position in score order — fixed, whatever column is sorted
}

// The chain (among `candidates`) where the company scores highest. Transition mode
// needs this because a successor can be two chains (TPU v8t + v8i).
function bestChain(c: ExposureCompany, candidates: string[]): string | null {
  let best: string | null = null;
  for (const ch of candidates) {
    if (!(ch in c.score_by_chain)) continue;
    if (best === null || c.score_by_chain[ch] > c.score_by_chain[best]) best = ch;
  }
  return best;
}

// The most recently dated screener slot a company has (guidance, supply status, …).
function newestSlot(c: ExposureCompany): { text: string; label: string } {
  let bestDate = "";
  let text = "";
  let label = "";
  for (const [slot, src] of Object.entries(c.slot_sources)) {
    const value = c.slots[slot as ExposureSlot];
    const d = labelDate(src);
    if (value && d > bestDate) {
      bestDate = d;
      text = value;
      label = src || "";
    }
  }
  return { text, label };
}

const uniq = (xs: (string | null | undefined)[]) =>
  Array.from(new Set(xs.filter((x): x is string => !!x)));

function buildRows(data: ExposureData, sel: Selection, now: Date): Row[] {
  // Members of every chain in the selection, each company once.
  const ids: string[] = [];
  const seen = new Set<string>();
  for (const ch of sel.chains) {
    for (const id of data.chains[ch]?.members ?? []) {
      if (!seen.has(id)) {
        seen.add(id);
        ids.push(id);
      }
    }
  }

  const rows: Row[] = [];
  for (const id of ids) {
    const c = data.companies[id];
    if (!c) continue;
    let status: GenStatus | null = null;
    let chain: string | null = sel.kind === "chain" ? sel.chain : null;
    if (sel.kind === "transition") {
      status = c.generations[sel.t.key] ?? null;
      // Numbers come from the next-gen chain when the company is in it; a company
      // that dropped out only has its prior-gen chain to show.
      chain = bestChain(c, sel.t.to) ?? bestChain(c, sel.t.from);
    }
    if (!chain) continue;
    const roles = c.roles.filter((r) => r.chain === chain);
    const stats = c.chain_stats[chain] ?? { role_weight: 0, edges: 0, contracts: 0, counterparties: 0 };
    const slot = newestSlot(c);
    rows.push({
      id,
      c,
      chain,
      status,
      product: uniq(roles.map((r) => r.product)).join(" · "),
      sector: uniq(roles.map((r) => r.sector)).join(" · "),
      group: roles[0]?.layer ?? roles[0]?.domain ?? c.primary ?? "unknown",
      score: status === "lost" ? null : c.score_by_chain[chain] ?? null,
      roleWeight: stats.role_weight,
      edges: stats.edges,
      contracts: stats.contracts,
      counterparties: stats.counterparties,
      latest: c.latest,
      days: daysSince(c.latest, now),
      ticker: c.ticker,
      exchange: c.exchange,
      tv: tradingViewSymbol(c.ticker, c.exchange),
      signal: slot.text,
      signalLabel: slot.label,
      rank: 0,
    });
  }

  // Rank = position in score order (best first); ties broken by name so it is stable.
  const byScore = [...rows].sort(
    (a, b) => (b.score ?? -1) - (a.score ?? -1) || a.id.localeCompare(b.id)
  );
  byScore.forEach((r, i) => (r.rank = i + 1));
  return rows;
}

// ── Sorting ───────────────────────────────────────────────────────────────
type SortKey =
  | "rank"
  | "company"
  | "status"
  | "product"
  | "group"
  | "score"
  | "contracts"
  | "counterparties"
  | "latest"
  | "ticker";

const STATUS_ORDER: Record<GenStatus, number> = { gained: 0, retained: 1, lost: 2 };
const groupOrd = (s: string) => (s in LAYER_ORDER ? LAYER_ORDER[s] : 100 + (DOMAIN_ORDER[s] ?? 50));
// Columns that read best biggest-first on the first click.
const DESC_FIRST: SortKey[] = ["score", "contracts", "counterparties", "latest"];

function compareRows(a: Row, b: Row, key: SortKey): number {
  switch (key) {
    case "rank":
      return a.rank - b.rank;
    case "company":
      return a.id.localeCompare(b.id);
    case "status":
      return (a.status ? STATUS_ORDER[a.status] : 9) - (b.status ? STATUS_ORDER[b.status] : 9);
    case "product":
      return a.product.localeCompare(b.product);
    case "group":
      return groupOrd(a.group) - groupOrd(b.group);
    case "score":
      return (a.score ?? -1) - (b.score ?? -1);
    case "contracts":
      return a.contracts - b.contracts;
    case "counterparties":
      return a.counterparties - b.counterparties;
    case "latest":
      return (a.latest ?? "").localeCompare(b.latest ?? "");
    case "ticker":
      // "￿" sorts after every real ticker, so private companies land at the end.
      return (a.ticker ?? "￿").localeCompare(b.ticker ?? "￿");
  }
}

interface Col {
  key: SortKey | "pick" | "signal";
  label: string;
  w?: string; // no width = takes whatever is left (table-layout: fixed)
  num?: boolean;
  sortable: boolean;
}
const COLS: Col[] = [
  { key: "pick", label: "Basket", w: "3.5%", sortable: false },
  { key: "rank", label: "#", w: "3.5%", num: true, sortable: true },
  { key: "company", label: "Company", w: "13%", sortable: true },
  { key: "status", label: "Gen", w: "9%", sortable: true }, // dropped when no transition applies
  { key: "product", label: "Role in chain", w: "13.5%", sortable: true },
  { key: "group", label: "Layer", w: "10%", sortable: true },
  { key: "score", label: "Score", w: "8%", num: true, sortable: true },
  { key: "contracts", label: "Contracts", w: "6%", num: true, sortable: true },
  { key: "counterparties", label: "Partners", w: "6%", num: true, sortable: true },
  { key: "latest", label: "Latest", w: "8.5%", sortable: true },
  { key: "ticker", label: "Ticker", w: "8%", sortable: true },
  { key: "signal", label: "Latest signal", sortable: false },
];

// ── Component ─────────────────────────────────────────────────────────────
export default function Exposure({ nodes, byId, onOpen }: Props) {
  // exposure.json text (roles, formula, concentration facts) + the screener-slot
  // text shown as "Latest signal" (it lives in the metrics / graph overlays).
  const { rev } = useLang(["exposure", "metrics"]);
  // undefined = still loading, null = missing (404) or unreadable.
  const [data, setData] = useState<ExposureData | null | undefined>(undefined);
  const [selValue, setSelValue] = useState<string>(`t:${TRANSITIONS[0].key}`);
  const [q, setQ] = useState("");
  const [groups, setGroups] = useState<Set<string>>(new Set()); // empty = every layer
  const [sortKey, setSortKey] = useState<SortKey>("score");
  const [sortDir, setSortDir] = useState<1 | -1>(-1);
  const [basket, setBasket] = useState<Set<string>>(new Set());
  const [toast, setToast] = useState<string | null>(null);
  const [fallbackText, setFallbackText] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    loadExposure().then((d) => {
      if (alive) setData(d);
    });
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    if (!toast) return;
    const id = setTimeout(() => setToast(null), 3000);
    return () => clearTimeout(id);
  }, [toast]);

  const now = useMemo(() => new Date(), []);
  const sel = useMemo(() => parseSelection(selValue), [selValue]);

  // Chains for the selector, grouped by their chains/ sub-folder. Without the JSON
  // we still list every chain the taxonomy knows, so the selector never goes blank.
  const chainGroups = useMemo(() => {
    const out = new Map<string, string[]>();
    const slugs = data ? Object.keys(data.chains) : Object.keys(CHAIN_COLORS);
    for (const slug of slugs.sort()) {
      const g = data?.chains[slug]?.group || "other";
      if (!out.has(g)) out.set(g, []);
      out.get(g)!.push(slug);
    }
    return Array.from(out.entries()).sort(
      (a, b) => Object.keys(CHAIN_GROUP_LABEL).indexOf(a[0]) - Object.keys(CHAIN_GROUP_LABEL).indexOf(b[0])
    );
  }, [data]);

  // Generation delta (transition mode) — pure computation over the nodes.
  const delta = useMemo(
    () => (sel.kind === "transition" ? computeTransition(nodes, sel.t) : null),
    [nodes, sel]
  );

  // In chain mode a "Gen" chip appears when the chain belongs to a transition
  // (nvda_b200 → "retained / lost in Vera Rubin"; nvidia_vera_rubin → "new / retained").
  const genInfo = useMemo(() => {
    const m = new Map<string, { status: GenStatus; label: string }>();
    if (sel.kind === "transition") return m; // rows carry their own status
    const t = TRANSITIONS.find((x) => x.from.includes(sel.chain) || x.to.includes(sel.chain));
    if (!t) return m;
    for (const n of nodes) {
      const item = nodeExposure(n).find((x) => x.t.key === t.key);
      if (item) m.set(n.id, { status: item.status, label: t.label });
    }
    return m;
  }, [nodes, sel]);
  const showGen = sel.kind === "transition" || genInfo.size > 0;
  const genLabel = sel.kind === "transition" ? sel.t.label : Array.from(genInfo.values())[0]?.label ?? "";

  const allRows = useMemo(() => (data ? buildRows(data, sel, now) : []), [data, sel, now]);

  // Layer chips: every layer/domain present in the selection, in taxonomy order, with counts.
  const chipGroups = useMemo(() => {
    const counts = new Map<string, number>();
    for (const r of allRows) counts.set(r.group, (counts.get(r.group) ?? 0) + 1);
    return Array.from(counts.entries()).sort((a, b) => groupOrd(a[0]) - groupOrd(b[0]));
  }, [allRows]);

  const visible = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const rows = allRows.filter((r) => {
      if (groups.size && !groups.has(r.group)) return false;
      if (!needle) return true;
      // English text plus what is on screen (local names / translations).
      const hay = `${r.id} ${r.ticker ?? ""} ${r.product} ${r.sector} ${GROUP_NAMES[r.group] ?? r.group} ${name(r.id)} ${trJoined(r.product)} ${trJoined(r.sector)} ${groupName(r.group)}`.toLowerCase();
      return hay.includes(needle);
    });
    rows.sort((a, b) => sortDir * compareRows(a, b, sortKey) || a.rank - b.rank);
    return rows;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [allRows, q, groups, sortKey, sortDir, rev]);

  // Concentration facts for every company in the selection, largest share first.
  const facts = useMemo(() => {
    if (!data) return [] as { id: string; f: ConcentrationFact }[];
    const needle = q.trim().toLowerCase();
    const out: { id: string; f: ConcentrationFact }[] = [];
    const seen = new Set<string>();
    for (const ch of sel.chains) {
      for (const id of data.chains[ch]?.members ?? []) {
        if (seen.has(id)) continue;
        seen.add(id);
        for (const f of data.companies[id]?.concentration ?? []) {
          if (needle && !`${id} ${f.counterparty}`.toLowerCase().includes(needle)) continue;
          out.push({ id, f });
        }
      }
    }
    out.sort(
      (a, b) =>
        Number(a.f.pct === null) - Number(b.f.pct === null) ||
        (b.f.pct ?? 0) - (a.f.pct ?? 0) ||
        a.id.localeCompare(b.id)
    );
    return out;
  }, [data, sel, q]);

  // The bar in the Score cell runs 0..maxScore — the highest score the formula can give.
  const maxScore = useMemo(() => {
    if (!data) return 14;
    const w = data.weights;
    return (
      Math.max(...Object.values(w.role)) +
      w.contract_step * w.contract_cap +
      w.edge_step * w.edge_cap +
      w.fresh_bonus
    );
  }, [data]);

  // ── handlers ──
  const onSort = (k: SortKey) => {
    if (k === sortKey) setSortDir((d) => (d === 1 ? -1 : 1));
    else {
      setSortKey(k);
      setSortDir(DESC_FIRST.includes(k) ? -1 : 1);
    }
  };
  const toggleGroup = (g: string) => {
    const next = new Set(groups);
    next.has(g) ? next.delete(g) : next.add(g);
    setGroups(next);
  };
  const togglePick = (id: string) => {
    const next = new Set(basket);
    next.has(id) ? next.delete(id) : next.add(id);
    setBasket(next);
  };
  const allVisiblePicked = visible.length > 0 && visible.every((r) => basket.has(r.id));
  const toggleAllVisible = () => {
    const next = new Set(basket);
    if (allVisiblePicked) visible.forEach((r) => next.delete(r.id));
    else visible.forEach((r) => next.add(r.id));
    setBasket(next);
  };

  // Clipboard can be blocked (http, iframe, permissions) — then show the text in a
  // box the user can copy from by hand instead of failing silently.
  const copyText = async (text: string, what: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setFallbackText(null);
      setToast(t("Copied {what}", { what }));
    } catch {
      setFallbackText(text);
      setToast(t("Clipboard blocked — copy from the box below"));
    }
  };
  const basketCompanies = () =>
    Array.from(basket)
      .map((id) => data?.companies[id])
      .filter((c): c is ExposureCompany => !!c);
  const copyTickers = () => {
    const picked = basketCompanies();
    const tickers = picked.map((c) => c.ticker).filter((t): t is string => !!t);
    const skipped = picked.length - tickers.length;
    copyText(tickers.join(", "), t("{n} tickers", { n: tickers.length }) + (skipped ? " " + t("({n} without a ticker skipped)", { n: skipped }) : ""));
  };
  const copyTradingView = () => {
    const picked = basketCompanies();
    const syms = picked.map((c) => tradingViewSymbol(c.ticker, c.exchange)).filter((s): s is string => !!s);
    const skipped = picked.length - syms.length;
    copyText(syms.join("\n"), t("{n} TradingView symbols", { n: syms.length }) + (skipped ? " " + t("({n} unmapped skipped)", { n: skipped }) : ""));
  };

  // CSV = the visible rows, narrowed to the basket when it holds any of them.
  const exportRows = basket.size ? visible.filter((r) => basket.has(r.id)) : visible;
  const downloadCsv = () => {
    const header = [
      "rank", "company", "ticker", "exchange", "tradingview", "country", "status", "generation",
      "layer", "sector", "product", "chain", "score", "role_weight", "edges", "contracts",
      "partners", "latest", "days_since", "latest_signal", "signal_source",
    ];
    const lines = [
      csvLine(header),
      ...exportRows.map((r) =>
        csvLine([
          r.rank, r.id, r.ticker, r.exchange, r.tv, r.c.country, r.c.status, r.status,
          GROUP_NAMES[r.group] ?? r.group, r.sector, r.product, r.chain, r.score, r.roleWeight,
          r.edges, r.contracts, r.counterparties, r.latest, r.days, r.signal, r.signalLabel,
        ])
      ),
    ];
    // The BOM makes Excel read the file as UTF-8 (the text carries "→" and "·").
    const blob = new Blob(["﻿" + lines.join("\r\n")], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `exposure_${sel.value.slice(2)}.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  const cols = showGen ? COLS : COLS.filter((c) => c.key !== "status");
  const chainBlock = sel.kind === "chain" && data ? data.chains[sel.chain] : null;

  return (
    <div className="xp">
      <h3>🎯 {t("Exposure — who benefits")}</h3>
      <p className="caption">
        {t("Pick a chain or a generation transition: its members ranked by how exposed they are — what they make in that chain, how many deals and edges tie them in, and how fresh the evidence is. Click a company for its panel; tick rows to build a basket you can copy into a watchlist.")}
      </p>

      {/* ── selector + text filter ── */}
      <div className="xp-toolbar">
        <div className="xp-field">
          <label className="field-label" htmlFor="xp-sel">
            {t("Chain / transition")}
          </label>
          <select
            id="xp-sel"
            value={sel.value}
            onChange={(e) => {
              setSelValue(e.target.value);
              setGroups(new Set()); // layer chips differ per chain
            }}
          >
            <optgroup label={t("Generation transitions")}>
              {TRANSITIONS.map((tn) => (
                <option key={tn.key} value={`t:${tn.key}`}>
                  {name(tn.vendor)}: {t(tn.label)}
                </option>
              ))}
            </optgroup>
            {chainGroups.map(([g, slugs]) => (
              <optgroup key={g} label={t(CHAIN_GROUP_LABEL[g] ?? "Chains")}>
                {slugs.map((s) => (
                  <option key={s} value={`c:${s}`}>
                    {slugLabel(s)}
                    {data?.chains[s]?.anchor ? ` — ${name(data.chains[s].anchor!)}` : ""}
                  </option>
                ))}
              </optgroup>
            ))}
          </select>
        </div>
        <div className="xp-field">
          <label className="field-label" htmlFor="xp-q">
            {t("Filter")}
          </label>
          <input
            id="xp-q"
            type="search"
            placeholder={t("Company, ticker, product, sector…")}
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
        </div>
      </div>

      {/* ── summary strip ── */}
      <div className="xp-summary">
        {sel.kind === "chain" ? (
          <>
            <span className="xp-dot" style={{ background: chainColor(sel.chain) }} />
            <b>{slugLabel(sel.chain)}</b>
            {chainBlock && (
              <>
                <span>{t("{n} companies", { n: chainBlock.members.length })}</span>
                <span>{t("{n} edges", { n: chainBlock.edges })}</span>
                <span>{t("{n} contracts", { n: chainBlock.contracts })}</span>
                {chainBlock.anchor && (
                  <span>
                    {t("about")}{" "}
                    <button type="button" className="co-link" onClick={() => onOpen(chainBlock.anchor!)}>
                      {name(chainBlock.anchor)}
                    </button>
                  </span>
                )}
              </>
            )}
          </>
        ) : (
          <>
            <b>{t(sel.t.label)}</b>
            {delta && (
              <span className="xp-gen-counts">
                <em style={{ color: "#4aa9ff" }}>📈 {t("{n} new", { n: delta.counts.gained })}</em>
                <em style={{ color: "#3fb950" }}>✅ {t("{n} retained", { n: delta.counts.retained })}</em>
                <em style={{ color: "#d29922" }}>⚠️ {t("{n} not in next gen", { n: delta.counts.lost })}</em>
              </span>
            )}
            <span>
              {sel.t.from.map(slugLabel).join(" + ")} → {sel.t.to.map(slugLabel).join(" + ")}
            </span>
          </>
        )}
        {data && <span>{t("data {date}", { date: data.generated })}</span>}
        {data && (
          <details className="xp-formula">
            <summary>{t("How is the score computed?")}</summary>
            <p>{tr(data.formula)}</p>
          </details>
        )}
      </div>

      {/* ── missing / loading ── */}
      {data === undefined && <div className="spinner">{t("Loading exposure…")}</div>}
      {data === null && (
        <div className="xp-notice">
          {t("Exposure data has not been generated yet (/data/exposure.json is missing). Run python graph_build.py --sync in the repo root — derive.py writes graph/exposure.json and the sync copies it here. The generation delta below still works because it is computed from the graph itself.")}
        </div>
      )}

      {/* ── layer chips + basket bar + ranked table ── */}
      {data && (
        <>
          <div className="xp-chips" role="group" aria-label={t("Filter by layer")}>
            <button
              type="button"
              className={"xp-chip" + (groups.size === 0 ? " on" : "")}
              onClick={() => setGroups(new Set())}
            >
              {t("All")} <span className="xp-n">{allRows.length}</span>
            </button>
            {chipGroups.map(([g, n]) => (
              <button
                key={g}
                type="button"
                className={"xp-chip" + (groups.has(g) ? " on" : "")}
                style={{ ["--xp-chip-color" as string]: GROUP_COLORS[g] || "#94a3b8" }}
                onClick={() => toggleGroup(g)}
                aria-pressed={groups.has(g)}
              >
                <span className="xp-dot" style={{ background: GROUP_COLORS[g] || "#94a3b8" }} />
                {groupName(g)} <span className="xp-n">{n}</span>
              </button>
            ))}
          </div>

          <div className="xp-basket">
            <span>
              <span className="xp-count">{basket.size}</span> {t("in basket")}
            </span>
            <button type="button" className="btn xp-btn" disabled={!basket.size} onClick={copyTickers}>
              {t("Copy tickers")}
            </button>
            <button type="button" className="btn xp-btn" disabled={!basket.size} onClick={copyTradingView}>
              {t("Copy TradingView list")}
            </button>
            <button
              type="button"
              className="btn xp-btn"
              disabled={!exportRows.length}
              onClick={downloadCsv}
              title={t("Visible rows — only the ticked ones when the basket holds any of them")}
            >
              {t(basket.size ? "Download CSV ({n} selected)" : "Download CSV ({n} visible)", { n: exportRows.length })}
            </button>
            {basket.size > 0 && (
              <button type="button" className="xp-link-btn" onClick={() => setBasket(new Set())}>
                {t("Clear basket")}
              </button>
            )}
            {toast && <span className="xp-toast">{toast}</span>}
          </div>
          {fallbackText && (
            <textarea
              className="xp-fallback"
              readOnly
              value={fallbackText}
              aria-label={t("Text to copy")}
              onFocus={(e) => e.currentTarget.select()}
            />
          )}

          <div className="tbl-wrap">
            <table className="data xp-table">
              <colgroup>
                {cols.map((c) => (
                  <col key={c.key} style={c.w ? { width: c.w } : undefined} />
                ))}
              </colgroup>
              <thead>
                <tr>
                  {cols.map((c) =>
                    c.key === "pick" ? (
                      <th key={c.key} className="xp-pick xp-static">
                        <input
                          type="checkbox"
                          aria-label={t("Select all visible rows")}
                          checked={allVisiblePicked}
                          onChange={toggleAllVisible}
                        />
                      </th>
                    ) : c.sortable ? (
                      <th
                        key={c.key}
                        className={(sortKey === c.key ? "active" : "") + (c.num ? " xp-num" : "")}
                        aria-sort={sortKey === c.key ? (sortDir === 1 ? "ascending" : "descending") : "none"}
                        onClick={() => onSort(c.key as SortKey)}
                      >
                        <span className="th-label">{t(c.label)}</span>
                        <span className="sort-arrow">{sortKey === c.key ? (sortDir === 1 ? "▲" : "▼") : "↕"}</span>
                      </th>
                    ) : (
                      <th key={c.key} className="xp-static">
                        <span className="th-label">{t(c.label)}</span>
                      </th>
                    )
                  )}
                </tr>
              </thead>
              <tbody>
                {visible.map((r) => {
                  const gen =
                    sel.kind === "transition"
                      ? r.status
                        ? { status: r.status, label: sel.t.label }
                        : null
                      : genInfo.get(r.id) ?? null;
                  const picked = basket.has(r.id);
                  return (
                    <tr
                      key={r.id}
                      className={(r.status === "lost" ? "xp-lost " : "") + (picked ? "xp-picked" : "")}
                    >
                      <td data-label={t("Basket")} className="xp-pick">
                        <input
                          type="checkbox"
                          aria-label={t("Add {name} to basket", { name: name(r.id) })}
                          checked={picked}
                          onChange={() => togglePick(r.id)}
                        />
                      </td>
                      <td data-label="#" className="xp-num">
                        {r.rank}
                      </td>
                      <td data-label={t("Company")} className="xp-co">
                        <div className="cell" title={t("Open {name}", { name: name(r.id) })}>
                          <button type="button" className="co-link" onClick={() => onOpen(r.id)}>
                            {name(r.id)}
                          </button>
                          {r.sector && <span className="xp-sub">{trJoined(r.sector)}</span>}
                        </div>
                      </td>
                      {showGen && (
                        <td data-label={t("Gen")}>
                          {gen ? (
                            <span
                              className={"xp-gen " + gen.status}
                              title={`${t(gen.label)}: ${t(STATUS_META[gen.status].word)}`}
                            >
                              {STATUS_META[gen.status].icon} {t(gen.status)}
                            </span>
                          ) : (
                            <span className="muted">—</span>
                          )}
                        </td>
                      )}
                      <td data-label={t("Role in chain")}>
                        <CellText text={trJoined(r.product) || "—"} label={t("Role in chain")} subject={name(r.id)} />
                      </td>
                      <td data-label={t("Layer")}>
                        <span className="xp-layer" title={groupName(r.group)}>
                          <span className="xp-dot" style={{ background: GROUP_COLORS[r.group] || "#94a3b8" }} />
                          <span>{groupName(r.group)}</span>
                        </span>
                      </td>
                      <td data-label={t("Score")} className="xp-num">
                        {r.score === null ? (
                          <span className="muted" title={t("Not in the next-generation chain")}>
                            —
                          </span>
                        ) : (
                          <span className="xp-score" title={scoreBreakdown(r.c, r.chain, data.weights)}>
                            {r.score.toFixed(1)}
                            <span className="xp-bar">
                              <i style={{ width: `${Math.min(100, (r.score / maxScore) * 100)}%` }} />
                            </span>
                          </span>
                        )}
                      </td>
                      <td data-label={t("Contracts")} className="xp-num" title={t("{n} edges in {chain}", { n: r.edges, chain: slugLabel(r.chain) })}>
                        {r.contracts}
                      </td>
                      <td data-label={t("Partners")} className="xp-num" title={t("Distinct counterparties in this chain")}>
                        {r.counterparties}
                      </td>
                      <td data-label={t("Latest")} title={r.days === null ? t("No dated source yet") : t("{n} days ago", { n: r.days })}>
                        <span className={"xp-fresh " + freshnessOf(r.days, data.weights)} />
                        {r.latest ?? "—"}
                      </td>
                      <td data-label={t("Ticker")}>
                        {r.ticker ? (
                          <>
                            <span className="xp-ticker" title={r.tv ?? t("No TradingView mapping for this exchange")}>
                              {r.ticker}
                            </span>
                            <span className="xp-exch">{r.exchange}</span>
                          </>
                        ) : (
                          <span className="muted" title={r.c.status ? t(r.c.status) : undefined}>
                            {r.c.status === "public" ? "—" : r.c.status ? t(r.c.status) : "—"}
                          </span>
                        )}
                      </td>
                      <td data-label={t("Latest signal")}>
                        <CellText
                          text={tr(r.signal) || "—"}
                          label={t("Latest signal")}
                          subject={name(r.id)}
                          detail={r.signal ? { source: r.signalLabel, signal: tr(r.signal) } : undefined}
                        />
                      </td>
                    </tr>
                  );
                })}
                {visible.length === 0 && (
                  <tr>
                    <td colSpan={cols.length} className="xp-empty">
                      {t("No companies match.")}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          <div className="xp-legend">
            <span>
              {t("{n} of {total} companies · score max {max} — hover a score for its breakdown", { n: visible.length, total: allRows.length, max: maxScore.toFixed(0) })}
            </span>
            <span>
              <span className="xp-fresh fresh" /> ≤ {t("{n}d", { n: data.weights.fresh_days })}
              <span className="xp-fresh aging" style={{ marginLeft: 10 }} /> ≤ {t("{n}d", { n: data.weights.aging_days })}
              <span className="xp-fresh stale" style={{ marginLeft: 10 }} /> {t("older")}
            </span>
            {showGen && <span>{t("Gen = status in {label}", { label: t(genLabel) })}</span>}
          </div>
        </>
      )}

      {/* ── generation delta (transition mode) ── */}
      {delta && (
        <div className="xp-section">
          <h4>🔀 {t("Generation delta")} — {t(delta.t.label)}</h4>
          <p className="caption">
            {t("Who wins a socket, who is not in the next-gen chain, and whose content changes. Computed from the curated chains; click a company for details.")}
          </p>
          <div className="xp-delta">
            <DeltaColumn
              cls="gained"
              title={`📈 ${t("New in next gen")} (${delta.counts.gained})`}
              note={t("won a socket it did not have in the current generation")}
              rows={delta.rows
                .filter((r) => r.status === "gained")
                .map((r) => ({ id: r.id, primary: r.primary, text: r.productTo ?? "" }))}
              onOpen={onOpen}
            />
            <DeltaColumn
              cls="lost"
              title={`⚠️ ${t("Not in next gen")} (${delta.counts.lost})`}
              note={t("lost the socket — or not yet added to the new chain")}
              rows={delta.rows
                .filter((r) => r.status === "lost")
                .map((r) => ({ id: r.id, primary: r.primary, text: r.productFrom ?? "" }))}
              onOpen={onOpen}
            />
            <DeltaColumn
              cls="changed"
              title={`🔁 ${t("Retained, content changed")} (${
                delta.rows.filter((r) => r.status === "retained" && r.productFrom !== r.productTo).length
              })`}
              note={t("retained in both generations with a different product — the content delta ({n} retained in total)", { n: delta.counts.retained })}
              rows={delta.rows
                .filter((r) => r.status === "retained" && r.productFrom !== r.productTo)
                .map((r) => ({ id: r.id, primary: r.primary, from: r.productFrom ?? "", text: r.productTo ?? "" }))}
              onOpen={onOpen}
            />
          </div>
        </div>
      )}

      {/* ── concentration ── */}
      {data && (
        <div className="xp-section">
          <h4>🧭 {t("Customer / supplier concentration")}</h4>
          <p className="caption">
            {t("Facts the companies filed themselves (major-customer tables, raw-material suppliers, supply contracts as a share of revenue) for the members of this selection. The share is the first percentage in the text — it can be an aggregate, so read the detail.")}
          </p>
          {facts.length === 0 ? (
            <div className="xp-empty">{t("No concentration facts filed for these companies yet.")}</div>
          ) : (
            <div className="tbl-wrap">
              <table className="data xp-table">
                <colgroup>
                  <col style={{ width: "15%" }} />
                  <col style={{ width: "15%" }} />
                  <col style={{ width: "8%" }} />
                  <col style={{ width: "7%" }} />
                  <col />
                  <col style={{ width: "17%" }} />
                </colgroup>
                <thead>
                  <tr>
                    <th className="xp-static">{t("Company")}</th>
                    <th className="xp-static">{t("Counterparty")}</th>
                    <th className="xp-static">{t("Role")}</th>
                    <th className="xp-static xp-num">{t("Share")}</th>
                    <th className="xp-static">{t("Detail")}</th>
                    <th className="xp-static">{t("Source")}</th>
                  </tr>
                </thead>
                <tbody>
                  {facts.map(({ id, f }, i) => (
                    <tr key={`${id}|${f.counterparty}|${f.label}|${i}`}>
                      <td data-label={t("Company")} className="xp-co">
                        <div className="cell">
                          <button type="button" className="co-link" onClick={() => onOpen(id)}>
                            {name(id)}
                          </button>
                        </div>
                      </td>
                      <td data-label={t("Counterparty")}>
                        <div className="cell">
                          {byId.has(f.counterparty) ? (
                            <button type="button" className="co-link" onClick={() => onOpen(f.counterparty)}>
                              {name(f.counterparty)}
                            </button>
                          ) : (
                            f.counterparty
                          )}
                        </div>
                      </td>
                      <td data-label={t("Role")}>
                        <span className={"xp-role " + f.role}>{t(f.role)}</span>
                      </td>
                      <td data-label={t("Share")} className="xp-num">
                        {f.pct === null ? <span className="muted">—</span> : <span className="xp-pct">{f.pct}%</span>}
                      </td>
                      <td data-label={t("Detail")}>
                        <CellText text={tr(f.text)} label={t("Detail")} subject={name(id)} detail={{ source: f.label }} />
                      </td>
                      <td data-label={t("Source")}>
                        <span className="xp-src">{f.label}</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// One column of the generation-delta view: a clickable list of companies.
function DeltaColumn({
  cls,
  title,
  note,
  rows,
  onOpen,
}: {
  cls: "gained" | "lost" | "changed";
  title: string;
  note: string;
  rows: { id: string; primary: string; text: string; from?: string }[];
  onOpen: (id: string) => void;
}) {
  return (
    <div className={"xp-delta-col " + cls}>
      <div className="xp-delta-head">{title}</div>
      <div className="xp-delta-note">{note}</div>
      {rows.map((r) => (
        <button key={r.id} type="button" className="xp-delta-row" onClick={() => onOpen(r.id)}>
          <span className="xp-dot" style={{ background: GROUP_COLORS[r.primary] || "#94a3b8" }} />
          <span>
            <div className="xp-delta-name">{name(r.id)}</div>
            <div className="xp-delta-prod">
              {r.from !== undefined ? (
                <>
                  {trJoined(r.from)} <span className="xp-arrow">→</span> {trJoined(r.text)}
                </>
              ) : (
                trJoined(r.text)
              )}
            </div>
          </span>
        </button>
      ))}
      {rows.length === 0 && <div className="xp-empty">{t("none")}</div>}
    </div>
  );
}
