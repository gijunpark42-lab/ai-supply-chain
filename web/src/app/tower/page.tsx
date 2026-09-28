"use client";

// /tower — the Supply-chain Tower (a prototype beside the main site, which it leaves alone).
// It reads the same data as the Graph tab (merged_graph.json + the chain list + the logo
// manifest) through the same node builder, so every enrich run shows up here too.
//
// Three ways to read it (the "modes"):
//   Chains       light up one product chain: customers, anchor, suppliers, bottlenecks
//   Generations  compare two generations (Blackwell → Rubin): who joins, who drops out
//   Signals      color companies by what their latest sourced entries say (supply tight …)

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import Tower3D from "@/components/Tower3D";
import SearchBox from "@/components/SearchBox";
import { buildViz, fetchJson } from "@/lib/data";
import type { LogoManifest, MergedGraph, VizNode } from "@/lib/types";
import { chainColor, slugLabel } from "@/lib/taxonomy";
import {
  COUNTRY_GROUPS,
  FLOORS,
  GENERATIONS,
  GEN_COLORS,
  SIGNALS,
  buildingKey,
  chainFloorOf,
  chainPath,
  chainView,
  compareChains,
  compareView,
  companyView,
  countryGroup,
  defaultView,
  floorSummary,
  floorsOf,
  labelDate,
  signalView,
  type ChainInfo,
  type CompareRow,
  type PathFloor,
} from "@/lib/tower";
import "@/components/Tower.css";

const FLOOR_NAME: Record<string, string> = Object.fromEntries(FLOORS.map((f) => [f.slug, f.name]));
const MEMBERS_SHOWN = 6; // per floor in the chain path; the rest is "+N more"

type Mode = "chains" | "generations" | "signals";
const MODES: [Mode, string][] = [
  ["chains", "Chains"],
  ["generations", "Generations"],
  ["signals", "Signals"],
];

