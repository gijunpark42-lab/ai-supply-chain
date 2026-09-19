"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { MergedGraph, LogoManifest, VizNode } from "@/lib/types";
import { fetchJson, buildViz } from "@/lib/data";
import { CHAIN_COLORS, LAYERS, DOMAINS } from "@/lib/taxonomy";
import { buildResolver } from "@/lib/company";
import Sidebar from "@/components/Sidebar";
import Graph3D from "@/components/Graph3D";
import NodePanel from "@/components/NodePanel";
import Screener from "@/components/Screener";
import Timelines from "@/components/Timelines";
import Chain2D from "@/components/Chain2D";
import Generations from "@/components/Generations";
import Coverage from "@/components/Coverage";
import CapexBacklog from "@/components/CapexBacklog";
import SearchBox from "@/components/SearchBox";
import Exposure from "@/components/Exposure";
import AskGraph from "@/components/AskGraph";
import Picks from "@/components/Picks";
import "./workspace.css";

const TABS = ["Graph", "Chain 2D", "Generations", "Exposure", "Timelines", "Screener", "Picks", "Capex", "Coverage", "Ask", "Semi Bot"] as const;
// External dashboard embedded in the "Semi Bot" tab (its own Vercel project; sends no
// X-Frame-Options / CSP frame-ancestors header, so it can be shown inline in an iframe).
const SEMI_BOT_URL = "https://semiband-dashboard.vercel.app";
type Tab = (typeof TABS)[number];
const VIEW_INFO: Record<Tab, { title: string; description: string }> = {
  Graph: { title: "Follow the connections.", description: "Explore companies and the supply relationships that connect them." },
  "Chain 2D": { title: "One product. Every layer.", description: "Trace a product chain from materials and equipment to its end customers." },
  Generations: { title: "See what changes next.", description: "Compare product generations and the suppliers gained, retained, or lost." },
  Exposure: { title: "Find the companies behind a chain.", description: "Explore sourced exposure, customer concentration, and generation changes." },
  Timelines: { title: "Put the signals in sequence.", description: "Track roadmaps, capacity, and product milestones across the supply chain." },
  Screener: { title: "Compare the companies.", description: "Review the latest reported results, guidance, supply status, and catalysts." },
  Picks: { title: "Track the picks.", description: "Two ranked one-quarter baskets, priced live against their 2026-09-18 entry." },
  Capex: { title: "Follow the investment.", description: "Compare capital spending and contracted demand across cloud infrastructure." },
  Coverage: { title: "Know what is on file.", description: "Check earnings dates, source freshness, and the enrichment queue." },
  Ask: { title: "Start with a question.", description: "Explore the stored signals and contracts with source-linked answers." },
  "Semi Bot": { title: "Your Semi Bot workspace.", description: "Open the trading dashboard alongside your supply-chain research." },
};

