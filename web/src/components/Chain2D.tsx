"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { fetchJson } from "@/lib/data";
import { slugLabel } from "@/lib/taxonomy";
import type { MergedGraph } from "@/lib/types";
import {
  buildFromChain, buildFromMerged, renderChain2D,
  type C2DData, type C2DHandle,
} from "@/lib/chain2d";
import { useLang } from "@/lib/i18n";
import "./Graph.css";
import "./SignalText.css"; // source-type badges inside the edge popup (lib/chain2d.ts)

interface ChainIndexEntry {
  id: string;
  company: string;
  chain_focus: string;
}

const ALL = "__ALL__";
// localStorage key that remembers the last chain the user looked at.
const STORAGE_KEY = "aisc.chain2d";

// Built models, keyed by chain id. Module-level so they survive tab switches
// (this component unmounts when you leave the tab) — coming back is instant and
// costs no fetch. A page reload clears it, which is also when new data arrives.
const modelCache = new Map<string, C2DData>();

// localStorage can be missing (server render) or throw (private mode, blocked
// storage), so every access is wrapped and falls back to "All chains".
function readStoredChain(): string {
  try {
    if (typeof window === "undefined") return ALL;
    return window.localStorage.getItem(STORAGE_KEY) || ALL;
  } catch {
    return ALL;
  }
}
function storeChain(id: string): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, id);
  } catch {
    // storage unavailable — remembering the chain is a convenience, not a need
  }
}