export default function TowerPage() {
  const [graph, setGraph] = useState<MergedGraph | null>(null);
  const [logos, setLogos] = useState<LogoManifest>({});
  const [chainList, setChainList] = useState<ChainInfo[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [mode, setMode] = useState<Mode>("chains");
  const [chain, setChain] = useState<string | null>(null); // picked product chain (Chains mode)
  const [gen, setGen] = useState({ from: GENERATIONS[0].from, to: GENERATIONS[0].to }); // Generations mode
  const [company, setCompany] = useState<string | null>(null); // picked company (wins over the mode)
  const [folded, setFolded] = useState(false); // phones: the panel folds down to its title

  useEffect(() => {
    Promise.all([
      fetchJson<MergedGraph>("/data/merged_graph.json"),
      fetchJson<ChainInfo[]>("/data/chains/index.json"),
    ])
      .then(([g, chains]) => {
        setGraph(g);
        setChainList(chains);
      })
      .catch((e) => setErr(String(e?.message || e)));
    // Logo badges are a nicety: without the manifest the tower simply shows none.
    fetchJson<LogoManifest>("/logos/manifest.json")
      .then(setLogos)
      .catch(() => {});
  }, []);

  // Esc steps back: first the company, then the chain.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (company) setCompany(null);
      else if (chain) setChain(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [company, chain]);

  // The Graph tab's node builder (degree, links, logos, signal badges …).
  const viz = useMemo(() => (graph ? buildViz(graph, logos, new Set()) : null), [graph, logos]);

  const path: PathFloor[] = useMemo(
    () => (viz && chain ? chainPath(viz.nodes, viz.links, chain, chainList.find((c) => c.id === chain)) : []),
    [viz, chain, chainList]
  );
  const rows: CompareRow[] = useMemo(
    () => (viz && mode === "generations" ? compareChains(viz.nodes, gen.from, gen.to) : []),
    [viz, mode, gen]
  );
  const view = useMemo(() => {
    if (!viz) return null;
    if (company) return companyView(viz.nodes, viz.links, company);
    if (mode === "generations") return compareView(viz.links, rows, gen.to);
    if (mode === "signals") return signalView(viz.nodes);
    if (chain) return chainView(viz.nodes, viz.links, chain, path);
    return defaultView(viz.nodes);
  }, [viz, company, mode, rows, gen, chain, path]);

  // How many companies each chain has, and each country group — for the buttons and legend.
  const chainCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const n of viz?.nodes || []) for (const c of new Set(n.products.map((p) => p.chain))) counts[c] = (counts[c] || 0) + 1;
    return counts;
  }, [viz]);
  const countryCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const n of viz?.nodes || []) counts[countryGroup(n.country).name] = (counts[countryGroup(n.country).name] || 0) + 1;
    return counts;
  }, [viz]);

  const selected = company && viz ? viz.byId.get(company) || null : null;
  // The picked company's building the camera flies to: the floor it works on in the chain on
  // screen (the new generation when comparing), else its first floor.
  const focusChain = mode === "chains" ? chain : mode === "generations" ? gen.to : null;
  const focusKey = selected
    ? buildingKey(selected.id, focusChain ? chainFloorOf(selected, focusChain) : floorsOf(selected)[0])
    : null;
  // A new chain, compare or mode flies the camera back out to see the whole tower.
  const overviewKey = `${mode}|${mode === "chains" ? chain : mode === "generations" ? `${gen.from}>${gen.to}` : ""}`;

  const pickChain = (id: string | null) => {
    setCompany(null);
    setMode("chains");
    setChain(id);
  };
  const pickMode = (m: Mode) => {
    setCompany(null);
    setMode(m);
  };

  // The details under the mode controls sit below the fold: bring them into view when they change.
  const detailsRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (chain || company) detailsRef.current?.scrollIntoView({ block: "start", behavior: "smooth" });
  }, [chain, company]);

  const chainName = (id: string) => slugLabel(id);

  return (
    <div className="tw-page">
      <aside className={"tw-panel" + (folded ? " folded" : "")}>
        <div className="tw-panel-head">
          <h1 className="tw-title">Supply-chain Tower</h1>
          <span className="tw-proto">prototype</span>
          <button type="button" className="tw-fold" onClick={() => setFolded(!folded)}>
            {folded ? "▴ Show" : "▾ Hide"}
          </button>
        </div>
        <Link className="tw-back" href="/">
          ← Back to the graph
        </Link>

        {viz && (
          <div className="tw-search">
            <SearchBox nodes={viz.nodes} onPick={(id) => setCompany(id)} onClear={() => setCompany(null)} />
          </div>
        )}

        <p className="tw-help">
          Floors are the layers of the AI supply chain — apps on top, minerals at the bottom, power and
          cooling in the annex. Each company is a building shaped like its industry (glass towers, data
          halls, GPU packages, memory stacks, fabs, tanks, cooling towers). Bigger = more supply links,
          color = home country, red beacon = the eight best-connected. Scroll in for logos; click a
          building or a floor&apos;s name to fly there.
        </p>

        <div className="tw-legend" aria-label="Country colors">
          {COUNTRY_GROUPS.map((g) => (
            <span key={g.name}>
              <i style={{ background: g.color }} />
              {g.name} <small className="tw-muted">{countryCounts[g.name] || 0}</small>
            </span>
          ))}
        </div>

        <div className="tw-modes" role="tablist" aria-label="How to read the tower">
          {MODES.map(([m, label]) => (
            <button key={m} type="button" role="tab" aria-selected={mode === m} className={mode === m ? "on" : ""} onClick={() => pickMode(m)}>
              {label}
            </button>
          ))}
        </div>

        {mode === "chains" && (
          <>
            <h2 className="tw-section-title">Light up a product chain</h2>
            <div className="tw-chips">
              <button type="button" className={"tw-chip-btn" + (!chain ? " on" : "")} onClick={() => pickChain(null)}>
                All companies
              </button>
              {chainList.map((c) => (
                <button
                  key={c.id}
                  type="button"
                  className={"tw-chip-btn" + (chain === c.id ? " on" : "")}
                  onClick={() => pickChain(c.id)}
                  title={c.chain_focus}
                >
                  <i style={{ background: chainColor(c.id) }} />
                  {slugLabel(c.id)} <small>{chainCounts[c.id] || 0}</small>
                </button>
              ))}
            </div>
          </>
        )}

        {mode === "generations" && (
          <>
            <h2 className="tw-section-title">Compare two generations</h2>
            <div className="tw-chips">
              {GENERATIONS.map((g) => (
                <button
                  key={g.label}
                  type="button"
                  className={"tw-chip-btn" + (gen.from === g.from && gen.to === g.to ? " on" : "")}
                  onClick={() => {
                    setCompany(null);
                    setGen({ from: g.from, to: g.to });
                  }}
                >
                  {g.label}
                </button>
              ))}
            </div>
            <div className="tw-compare-pick">
              <select value={gen.from} onChange={(e) => setGen({ ...gen, from: e.target.value })} aria-label="Older generation">
                {chainList.map((c) => (
                  <option key={c.id} value={c.id}>
                    {chainName(c.id)}
                  </option>
                ))}
              </select>
              <span aria-hidden="true">→</span>
              <select value={gen.to} onChange={(e) => setGen({ ...gen, to: e.target.value })} aria-label="Newer generation">
                {chainList.map((c) => (
                  <option key={c.id} value={c.id}>
                    {chainName(c.id)}
                  </option>
                ))}
              </select>
            </div>
            <div className="tw-legend">
              <span>
                <i style={{ background: GEN_COLORS.added }} />
                new in {chainName(gen.to)}
              </span>
              <span>
                <i style={{ background: GEN_COLORS.dropped }} />
                gone
              </span>
              <span>
                <i style={{ background: GEN_COLORS.staying }} />
                in both
              </span>
            </div>
          </>
        )}

        {mode === "signals" && (
          <>
            <h2 className="tw-section-title">What the latest sourced entries say</h2>
            <div className="tw-legend">
              {SIGNALS.map((s) => (
                <span key={s.key}>
                  <i style={{ background: s.color }} />
                  {s.mark} {s.label}
                </span>
              ))}
            </div>
          </>
        )}

        <div ref={detailsRef}>
          {selected ? (
            <CompanyCard node={selected} onChain={pickChain} onClose={() => setCompany(null)} />
          ) : mode === "chains" && chain ? (
            <ChainPath id={chain} info={chainList.find((c) => c.id === chain)} path={path} onPick={setCompany} />
          ) : mode === "generations" ? (
            <CompareList rows={rows} from={chainName(gen.from)} to={chainName(gen.to)} onPick={setCompany} />
          ) : mode === "signals" && viz ? (
            <SignalList nodes={viz.nodes} onPick={setCompany} />
          ) : null}
        </div>
      </aside>

      {view && viz ? (
        <Tower3D nodes={viz.nodes} view={view} focusKey={focusKey} overviewKey={overviewKey} onPickCompany={setCompany} />
      ) : (
        <div className="tw-stage">
          <div className="tw-state">{err ? `Could not load the data: ${err}` : "Building the tower…"}</div>
        </div>
      )}
    </div>
  );
}