export default function Page() {
  const [graph, setGraph] = useState<MergedGraph | null>(null);
  const [manifest, setManifest] = useState<LogoManifest>({});
  const [reportKeys, setReportKeys] = useState<Set<string>>(new Set());
  const [err, setErr] = useState<string | null>(null);
  const [loadAttempt, setLoadAttempt] = useState(0);

  const [tab, setTab] = useState<Tab>("Graph");
  const [navOpen, setNavOpen] = useState(false); // mobile filter drawer
  const closeNav = useCallback(() => setNavOpen(false), []);
  const [glass, setGlass] = useState(true);
  const [dimStale, setDimStale] = useState(false);
  const [chains, setChains] = useState<Set<string>>(new Set(Object.keys(CHAIN_COLORS)));
  const [layers, setLayers] = useState<Set<string>>(new Set(LAYERS.map((l) => l[0])));
  const [domains, setDomains] = useState<Set<string>>(new Set(DOMAINS.map((d) => d[0])));

  const [selected, setSelected] = useState<VizNode | null>(null);
  const [focusId, setFocusId] = useState<string | null>(null);

  // Load curated data once.
  useEffect(() => {
    let cancelled = false;
    setErr(null);
    (async () => {
      try {
        // report_keys.json is a ~1KB array of company names. We only need to know
        // WHICH companies have a report to draw the badge — the full 1.6MB
        // reports.bundle.json is lazy-loaded by NodePanel when one is opened.
        const [g, m, rk] = await Promise.all([
          fetchJson<MergedGraph>("/data/merged_graph.json"),
          fetchJson<LogoManifest>("/logos/manifest.json"),
          fetchJson<string[]>("/data/report_keys.json"),
        ]);
        if (cancelled) return;
        setGraph(g);
        setManifest(m);
        setReportKeys(new Set(rk));
      } catch (e: any) {
        if (!cancelled) setErr(e?.message || String(e));
      }
    })();
    return () => { cancelled = true; };
  }, [loadAttempt]);

  // Reflect glass on <body> so CSS theme rules apply app-wide.
  useEffect(() => {
    document.body.classList.toggle("glass", glass);
  }, [glass]);

  // While the mobile drawer is open, stop the page behind it from scrolling.
  useEffect(() => {
    document.body.classList.toggle("nav-open", navOpen);
    return () => document.body.classList.remove("nav-open");
  }, [navOpen]);

  // On a phone the tab bar is a scrollable strip, so the tab you just picked can
  // sit off-screen. Pull it back into view. (`block: "nearest"` keeps this from
  // scrolling the page vertically as a side effect. No `behavior: "smooth"` —
  // with the strip's scroll-snap it silently does nothing in Chrome.)
  const tabsRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = tabsRef.current?.querySelector<HTMLElement>('[aria-selected="true"]');
    el?.scrollIntoView({ inline: "center", block: "nearest" });
  }, [tab]);

  const navigateTabs = (event: React.KeyboardEvent<HTMLDivElement>) => {
    const index = TABS.indexOf(tab);
    let next = index;
    if (event.key === "ArrowRight") next = (index + 1) % TABS.length;
    else if (event.key === "ArrowLeft") next = (index - 1 + TABS.length) % TABS.length;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = TABS.length - 1;
    else return;
    event.preventDefault();
    setTab(TABS[next]);
    tabsRef.current?.querySelectorAll<HTMLButtonElement>("[role='tab']")[next]?.focus();
  };

  const viz = useMemo(() => {
    if (!graph) return null;
    return buildViz(graph, manifest, reportKeys);
  }, [graph, manifest, reportKeys]);

  // Which nodes pass the sidebar filters (mirrors app.py 613-642). We compute a
  // visible-ID set rather than a filtered array, so the graph shows/hides nodes
  // instead of rebuilding — the layout stays put when you toggle a checkbox.
  const visibleIds = useMemo(() => {
    const s = new Set<string>();
    if (!viz) return s;
    for (const n of viz.nodes) {
      const chainOk = n.chains.length === 0 || n.chains.some((c) => chains.has(c));
      const hasGroups = n.layers.length + n.domains.length > 0;
      const groupOk =
        !hasGroups ||
        n.layers.some((l) => layers.has(l)) ||
        n.domains.some((d) => domains.has(d));
      if (chainOk && groupOk) s.add(n.id);
    }
    return s;
  }, [viz, chains, layers, domains]);

  const linkCount = useMemo(() => {
    if (!graph) return 0;
    let c = 0;
    // The force renderer replaces visual-link IDs with node objects. Count the
    // untouched source edges so changing filters cannot turn this total to zero.
    for (const l of graph.edges)
      if (chains.has(l.chain) && visibleIds.has(l.source) && visibleIds.has(l.target)) c++;
    return c;
  }, [graph, chains, visibleIds]);

  const toggle = (kind: "chain" | "layer" | "domain", slug: string) => {
    const map = { chain: [chains, setChains], layer: [layers, setLayers], domain: [domains, setDomains] } as const;
    const [set, setter] = map[kind] as [Set<string>, (s: Set<string>) => void];
    const next = new Set(set);
    next.has(slug) ? next.delete(slug) : next.add(slug);
    setter(next);
  };

  // Select-all / clear for a whole checklist section.
  const bulk = (kind: "chain" | "layer" | "domain", on: boolean) => {
    const all =
      kind === "chain"
        ? Object.keys(CHAIN_COLORS)
        : kind === "layer"
        ? LAYERS.map((l) => l[0])
        : DOMAINS.map((d) => d[0]);
    const setter = kind === "chain" ? setChains : kind === "layer" ? setLayers : setDomains;
    setter(on ? new Set(all) : new Set());
  };

  const resetFilters = () => {
    bulk("chain", true);
    bulk("layer", true);
    bulk("domain", true);
    setFocusId(null);
  };
  const filtersChanged = chains.size !== Object.keys(CHAIN_COLORS).length ||
    layers.size !== LAYERS.length || domains.size !== DOMAINS.length;

  // Companies the SearchBox can pick from = the ones the sidebar filters leave visible.
  const searchNodes = useMemo(
    () => (viz ? viz.nodes.filter((n) => visibleIds.has(n.id)) : []),
    [viz, visibleIds]
  );

  // Per-row counts for the sidebar checklists ("how many visible companies sit in
  // this chain / layer / domain") — recomputed only when the filters change.
  const visibleCounts = useMemo(() => {
    const chains: Record<string, number> = {};
    const layers: Record<string, number> = {};
    const domains: Record<string, number> = {};
    if (viz)
      for (const n of viz.nodes) {
        if (!visibleIds.has(n.id)) continue;
        for (const c of n.chains) chains[c] = (chains[c] || 0) + 1;
        for (const l of n.layers) layers[l] = (layers[l] || 0) + 1;
        for (const d of n.domains) domains[d] = (domains[d] || 0) + 1;
      }
    return { chains, layers, domains };
  }, [viz, visibleIds]);

  // Open a company's NodePanel by name — the same panel a 3D-graph node click
  // opens. Handed to the table views so any company name in them is clickable.
  const openNode = (id: string) => {
    const n = viz?.byId.get(id);
    if (n) setSelected(n);
  };
  // Maps a table's free-text company name back to a graph node id.
  const resolveCompany = useMemo(
    () => buildResolver(viz ? viz.byId.keys() : []),
    [viz]
  );

  return (
    <div className="app">
      <a className="workspace-skip" href="#research-panel">Skip to research</a>
      <Sidebar
        open={navOpen}
        onClose={closeNav}
        glass={glass}
        setGlass={setGlass}
        chains={chains}
        layers={layers}
        domains={domains}
        toggle={toggle}
        bulk={bulk}
        dimStale={dimStale}
        setDimStale={setDimStale}
        visibleCounts={visibleCounts}
      />

      {/* Backdrop only exists while the mobile drawer is open. */}
      {navOpen && <div className="nav-backdrop" onClick={closeNav} />}

      <main className="main">
        <header className="app-header">
          <div className="app-header-row">
            <button
              className="nav-toggle"
              onClick={() => setNavOpen(true)}
              aria-label="Open filters"
              aria-expanded={navOpen}
              aria-controls="graph-filters"
            >
              ☰<span className="nav-toggle-text">Filters</span>
            </button>
            <h1 className="app-title">AI Supply Chain</h1>
            <p className="app-sub">
              Research the companies behind AI.
            </p>
            <span className="workspace-source">Transcript-grounded research</span>
          </div>
          <div className="tabs" role="tablist" aria-label="Research views" ref={tabsRef} onKeyDown={navigateTabs}>
            {TABS.map((t, index) => (
              <button
                key={t}
                id={`research-tab-${index}`}
                className="tab"
                role="tab"
                aria-selected={tab === t}
                aria-controls="research-panel"
                tabIndex={tab === t ? 0 : -1}
                onClick={() => setTab(t)}
              >
                {t}
              </button>
            ))}
          </div>
        </header>

        <section id="research-panel" className="workspace-panel" role="tabpanel"
          aria-labelledby={`research-tab-${TABS.indexOf(tab)}`} tabIndex={0}>
        <div className="workspace-intro">
          <div>
            <p className="workspace-eyebrow">RESEARCH WORKSPACE <span aria-hidden="true">/</span> {tab}</p>
            <h2>{VIEW_INFO[tab].title}</h2>
            <p>{VIEW_INFO[tab].description}</p>
          </div>
          {tab === "Graph" && <div className="workspace-map-badge"><span aria-hidden="true" />Interactive 3D map</div>}
        </div>

        {err && tab !== "Semi Bot" && (
          <div className="workspace-state" role="alert">
            <span className="workspace-state-icon" aria-hidden="true">!</span>
            <h3>We couldn&apos;t load your research.</h3>
            <p>Check your connection and try again. Your filter selections will stay in place.</p>
            <button className="btn" onClick={() => setLoadAttempt((attempt) => attempt + 1)}>Try again</button>
          </div>
        )}
        {!viz && !err && tab !== "Semi Bot" && (
          <div className="workspace-state workspace-loading" role="status">
            <span className="workspace-loader" aria-hidden="true" />
            <h3>Loading your research workspace</h3>
            <p>Connecting companies, product chains, and source documents…</p>
          </div>
        )}

        {viz && tab === "Graph" && (
          <>
            <div className="workspace-graph-tools">
              <div className="workspace-search">
                <div className="workspace-search-label">
                  <label className="field-label" htmlFor="graph-company-search">Find a company</label>
                  <span className="workspace-shortcut"><kbd>/</kbd> to search</span>
                </div>
                <SearchBox
                  inputId="graph-company-search"
                  shortcut={!selected && !navOpen}
                  nodes={searchNodes}
                  onPick={(id) => setFocusId(id)}
                  onClear={() => setFocusId(null)}
                />
              </div>
              <dl className="workspace-stats" aria-label="Visible graph summary">
                <div><dt>Companies</dt><dd>{visibleIds.size.toLocaleString("en-US")}<span> / {viz.nodes.length.toLocaleString("en-US")}</span></dd></div>
                <div><dt>Connections</dt><dd>{linkCount.toLocaleString("en-US")}</dd></div>
                <div><dt>Active chains</dt><dd>{chains.size}<span> / {Object.keys(CHAIN_COLORS).length}</span></dd></div>
              </dl>
            </div>
            <div className="workspace-map-note">
              <span>Click a company for details. Drag to rotate · Scroll to zoom.</span>
              {filtersChanged ? <button onClick={resetFilters}>Reset graph filters ↗</button> : <span className="workspace-all-visible">All filters selected</span>}
            </div>
            <div className="workspace-map">
            <Graph3D
              nodes={viz.nodes}
              links={viz.links}
              visibleIds={visibleIds}
              visibleChains={chains}
              dimStale={dimStale}
              glass={glass}
              focusId={focusId}
              onNodeClick={setSelected}
              onBackgroundClick={() => setSelected(null)}
              onFocusChange={setFocusId}
            />
            {visibleIds.size === 0 && (
              <div className="workspace-map-empty" role="status">
                <div>
                  <span className="workspace-state-icon" aria-hidden="true">⌕</span>
                  <h3>No companies in this view</h3>
                  <p>Choose another chain, layer, or domain, or restore all graph filters.</p>
                  <button className="btn" onClick={resetFilters}>Show all companies</button>
                </div>
              </div>
            )}
            </div>
          </>
        )}

        {viz && tab === "Chain 2D" && <Chain2D glass={glass} />}
        {viz && tab === "Generations" && (
          <Generations nodes={viz.nodes} byId={viz.byId} onSelect={setSelected} />
        )}
        {viz && tab === "Timelines" && (
          <Timelines resolve={resolveCompany} onOpen={openNode} />
        )}
        {viz && tab === "Screener" && <Screener byId={viz.byId} onOpen={openNode} />}
        {viz && tab === "Picks" && <Picks onOpen={openNode} />}
        {viz && tab === "Capex" && (
          <CapexBacklog resolve={resolveCompany} onOpen={openNode} />
        )}
        {viz && tab === "Exposure" && (
          <Exposure nodes={viz.nodes} byId={viz.byId} onOpen={openNode} />
        )}
        {viz && tab === "Coverage" && <Coverage nodes={viz.nodes} onSelect={setSelected} />}
        {viz && tab === "Ask" && (
          <AskGraph nodes={viz.nodes} links={viz.links} onOpen={openNode} />
        )}
        {tab === "Semi Bot" && (
          <div className="embed">
            <p className="caption embed-caption">
              Semi Bot dashboard, shown inline.{" "}
              <a href={SEMI_BOT_URL} target="_blank" rel="noopener noreferrer">
                Open in a new tab ↗
              </a>
            </p>
            <iframe
              className="embed-frame"
              src={SEMI_BOT_URL}
              title="Semi Bot dashboard"
              loading="lazy"
              allow="clipboard-write; fullscreen"
            />
          </div>
        )}
        </section>
      </main>

      {selected && (
        <NodePanel
          node={selected}
          glass={glass}
          onClose={() => setSelected(null)}
          onNavigate={(id) => {
            const n = viz?.byId.get(id);
            if (n) setSelected(n);
          }}
        />
      )}
    </div>
  );
}