export default function Chain2D({ glass }: { glass: boolean }) {
  // The chain files carry the "graph" overlay's text (products, sectors, deals).
  const { t, tr, name, rev } = useLang(["graph"]);
  const [index, setIndex] = useState<ChainIndexEntry[]>([]);
  const [sel, setSel] = useState<string>(readStoredChain);
  const [data, setData] = useState<C2DData | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  // Column slugs currently drawn as a single collapsed bar.
  const [collapsed, setCollapsed] = useState<Set<string>>(() => new Set());

  const wrapRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const tipRef = useRef<HTMLDivElement>(null);
  const epanelRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(1000);
  // The renderer's handle (pin / escape) and the pinned node key, kept in refs
  // because neither should trigger a React re-render — the renderer toggles
  // classes on the existing SVG instead.
  const handleRef = useRef<C2DHandle | null>(null);
  const pinnedRef = useRef<string | null>(null);

  useEffect(() => {
    fetchJson<ChainIndexEntry[]>("/data/chains/index.json").then(setIndex).catch(() => {});
  }, []);

  // If the remembered chain no longer exists (renamed / removed), fall back to All.
  useEffect(() => {
    if (sel !== ALL && index.length && !index.some((c) => c.id === sel)) setSel(ALL);
  }, [index, sel]);

  // Remember the choice for next time.
  useEffect(() => {
    storeChain(sel);
  }, [sel]);

  // Load the selected chain (or the whole merged graph for "All").
  useEffect(() => {
    let alive = true;
    pinnedRef.current = null; // a pin is a node key inside ONE model
    setLoadErr(null);
    const cached = modelCache.get(sel);
    if (cached) {
      setData(cached);
      setLoading(false);
      return;
    }
    setLoading(true);
    setData(null);
    const p =
      sel === ALL
        ? fetchJson<MergedGraph>("/data/merged_graph.json").then(buildFromMerged)
        : fetchJson<any>(`/data/chains/${sel}.json`).then(buildFromChain);
    p.then((d) => {
      modelCache.set(sel, d);
      if (alive) {
        setData(d);
        setLoading(false);
      }
    }).catch((e) => {
      if (alive) {
        setLoading(false);
        setLoadErr(e?.message || String(e));
      }
    });
    return () => {
      alive = false;
    };
  }, [sel]);

  // Track container width so the SVG lays out to the available space.
  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setWidth(el.clientWidth));
    ro.observe(el);
    setWidth(el.clientWidth);
    return () => ro.disconnect();
  }, []);

  const onToggleCollapse = useCallback((slug: string) => {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(slug)) next.delete(slug);
      else next.add(slug);
      return next;
    });
  }, []);

  // (Re)draw the SVG whenever the data, width or collapsed set changes. Hover
  // and pin never come through here — the renderer handles them by toggling
  // CSS classes, and a surviving pin is restored via `pinned`.
  useEffect(() => {
    if (!data || !svgRef.current || !tipRef.current || !epanelRef.current) return;
    handleRef.current = renderChain2D(svgRef.current, tipRef.current, epanelRef.current, data, width, {
      collapsed,
      onToggleCollapse,
      pinned: pinnedRef.current,
      onPinChange: (k) => {
        pinnedRef.current = k;
      },
    });
    // `rev`: redraw in the new language (the SVG text is written by the renderer).
  }, [data, width, collapsed, onToggleCollapse, rev]);

  // Esc: close the edge panel first, then unpin.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (handleRef.current && handleRef.current.escape()) e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const cur = index.find((c) => c.id === sel);
  const counts = useMemo(() => {
    if (!data) return { c: 0, e: 0 };
    return { c: data.columns.reduce((s, col) => s + col.players.length, 0), e: data.edges.length };
  }, [data]);
  const hasExternal = useMemo(
    () => !!data && data.columns.some((c) => c.kind === "external"),
    [data]
  );
  const columnSlugs = useMemo(() => (data ? data.columns.map((c) => c.slug) : []), [data]);
  const nCollapsed = columnSlugs.filter((s) => collapsed.has(s)).length;

  const bg = glass ? "#262b35" : "#0b0e13";

  return (
    <div className={"c2d" + (glass ? " glass" : "")}>
      <div className="row" style={{ marginBottom: "0.9rem" }}>
        <div className="grow" style={{ maxWidth: 460 }}>
          <label className="field-label">{t("Chain")}</label>
          <select value={sel} onChange={(e) => setSel(e.target.value)}>
            <option value={ALL}>🌐 {t("All value chains (everything)")}</option>
            {index.map((c) => (
              <option key={c.id} value={c.id}>
                {slugLabel(c.id)}
              </option>
            ))}
          </select>
        </div>
        <div className="caption">
          {sel === ALL ? (
            <>
              <b style={{ color: "var(--ap-text)" }}>{t("All value chains")}</b> — {t("every company & edge, grouped by layer")}
            </>
          ) : cur ? (
            <>
              <b style={{ color: "var(--ap-text)" }}>{name(cur.company)}</b> — {tr(cur.chain_focus)}
            </>
          ) : null}
        </div>
      </div>

      {/* Always-visible legend for the map's visual language + interactions. */}
      <div className="c2d-legend" aria-label={t("Map legend")}>
        <span className="lg-item">
          <span className="lg-dot" />
          {t("earnings data")}
        </span>
        <span className="lg-item">
          <svg width="24" height="6" aria-hidden="true">
            <line x1="1" y1="3" x2="23" y2="3" stroke="#7dd3fc" strokeWidth="2" />
          </svg>
          {t("deal data")}
        </span>
        <span className="lg-item">
          <svg width="24" height="6" aria-hidden="true">
            <line x1="1" y1="3" x2="23" y2="3" stroke="#64748b" strokeWidth="1.5" strokeDasharray="4 3" />
          </svg>
          {t("structure only")}
        </span>
        <span className="lg-item">
          <span className="lg-sw" style={{ background: "#fbbf24" }} />▼ {t("downstream")}
        </span>
        <span className="lg-item">
          <span className="lg-sw" style={{ background: "#60a5fa" }} />▲ {t("upstream")}
        </span>
        {hasExternal && (
          <span className="lg-item" title={t("Named as a supplier or customer here, but its own node lives in another chain")}>
            <span className="gx-lg-ext" />
            {t("external = appears in another chain")}
          </span>
        )}
        <span className="lg-item lg-hint">
          {t("hover = full path · click = pin (click again / Esc = unpin) · click edge = contracts · layer label = collapse")}
        </span>
        <span className="gx-c2d-tools">
          <button
            type="button"
            className="gx-mini"
            disabled={!data || nCollapsed === columnSlugs.length}
            onClick={() => setCollapsed(new Set(columnSlugs))}
            title={t("Draw every layer as one bar — edges between layers stay visible")}
          >
            {t("Collapse all")}
          </button>
          <button
            type="button"
            className="gx-mini"
            disabled={nCollapsed === 0}
            onClick={() => setCollapsed(new Set())}
          >
            {t("Expand all")}
          </button>
        </span>
      </div>

      <div ref={wrapRef} className="c2d-wrap" style={{ background: bg }}>
        {loading && <div className="graph-msg">{t("Building the map…")}</div>}
        {loadErr && !loading && (
          <div className="graph-msg">{t("Could not load this chain ({err}). Pick another chain above.", { err: loadErr })}</div>
        )}
        <svg ref={svgRef} />
      </div>
      <div ref={tipRef} className="c2d-tip" />
      <div ref={epanelRef} className="c2d-epanel" />

      <p className="caption" style={{ marginTop: "0.6rem" }}>
        {t(sel === ALL ? "{c} companies · {e} edges across all chains" : "{c} companies · {e} edges in this chain", { c: counts.c, e: counts.e })}
        {nCollapsed > 0 && " · " + t(nCollapsed === 1 ? "{n} layer collapsed" : "{n} layers collapsed", { n: nCollapsed })}
      </p>
    </div>
  );
}