// The picked chain, read top → bottom: customers, the anchor, then the suppliers floor by floor.
function ChainPath({
  id,
  info,
  path,
  onPick,
}: {
  id: string;
  info: ChainInfo | undefined;
  path: PathFloor[];
  onPick: (id: string) => void;
}) {
  return (
    <section className="tw-path">
      <h2 className="tw-section-title">The chain, top to bottom</h2>
      <h3>{slugLabel(id)}</h3>
      {info?.chain_focus && (
        <p className="tw-muted">{info.chain_focus.length > 200 ? info.chain_focus.slice(0, 200) + "…" : info.chain_focus}</p>
      )}
      <ol>
        {path.map((pf) => {
          // On a floor that mixes roles, each company says which side it is on.
          const mixed = Object.values(pf.counts).filter((n) => n > 0).length > 1;
          return (
            <li key={pf.floor.slug} className={pf.warn ? "warn" : ""}>
              <div className="tw-path-floor">
                <i style={{ background: pf.floor.color }} />
                {pf.floor.name}
                <span className={"tw-role" + (pf.counts.anchor ? " anchor" : "")}>{floorSummary(pf)}</span>
              </div>
              <ul>
                {pf.members.slice(0, MEMBERS_SHOWN).map((m) => (
                  <li key={m.node.id}>
                    <button type="button" className="tw-link-btn" onClick={() => onPick(m.node.id)}>
                      {m.node.id}
                    </button>{" "}
                    {mixed && <span className={"tw-member-role " + m.role}>{m.role}</span>}{" "}
                    <span className="tw-muted">{m.product}</span>
                  </li>
                ))}
                {pf.members.length > MEMBERS_SHOWN && (
                  <li className="tw-muted">+{pf.members.length - MEMBERS_SHOWN} more</li>
                )}
              </ul>
            </li>
          );
        })}
      </ol>
      <p className="tw-muted tw-note">
        ⚠ = a supplier floor with only one or two companies in this chain: they can set the price, or stop the
        whole chain.
      </p>
    </section>
  );
}

// Two generations side by side, floor by floor: who joins (the winners of the transition),
// who drops out, and how many stay.
function CompareList({ rows, from, to, onPick }: { rows: CompareRow[]; from: string; to: string; onPick: (id: string) => void }) {
  const added = rows.reduce((n, r) => n + r.added.length, 0);
  const dropped = rows.reduce((n, r) => n + r.dropped.length, 0);
  const staying = rows.reduce((n, r) => n + r.staying.length, 0);
  const names = (list: CompareRow["added"], color: string) =>
    list.map((m) => (
      <li key={m.node.id}>
        <i className="tw-dot" style={{ background: color }} />
        <button type="button" className="tw-link-btn" onClick={() => onPick(m.node.id)}>
          {m.node.id}
        </button>{" "}
        <span className="tw-muted">{m.product}</span>
      </li>
    ));
  return (
    <section className="tw-path">
      <h2 className="tw-section-title">
        {from} → {to}
      </h2>
      <p className="tw-muted">
        {added} new · {dropped} gone · {staying} in both
      </p>
      <ol>
        {rows
          .filter((r) => r.added.length || r.dropped.length)
          .map((r) => (
            <li key={r.floor.slug}>
              <div className="tw-path-floor">
                <i style={{ background: r.floor.color }} />
                {r.floor.name}
                <span className="tw-role">
                  {[r.added.length && `+${r.added.length}`, r.dropped.length && `−${r.dropped.length}`, r.staying.length && `${r.staying.length} stay`]
                    .filter(Boolean)
                    .join(" · ")}
                </span>
              </div>
              <ul>
                {names(r.added, GEN_COLORS.added)}
                {names(r.dropped, GEN_COLORS.dropped)}
              </ul>
            </li>
          ))}
      </ol>
      <p className="tw-muted tw-note">
        Floors where nothing changes are left out of this list; on the tower they stay white. The links drawn are
        the new generation&apos;s — green where a newcomer is involved.
      </p>
    </section>
  );
}

// Each signal with the companies that carry it, best-connected first.
function SignalList({ nodes, onPick }: { nodes: VizNode[]; onPick: (id: string) => void }) {
  return (
    <section className="tw-path">
      <ol>
        {SIGNALS.map((s) => {
          const list = nodes.filter((n) => n.badges.includes(s.key)).sort((a, b) => b.degree - a.degree);
          return (
            <li key={s.key}>
              <div className="tw-path-floor">
                <i style={{ background: s.color }} />
                {s.mark} {s.label}
                <span className="tw-role">{list.length}</span>
              </div>
              <ul>
                {list.slice(0, 8).map((n) => (
                  <li key={n.id}>
                    <button type="button" className="tw-link-btn" onClick={() => onPick(n.id)}>
                      {n.id}
                    </button>{" "}
                    <span className="tw-muted">{floorsOf(n).map((f) => FLOOR_NAME[f] || f).join(", ")}</span>
                  </li>
                ))}
                {list.length > 8 && <li className="tw-muted">+{list.length - 8} more</li>}
              </ul>
            </li>
          );
        })}
      </ol>
      <p className="tw-muted tw-note">
        Read from each company&apos;s own recent entries (calls, filings, releases), so the colors move with every
        enrich run. Click a company to see the entries behind it.
      </p>
    </section>
  );
}

// The picked company: where it stands, who it trades with, and its latest sourced signals.
function CompanyCard({
  node,
  onChain,
  onClose,
}: {
  node: VizNode;
  onChain: (id: string) => void;
  onClose: () => void;
}) {
  const suppliers = new Set(node.incoming.map((x) => x.source)).size;
  const customers = new Set(node.outgoing.map((x) => x.target)).size;
  const signals = [...(node.quarterly_data || [])]
    .sort((a, b) => labelDate(b.quarter).localeCompare(labelDate(a.quarter)))
    .slice(0, 3);
  const badges = SIGNALS.filter((s) => node.badges.includes(s.key));
  return (
    <section className="tw-card">
      <h2 className="tw-section-title">Company</h2>
      <div className="tw-card-head">
        <h3>{node.id}</h3>
        <button type="button" onClick={onClose} aria-label="Close the company card">
          ✕
        </button>
      </div>
      <p className="tw-muted">{[node.ticker, countryGroup(node.country).name].filter(Boolean).join(" · ")}</p>
      {badges.length > 0 && <p className="tw-badges">{badges.map((s) => `${s.mark} ${s.label}`).join("   ")}</p>}
      <dl className="tw-kv">
        <dt>Floors</dt>
        <dd>{floorsOf(node).map((f) => FLOOR_NAME[f] || f).join(", ")}</dd>
        <dt>Suppliers</dt>
        <dd>{suppliers}</dd>
        <dt>Customers</dt>
        <dd>{customers}</dd>
      </dl>
      {node.chains.length > 0 && (
        <>
          <h2 className="tw-section-title">In {node.chains.length} chains</h2>
          <div className="tw-chips">
            {node.chains.map((c) => (
              <button key={c} type="button" className="tw-chip-btn" onClick={() => onChain(c)}>
                <i style={{ background: chainColor(c) }} />
                {slugLabel(c)}
              </button>
            ))}
          </div>
        </>
      )}
      {signals.length > 0 && (
        <>
          <h2 className="tw-section-title">Latest signals</h2>
          <ul className="tw-signals">
            {signals.map((q, i) => (
              <li key={i}>
                <p>{q.signal}</p>
                {q.figure && q.figure !== "no specific figure" && <p className="tw-fig">{q.figure}</p>}
                <p className="tw-src">{q.quarter}</p>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
