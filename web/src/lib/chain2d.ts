// chain2d.ts — build the {columns, edges} model for the Chain 2D layer map, and
// an imperative SVG renderer ported (near 1:1) from app.py's CHAIN2D_TEMPLATE.
//
// Two builders feed the SAME renderer:
//   buildFromChain(chain)  — one curated chain file (preserves sector nesting)
//   buildFromMerged(graph) — ALL value chains at once (grouped by primary layer)
//
// The renderer draws the SVG ONCE per (data, width, collapsed-set). Everything
// interactive afterwards — hovering a company, pinning its supply path, lighting
// an edge — only toggles CSS classes on the elements that already exist. That is
// what keeps the merged "all chains" map (300+ pills, 1,200+ edges) responsive:
// we never rebuild the DOM on a mouse move.

import type { MergedGraph, GraphNode } from "./types";
import {
  LAYERS, DOMAINS, LAYER_ORDER, LAYER_NAMES, LAYER_COLORS, DOMAIN_NAMES, DOMAIN_COLORS,
} from "./taxonomy";
import { sigDate } from "./signals";
// Aliased: this file uses `t`, `name` as local variable names.
import { t as T, tr as TR, name as NM } from "./i18n";

export interface C2DPlayer {
  c: string; p: string; qd: number; ext: number; row: number; sec: string; sub: string;
}
export interface C2DHeader { label: string; sub: number; row: number; }
export interface C2DColumn {
  slug: string; name: string; color: string;
  kind: "layer" | "domain" | "external";
  players: C2DPlayer[]; headers: C2DHeader[]; nrows: number;
}
export interface C2DEdge {
  ci: number; pi: number; cj: number; pj: number; rel: string; nc: number; contracts: any[];
}
export interface C2DData { columns: C2DColumn[]; edges: C2DEdge[]; }

// Options the component passes to the renderer. All optional.
export interface C2DOptions {
  // Column slugs (e.g. "equipment", "power") drawn as ONE collapsed bar instead
  // of individual pills. Edges still attach to the bar, so supply paths that run
  // through a collapsed layer stay visible.
  collapsed?: Set<string>;
  // Called when the user clicks a band label / bar to collapse or expand it.
  onToggleCollapse?: (slug: string) => void;
  // A node key ("colIdx|playerIdx") whose ripple should be restored right after
  // drawing — used to keep a pin alive across re-renders (resize, collapse).
  pinned?: string | null;
  // Called whenever the pin changes because of a click inside the SVG.
  onPinChange?: (key: string | null) => void;
}

// What the renderer hands back so the component can drive it from outside
// (keyboard shortcuts) without re-rendering.
export interface C2DHandle {
  // Pin a node's full supply path (null = unpin).
  pin(key: string | null): void;
  // Esc behaviour: first closes the edge panel, then unpins. Returns true if
  // anything changed (so the caller knows whether to swallow the key press).
  escape(): boolean;
  // Currently pinned node key, or null.
  pinned(): string | null;
}

// ── Builder 1: a single curated chain file ──────────────────────────────────
function buildColumn(slug: string, name: string, color: string, kind: C2DColumn["kind"], group: any) {
  const players: C2DPlayer[] = [];
  const headers: C2DHeader[] = [];
  const raw: any[] = [];
  let row = 0;
  for (const sec of group.sectors || []) {
    headers.push({ label: sec.sector || "", sub: 0, row });
    row++;
    for (const ss of sec.sub_sectors || []) {
      headers.push({ label: ss.sub_sector || "", sub: 1, row });
      row++;
      for (const p of ss.players || []) {
        players.push({
          c: p.company, p: p.product || "", qd: (p.quarterly_data || []).length,
          ext: 0, row, sec: sec.sector || "", sub: ss.sub_sector || "",
        });
        raw.push(p);
        row++;
      }
    }
    for (const p of sec.players || []) {
      players.push({
        c: p.company, p: p.product || "", qd: (p.quarterly_data || []).length,
        ext: 0, row, sec: sec.sector || "", sub: "",
      });
      raw.push(p);
      row++;
    }
  }
  return { col: { slug, name, color, kind, players, headers, nrows: row } as C2DColumn, raw };
}

export function buildFromChain(chain: any): C2DData {
  const cols: C2DColumn[] = [];
  const raws: any[][] = [];

  const layerGroups: Record<string, any> = {};
  for (const g of chain.flow || []) if (g.layer) layerGroups[g.layer] = g;
  for (const slug of Object.keys(layerGroups).sort(
    (a, b) => (LAYER_ORDER[a] ?? 999) - (LAYER_ORDER[b] ?? 999)
  )) {
    const { col, raw } = buildColumn(slug, LAYER_NAMES[slug] || slug, LAYER_COLORS[slug] || "#94a3b8", "layer", layerGroups[slug]);
    cols.push(col);
    raws.push(raw);
  }

  const domOrder: Record<string, number> = Object.fromEntries(DOMAINS.map((d, i) => [d[0], i]));
  const domGroups: Record<string, any> = {};
  for (const g of chain.domains || []) if (g.domain) domGroups[g.domain] = g;
  for (const slug of Object.keys(domGroups).sort(
    (a, b) => (domOrder[a] ?? 999) - (domOrder[b] ?? 999)
  )) {
    const { col, raw } = buildColumn(slug, DOMAIN_NAMES[slug] || slug, DOMAIN_COLORS[slug] || "#94a3b8", "domain", domGroups[slug]);
    cols.push(col);
    raws.push(raw);
  }

  const pos: Record<string, [number, number]> = {};
  cols.forEach((col, ci) => col.players.forEach((pl, pi) => {
    if (!(pl.c in pos)) pos[pl.c] = [ci, pi];
  }));

  const ext: Record<string, number> = {};
  const pending: [number, number, [string | number, number], any][] = [];
  raws.forEach((raw, ci) =>
    raw.forEach((p, pi) =>
      (p.connects_to || []).forEach((e: any) => {
        const tgtCo = e.company;
        if (tgtCo === p.company) return;
        let tgt = pos[tgtCo] as [string | number, number] | undefined;
        if (!tgt) {
          if (!(tgtCo in ext)) ext[tgtCo] = Object.keys(ext).length;
          tgt = ["EXT", ext[tgtCo]];
        }
        pending.push([ci, pi, tgt, e]);
      })
    )
  );

  if (Object.keys(ext).length) {
    const extPlayers: C2DPlayer[] = Object.entries(ext)
      .sort((a, b) => a[1] - b[1])
      .map(([co, i]) => ({ c: co, p: "appears in another chain", qd: 0, ext: 1, row: i, sec: "", sub: "" }));
    cols.push({ slug: "external", name: "External", color: "#475569", kind: "external", players: extPlayers, headers: [], nrows: extPlayers.length });
  }
  const extCi = cols.length - 1;

  const edges: C2DEdge[] = [];
  for (const [ci, pi, tgt, e] of pending) {
    const [cj, pj] = tgt[0] === "EXT" ? [extCi, tgt[1] as number] : (tgt as [number, number]);
    const contracts = e.contracts || [];
    edges.push({ ci, pi, cj, pj, rel: e.relationship || "", nc: contracts.length, contracts });
  }

  return { columns: cols, edges };
}

// ── Builder 2: ALL chains merged (one big layered map from merged_graph) ─────
export function buildFromMerged(graph: MergedGraph): C2DData {
  const primaryOf = (n: GraphNode) =>
    (n.layers && n.layers[0]) || (n.domains && n.domains[0]) || "other";

  const byGroup: Record<string, GraphNode[]> = {};
  for (const n of graph.nodes) (byGroup[primaryOf(n)] ||= []).push(n);

  const cols: C2DColumn[] = [];
  const pos: Record<string, [number, number]> = {};

  const pushCol = (slug: string, name: string, color: string, kind: C2DColumn["kind"]) => {
    const ns = byGroup[slug];
    if (!ns || !ns.length) return;
    ns.sort((a, b) =>
      (a.sectors[0] || "").localeCompare(b.sectors[0] || "") || a.id.localeCompare(b.id)
    );
    const players: C2DPlayer[] = [];
    const headers: C2DHeader[] = [];
    let row = 0;
    let prevSec: string | null = null;
    for (const n of ns) {
      const sec = n.sectors[0] || "";
      if (sec && sec !== prevSec) {
        headers.push({ label: sec, sub: 0, row });
        row++;
        prevSec = sec;
      }
      players.push({
        c: n.id, p: n.products[0]?.product || "", qd: (n.quarterly_data || []).length,
        ext: 0, row, sec, sub: "",
      });
      row++;
    }
    const ci = cols.length;
    cols.push({ slug, name, color, kind, players, headers, nrows: row });
    players.forEach((pl, pi) => {
      if (!(pl.c in pos)) pos[pl.c] = [ci, pi];
    });
  };

  for (const [slug, name, color] of LAYERS) pushCol(slug, name, color, "layer");
  for (const [slug, name, color] of DOMAINS) pushCol(slug, name, color, "domain");
  pushCol("other", "Other", "#94a3b8", "layer");

  const edges: C2DEdge[] = [];
  for (const e of graph.edges) {
    const s = pos[e.source];
    const t = pos[e.target];
    if (!s || !t) continue;
    edges.push({
      ci: s[0], pi: s[1], cj: t[0], pj: t[1],
      rel: e.relationship || "", nc: (e.contracts || []).length, contracts: e.contracts || [],
    });
  }

  return { columns: cols, edges };
}

// ── Imperative SVG renderer (ported from CHAIN2D_TEMPLATE JS) ────────────────
const NS = "http://www.w3.org/2000/svg";
const esc = (s: string) => (s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;");
// Counted nouns in the current language ("3 contracts" / "계약 3건").
const plural = (n: number, word: string) => T(n === 1 ? `{n} ${word}` : `{n} ${word}s`, { n });
const companies = (n: number) => T(n === 1 ? "{n} company" : "{n} companies", { n });
// Column title: the English layer/domain name is the i18n key.
const colName = (col: any) => T(col.name || col.slug);
// Milliseconds the mouse must rest on a pill before its full path lights up.
// Without this, sweeping the mouse across the map flashes a new path every pixel.
const HOVER_DELAY = 70;

// The source label of the most recent contract on an edge ("NVIDIA Q2 FY2027
// (08-26-2026)"). Labels sort by the date in parentheses; if none carry a date
// we fall back to the first label we find.
function latestLabel(contracts: any[]): string {
  let best = "";
  let bestKey = -1;
  for (const c of contracts || []) {
    const src: string = c && c.source ? String(c.source) : "";
    if (!src) continue;
    const k = sigDate(src);
    if (!best || k > bestKey) { best = src; bestKey = k; }
  }
  return best;
}

export function renderChain2D(
  svg: SVGSVGElement,
  tipEl: HTMLElement,
  epanelEl: HTMLElement,
  data: C2DData,
  totalWidth: number,
  opts: C2DOptions = {}
): C2DHandle {
  svg.innerHTML = "";
  tipEl.style.display = "none";
  epanelEl.style.display = "none";
  epanelEl.innerHTML = "";

  const collapsedSet = opts.collapsed || new Set<string>();
  // Shallow-copy each column: the renderer attaches private `_` layout fields and
  // the model itself is memoised by the component, so we must not mutate it.
  const cols: any[] = data.columns.map((c) => ({ ...c }));

  // flatten into node/edge lists keyed by "colIdx|playerIdx"
  const nodes: any[] = [];
  const idx: Record<string, any> = {};
  cols.forEach((col, ci) =>
    col.players.forEach((p: any, pi: number) => {
      const k = ci + "|" + pi;
      const n = { k, ti: ci, j: pi, row: p.row, color: col.color, c: p.c, p: p.p, qd: p.qd, ext: p.ext || 0, sec: p.sec };
      nodes.push(n);
      idx[k] = n;
    })
  );
  const edges = data.edges.map((e) => ({
    s: e.ci + "|" + e.pi, t: e.cj + "|" + e.pj, rel: e.rel, nc: e.nc, cn: e.contracts || [],
  }));
  const outs: Record<string, number[]> = {};
  const ins: Record<string, number[]> = {};
  edges.forEach((e, i) => {
    (outs[e.s] = outs[e.s] || []).push(i);
    (ins[e.t] = ins[e.t] || []).push(i);
  });

  // geometry: LEFT = 13-layer stack; RIGHT = domain panel.
  // Both regions SHRINK-TO-FIT their widest band (capped by what the viewport
  // fits), so a small chain doesn't leave a field of dead space between its
  // pills and the domain panel — the panel pulls in and the map gets compact.
  const GUT = 180, padX = 14, padT = 8, pillW = 150, pillH = 26;
  const gapX = 10, gapY = 8, secH = 14, rowGap = 12, hdrH = 18, divW = 18;
  const isDomain = (col: any) => col.kind === "domain";
  const hasDom = cols.some(isDomain);
  const totalW = Math.max(900, totalWidth - 24);
  const maxLeftBand = Math.max(1, ...cols.filter((c) => !isDomain(c)).map((c: any) => c.players.length));
  const maxDomBand = hasDom
    ? Math.max(1, ...cols.filter(isDomain).map((c: any) => c.players.length))
    : 0;
  const rightCols = hasDom ? Math.min(3, maxDomBand) : 0;
  const RW = hasDom ? rightCols * (pillW + gapX) - gapX + 2 * padX : 0;
  const DIV = hasDom ? divW : 0;
  const fitPerRow = Math.max(
    1,
    Math.floor((totalW - RW - DIV - GUT - 2 * padX + gapX) / (pillW + gapX))
  );
  const leftPerRow = Math.min(fitPerRow, maxLeftBand);
  const leftW = GUT + 2 * padX + leftPerRow * (pillW + gapX) - gapX;
  const rightPerRow = Math.max(1, rightCols);
  const rightX0 = leftW + DIV + padX;
  let topL = padT, topR = padT;
  cols.forEach((col) => {
    const dom = isDomain(col);
    col._dom = dom;
    col._collapsed = collapsedSet.has(col.slug) && col.players.length > 0;
    col._perRow = dom ? rightPerRow : leftPerRow;
    // A collapsed column is a single bar spanning the whole band width.
    col._barW = col._perRow * (pillW + gapX) - gapX;
    const np = col.players.length;
    const rows = np === 0 ? 0 : col._collapsed ? 1 : Math.ceil(np / col._perRow);
    col._hasSec = !col._collapsed && (col.headers || []).some((h: any) => !h.sub);
    col._stripH = col._hasSec && np > 0 ? secH : 0;
    col._hdrH = dom ? hdrH : 0;
    col._x0 = dom ? rightX0 : GUT + padX;
    if (dom) { col._top = topR; col._pillTop = topR + col._hdrH + col._stripH; }
    else { col._top = topL; col._pillTop = topL + col._stripH; }
    const bandH = col._hdrH + col._stripH + Math.max(1, rows) * pillH + Math.max(0, rows - 1) * rowGap;
    col._bandH = bandH;
    if (dom) topR += bandH + gapY; else topL += bandH + gapY;
  });
  // Width = the content itself (+ slack for same-band arcs that bow out the side).
  const W = leftW + DIV + RW + 40;
  const H = Math.max(topL, topR) + 8;
  svg.setAttribute("width", String(W));
  svg.setAttribute("height", String(H));
  nodes.forEach((n) => {
    const col = cols[n.ti];
    if (col._collapsed) {
      // Spread the hidden players evenly along the bar so their edges fan out of
      // it instead of piling onto one point. ax0/ax1 = where horizontal edges
      // attach (the bar's left / right edge).
      const np = col.players.length;
      n.x = col._x0 + ((n.j + 0.5) / np) * col._barW - pillW / 2;
      n.y = col._pillTop;
      n.bar = true;
      n.ax0 = col._x0;
      n.ax1 = col._x0 + col._barW;
      return;
    }
    const s = n.j, rr = Math.floor(s / col._perRow), cc = s % col._perRow;
    n.x = col._x0 + cc * (pillW + gapX);
    n.y = col._pillTop + rr * (pillH + rowGap);
    n.bar = false;
    n.ax0 = n.x;
    n.ax1 = n.x + pillW;
  });

  function fitText(el: SVGTextElement, maxPx: number) {
    if (!el || maxPx <= 0) return;
    const full = el.textContent || "";
    const w = el.getComputedTextLength();
    if (!w) {
      const fs = parseFloat(el.getAttribute("font-size") || "11") || 11;
      const cw = fs * 0.6;
      if (full.length * cw <= maxPx) return;
      const keep = Math.max(1, Math.floor(maxPx / cw) - 1);
      el.textContent = full.length > keep ? full.slice(0, keep) + "…" : full;
      return;
    }
    if (w <= maxPx) return;
    let lo = 0, hi = full.length;
    while (lo < hi) {
      const mid = Math.ceil((lo + hi) / 2);
      el.textContent = full.slice(0, mid) + "…";
      if (el.getComputedTextLength() <= maxPx) lo = mid;
      else hi = mid - 1;
    }
    el.textContent = lo > 0 ? full.slice(0, lo) + "…" : "…";
  }
  function tip(ev: MouseEvent, html: string) {
    tipEl.innerHTML = html;
    tipEl.style.display = "block";
    tipEl.style.left = Math.min(ev.clientX + 14, window.innerWidth - 310) + "px";
    tipEl.style.top = ev.clientY + 12 + "px";
  }
  const hideTip = () => (tipEl.style.display = "none");
  const text = (x: number, y: number, cls?: string) => {
    const t = document.createElementNS(NS, "text");
    t.setAttribute("x", String(x));
    t.setAttribute("y", String(y));
    if (cls) t.classList.add(cls);
    return t;
  };

  // edges (drawn first)
  const gE = document.createElementNS(NS, "g");
  svg.appendChild(gE);
  const edgeEls: SVGPathElement[] = [];
  edges.forEach((e, i) => {
    const a = idx[e.s], b = idx[e.t];
    // Missing endpoint, or both ends inside the same collapsed bar: nothing to
    // draw. Keep a detached placeholder so edgeEls[i] always lines up with edges[i].
    if (!a || !b || (a.ti === b.ti && cols[a.ti]._collapsed)) {
      edgeEls.push(document.createElementNS(NS, "path"));
      return;
    }
    const ar = cols[a.ti]._dom, br = cols[b.ti]._dom;
    const cxa = a.x + pillW / 2, cxb = b.x + pillW / 2;
    let d: string;
    if (ar !== br) {
      const ax = ar ? a.ax0 : a.ax1, bx = br ? b.ax0 : b.ax1;
      const ya = a.y + pillH / 2, yb = b.y + pillH / 2, mx = (ax + bx) / 2;
      d = `M ${ax} ${ya} C ${mx} ${ya}, ${mx} ${yb}, ${bx} ${yb}`;
    } else if (b.ti > a.ti) {
      const y1 = a.y + pillH, y2 = b.y, mid = (y1 + y2) / 2;
      d = `M ${cxa} ${y1} C ${cxa} ${mid}, ${cxb} ${mid}, ${cxb} ${y2}`;
    } else if (b.ti < a.ti) {
      const y1 = a.y, y2 = b.y + pillH, mid = (y1 + y2) / 2;
      d = `M ${cxa} ${y1} C ${cxa} ${mid}, ${cxb} ${mid}, ${cxb} ${y2}`;
    } else {
      const ya = a.y + pillH / 2, yb = b.y + pillH / 2, xr = Math.max(a.x, b.x) + pillW + 30;
      d = `M ${a.x + pillW} ${ya} C ${xr} ${ya}, ${xr} ${yb}, ${b.x + pillW} ${yb}`;
    }
    const p = document.createElementNS(NS, "path");
    p.setAttribute("d", d);
    p.classList.add("c2edge");
    p.setAttribute("stroke", e.nc > 0 ? "#7dd3fc" : "#475569");
    p.setAttribute("stroke-width", e.nc > 0 ? "1.8" : "1");
    if (e.nc === 0) p.setAttribute("stroke-dasharray", "4 4");
    // Low base opacity so the web reads calm; hover/focus (elit), ripple
    // (edown/eup) and selection (esel) bring individual edges up to full.
    p.setAttribute("opacity", e.nc > 0 ? "0.35" : "0.2");
    (p.style as any).pointerEvents = "none";
    gE.appendChild(p);
    edgeEls.push(p);
    const hit = document.createElementNS(NS, "path");
    hit.setAttribute("d", d);
    hit.setAttribute("fill", "none");
    hit.setAttribute("stroke", "transparent");
    hit.setAttribute("stroke-width", "14");
    (hit.style as any).cursor = "pointer";
    hit.addEventListener("mouseenter", () => edgeEls[i].classList.add("elit"));
    hit.addEventListener("mousemove", (ev) => {
      const latest = latestLabel(e.cn);
      tip(ev,
        `<b>${esc(NM(a.c))} → ${esc(NM(b.c))}</b><br>${esc(TR(e.rel)) || esc(T("supply relationship"))}<br>` +
        `<span style="color:#7dd3fc">${plural(e.nc, "contract")}</span>` +
        (latest ? ` · ${esc(T("latest:"))} <span style="color:#fbbf24">${esc(latest)}</span>` : "") +
        `<br><span style="color:#64748b">${esc(T("click = detail"))}</span>`);
    });
    hit.addEventListener("mouseleave", () => {
      hideTip();
      if (selEdge !== i) edgeEls[i].classList.remove("elit");
    });
    hit.addEventListener("click", (ev) => { ev.stopPropagation(); showEdge(i); });
    gE.appendChild(hit);
  });

  // A band label doubles as the collapse / expand toggle for its column.
  const toggleGroup = (col: any) => {
    const g = document.createElementNS(NS, "g");
    g.classList.add("gx-coltoggle");
    g.setAttribute("role", "button");
    g.setAttribute("tabindex", "-1");
    const title = document.createElementNS(NS, "title");
    title.textContent = T(col._collapsed ? "Expand {name}" : "Collapse {name}", { name: colName(col) });
    g.appendChild(title);
    g.addEventListener("click", (ev) => {
      ev.stopPropagation();
      hideTip();
      if (opts.onToggleCollapse) opts.onToggleCollapse(col.slug);
    });
    return g;
  };

  // band labels
  cols.forEach((col) => {
    const cnt = companies(col.players.length);
    const chev = col._collapsed ? "▸" : "▾";
    const g = toggleGroup(col);
    if (col._dom) {
      const hit = document.createElementNS(NS, "rect");
      hit.setAttribute("x", String(col._x0 - 4));
      hit.setAttribute("y", String(col._top));
      hit.setAttribute("width", String(RW - 2 * padX + 8));
      hit.setAttribute("height", String(hdrH));
      hit.classList.add("gx-hit");
      g.appendChild(hit);
      const t = text(col._x0, col._top + 13, "c2hdr");
      t.setAttribute("fill", col.color || "#94a3b8");
      t.textContent = chev + " " + colName(col).toUpperCase() + "  ·  " + cnt;
      g.appendChild(t);
      svg.appendChild(g);
      fitText(t, RW - 2 * padX);
    } else {
      const ty = col._pillTop + pillH / 2;
      const hit = document.createElementNS(NS, "rect");
      hit.setAttribute("x", "0");
      hit.setAttribute("y", String(col._top));
      hit.setAttribute("width", String(GUT - 4));
      hit.setAttribute("height", String(Math.min(col._bandH, pillH + col._stripH + 6)));
      hit.classList.add("gx-hit");
      g.appendChild(hit);
      const cv = text(1, ty - 4, "gx-chev");
      cv.textContent = chev;
      g.appendChild(cv);
      const tx = text(14, ty - 4, "c2hdr");
      tx.setAttribute("font-size", "10.5px");
      tx.setAttribute("letter-spacing", ".2px");
      tx.setAttribute("fill", col.color || "#94a3b8");
      tx.textContent = colName(col).toUpperCase();
      g.appendChild(tx);
      const c = text(14, ty + 11, "c2cnt");
      c.setAttribute("fill", col.color || "#64748b");
      c.textContent = cnt + (col._collapsed ? " · " + T("collapsed") : "");
      g.appendChild(c);
      svg.appendChild(g);
      fitText(tx, GUT - 20);
      fitText(c, GUT - 20);
      // The External column is not part of this chain's structure — say so where
      // the reader's eye lands.
      if (col.kind === "external") {
        const note = text(14, ty + 23, "gx-extnote");
        note.textContent = T("appears in another chain");
        svg.appendChild(note);
        fitText(note, GUT - 20);
      }
    }
  });
  if (hasDom) {
    const dl = document.createElementNS(NS, "line");
    dl.setAttribute("x1", String(leftW + DIV / 2));
    dl.setAttribute("y1", String(padT));
    dl.setAttribute("x2", String(leftW + DIV / 2));
    dl.setAttribute("y2", String(H - 8));
    dl.setAttribute("stroke", "#1e293b");
    dl.setAttribute("stroke-width", "2");
    svg.appendChild(dl);
  }

  // sector labels
  cols.forEach((col, ci) => {
    if (!col._hasSec) return;
    let prev: string | null = null;
    col.players.forEach((p: any, pi: number) => {
      if (p.sec && p.sec !== prev) {
        const n = idx[ci + "|" + pi];
        const t = text(n.x, n.y - 4);
        t.setAttribute("fill", "#9aa6b2");
        t.setAttribute("font-size", "10px");
        t.textContent = TR(p.sec);
        svg.appendChild(t);
        fitText(t, pillW);
      }
      prev = p.sec;
    });
  });

  // ripple reachability — memoised per node, since hovering now walks the full
  // path every time and the merged map has 1,200+ edges.
  const reachMemo = new Map<string, Set<string>>();
  function reach(k: string, adj: Record<string, number[]>, next: (e: any) => string, tag: string) {
    const memoKey = tag + k;
    const hit = reachMemo.get(memoKey);
    if (hit) return hit;
    const seen = new Set<string>();
    const q = [k];
    while (q.length) {
      const cur = q.pop()!;
      (adj[cur] || []).forEach((i) => {
        const nx = next(edges[i]);
        if (!seen.has(nx)) { seen.add(nx); q.push(nx); }
      });
    }
    seen.delete(k);
    reachMemo.set(memoKey, seen);
    return seen;
  }
  const downOf = (k: string) => reach(k, outs, (e) => e.t, "d");
  const upOf = (k: string) => reach(k, ins, (e) => e.s, "u");

  // ── Highlight state (classes only — never rebuilds the SVG) ──
  type Mark = "rself" | "rdown" | "rup";
  const RANK: Record<Mark, number> = { rself: 3, rdown: 2, rup: 1 };
  const MARKS = ["dim", "rself", "rdown", "rup"];
  let pinned: string | null = null;
  const pillEls: Record<string, SVGGElement> = {};
  // Collapsed columns have one bar element instead of pills, keyed by column index.
  const barEls: Record<number, SVGGElement> = {};

  // Paint every pill / bar from a mark function. A bar takes the strongest mark
  // among the players hidden inside it (self > downstream > upstream).
  function paint(markOf: (k: string) => Mark | null, dimOthers: boolean) {
    nodes.forEach((n) => {
      const el = pillEls[n.k];
      if (!el) return;
      const m = markOf(n.k);
      el.classList.remove(...MARKS);
      if (m) el.classList.add(m);
      else if (dimOthers) el.classList.add("dim");
    });
    for (const [ci, el] of Object.entries(barEls)) {
      let best: Mark | null = null;
      const np = cols[+ci].players.length;
      for (let pi = 0; pi < np; pi++) {
        const m = markOf(ci + "|" + pi);
        if (m && (best === null || RANK[m] > RANK[best])) best = m;
      }
      el.classList.remove(...MARKS);
      if (best !== null) el.classList.add(best);
      else if (dimOthers) el.classList.add("dim");
    }
  }
  function clearAll() {
    paint(() => null, false);
    edgeEls.forEach((el) => el.classList.remove("dim", "edown", "eup", "elit"));
  }
  // Light the FULL supply path of node k: everything downstream in amber,
  // everything upstream in blue, the rest dimmed.
  function applyRipple(k: string) {
    const D = downOf(k), U = upOf(k);
    paint((kk) => (kk === k ? "rself" : D.has(kk) ? "rdown" : U.has(kk) ? "rup" : null), true);
    edgeEls.forEach((el, i) => {
      const e = edges[i];
      el.classList.remove("dim", "edown", "eup", "elit");
      const sD = e.s === k || D.has(e.s), tD = D.has(e.t);
      const sU = U.has(e.s), tU = e.t === k || U.has(e.t);
      if (sD && tD) el.classList.add("edown");
      else if (sU && tU) el.classList.add("eup");
      else el.classList.add("dim");
    });
  }

  // edge-detail panel
  let selEdge: number | null = null;
  function clearSel() {
    if (selEdge !== null && edgeEls[selEdge]) edgeEls[selEdge].classList.remove("esel");
    Object.values(pillEls).forEach((el) => el.classList.remove("epin"));
    selEdge = null;
  }
  function edgeBetween(k1: string, k2: string) {
    const res: number[] = [];
    (outs[k1] || []).forEach((i) => { if (edges[i].t === k2) res.push(i); });
    (outs[k2] || []).forEach((i) => { if (edges[i].t === k1) res.push(i); });
    return res;
  }
  function renderPanel(i: number) {
    const e = edges[i], a = idx[e.s], b = idx[e.t];
    let h = `<div class="ep-h"><span><b>${esc(NM(a.c))}</b> &rarr; <b>${esc(NM(b.c))}</b></span>`
      + `<span class="ep-x" id="ep-x">&times;</span></div>`
      + `<div class="ep-rel">${esc(TR(e.rel)) || esc(T("supply relationship"))}</div>`;
    if (e.cn && e.cn.length) {
      h += `<div class="ep-n">${esc(T(e.cn.length === 1 ? "{n} contract on this link" : "{n} contracts on this link", { n: e.cn.length }))}</div>`;
      e.cn.forEach((c: any) => {
        const meta = [c.units, c.value, c.date_signed, c.type]
          .filter((x) => x && x !== "no specific figure" && x !== "not stated").map(TR).join("  ·  ");
        h += `<div class="ep-c">`
          + (c.source ? `<div class="ep-src">${esc(c.source)}</div>` : "")
          + (c.signal ? `<div class="ep-sig">${esc(TR(c.signal))}</div>` : "")
          + (meta ? `<div class="ep-meta">${esc(meta)}</div>` : "")
          + `</div>`;
      });
    } else {
      h += `<div class="ep-empty">${esc(T("Structure only — no deal/contract data on this link yet."))}</div>`;
    }
    epanelEl.innerHTML = h;
    epanelEl.style.display = "block";
    const x = epanelEl.querySelector("#ep-x");
    if (x) x.addEventListener("click", (ev) => { ev.stopPropagation(); closePanel(); });
  }
  function showEdge(i: number) {
    clearSel();
    selEdge = i;
    edgeEls[i].classList.add("esel");
    if (pillEls[edges[i].s]) pillEls[edges[i].s].classList.add("epin");
    if (pillEls[edges[i].t]) pillEls[edges[i].t].classList.add("epin");
    renderPanel(i);
  }
  function closePanelSoft() { epanelEl.style.display = "none"; clearSel(); }
  function closePanel() { closePanelSoft(); setPinned(null); }

  // Pin / unpin. `silent` skips the callback (used when restoring a pin after a
  // re-render — the component already knows about it).
  function setPinned(k: string | null, silent = false) {
    if (pinned && pillEls[pinned]) pillEls[pinned].classList.remove("gx-pinned");
    pinned = k && idx[k] ? k : null;
    if (pinned) {
      applyRipple(pinned);
      if (pillEls[pinned]) pillEls[pinned].classList.add("gx-pinned");
    } else {
      clearAll();
    }
    if (!silent && opts.onPinChange) opts.onPinChange(pinned);
  }

  // Hover with a small delay: the timer is cancelled if the mouse leaves first.
  let hoverTimer: ReturnType<typeof setTimeout> | null = null;
  function cancelHover() {
    if (hoverTimer !== null) { clearTimeout(hoverTimer); hoverTimer = null; }
  }

  // collapsed bars (one per collapsed column)
  cols.forEach((col, ci) => {
    if (!col._collapsed) return;
    const g = document.createElementNS(NS, "g");
    g.classList.add("gx-bar");
    const r = document.createElementNS(NS, "rect");
    r.setAttribute("x", String(col._x0));
    r.setAttribute("y", String(col._pillTop));
    r.setAttribute("width", String(col._barW));
    r.setAttribute("height", String(pillH));
    r.setAttribute("rx", "13");
    r.setAttribute("stroke", col.color || "#94a3b8");
    r.setAttribute("stroke-width", "1.2");
    r.setAttribute("stroke-dasharray", "6 4");
    g.appendChild(r);
    const label = text(col._x0 + 12, col._pillTop + pillH / 2 + 4);
    label.textContent = T("{companies} collapsed — click to expand", { companies: companies(col.players.length) });
    g.appendChild(label);
    const title = document.createElementNS(NS, "title");
    title.textContent = T("Expand {name}", { name: colName(col) });
    g.appendChild(title);
    g.addEventListener("mousemove", (ev) =>
      tip(ev,
        `<b>${esc(colName(col).toUpperCase())}</b><br>` +
        esc(T("{companies} collapsed", { companies: companies(col.players.length) })) +
        `<br><span style="color:#64748b">${esc(T("click = expand"))}</span>`));
    g.addEventListener("mouseleave", hideTip);
    g.addEventListener("click", (ev) => {
      ev.stopPropagation();
      hideTip();
      if (opts.onToggleCollapse) opts.onToggleCollapse(col.slug);
    });
    svg.appendChild(g);
    barEls[ci] = g;
    fitText(label, col._barW - 20);
  });

  // company pills
  nodes.forEach((n) => {
    if (n.bar) return; // hidden inside a collapsed bar
    const g = document.createElementNS(NS, "g");
    g.classList.add("c2pill");
    const r = document.createElementNS(NS, "rect");
    r.setAttribute("x", String(n.x));
    r.setAttribute("y", String(n.y));
    r.setAttribute("width", String(pillW));
    r.setAttribute("height", String(pillH));
    r.setAttribute("rx", "13");
    r.setAttribute("stroke", n.ext ? "#475569" : n.color || "#94a3b8");
    r.setAttribute("stroke-width", "1.2");
    if (n.ext) { r.setAttribute("stroke-dasharray", "4 3"); r.setAttribute("fill-opacity", "0.55"); }
    g.appendChild(r);
    if (n.qd > 0) {
      const dot = document.createElementNS(NS, "circle");
      dot.setAttribute("cx", String(n.x + 12));
      dot.setAttribute("cy", String(n.y + pillH / 2));
      dot.setAttribute("r", "3");
      dot.setAttribute("fill", "#34d399");
      g.appendChild(dot);
    }
    const tx = text(n.x + (n.qd > 0 ? 20 : 10), n.y + pillH / 2 + 4);
    tx.textContent = NM(n.c);
    g.appendChild(tx);
    g.addEventListener("mouseenter", () => {
      if (pinned) return;
      cancelHover();
      hoverTimer = setTimeout(() => { hoverTimer = null; if (!pinned) applyRipple(n.k); }, HOVER_DELAY);
    });
    g.addEventListener("mousemove", (ev) => {
      const nd = downOf(n.k).size, nu = upOf(n.k).size;
      tip(ev,
        `<b>${esc(NM(n.c))}</b>` +
        (n.ext
          ? `<br><span style="color:#94a3b8">${esc(T("External — appears in another chain, not part of this chain's structure"))}</span>`
          : `<br>${esc(TR(n.p))}`) +
        `<br><span style="color:#34d399">${esc(plural(n.qd, "signal"))}</span> · ` +
        `<span style="color:#fbbf24">▼ ${esc(T("downstream"))} ${nd}</span> · ` +
        `<span style="color:#60a5fa">▲ ${esc(T("upstream"))} ${nu}</span>` +
        `<br><span style="color:#64748b">${esc(T(pinned === n.k ? "click = unpin" : "click = pin path"))} · ${esc(T("Esc = unpin"))}</span>`);
    });
    g.addEventListener("mouseleave", () => {
      cancelHover();
      if (!pinned) clearAll();
      hideTip();
    });
    g.addEventListener("click", (ev) => {
      ev.stopPropagation();
      cancelHover();
      // With a pin active, clicking a directly connected company opens that edge.
      if (pinned && pinned !== n.k) {
        const es = edgeBetween(pinned, n.k);
        if (es.length) { showEdge(es[0]); return; }
      }
      closePanelSoft();
      setPinned(pinned === n.k ? null : n.k);
    });
    svg.appendChild(g);
    pillEls[n.k] = g;
    fitText(tx, pillW - (n.qd > 0 ? 20 : 10) - 8);
  });
  svg.addEventListener("click", () => { setPinned(null); closePanelSoft(); });

  // Restore a pin that survived a re-render (resize / collapse toggle).
  if (opts.pinned && idx[opts.pinned]) setPinned(opts.pinned, true);

  return {
    pin: (k) => setPinned(k),
    escape: () => {
      if (selEdge !== null) { closePanelSoft(); return true; }
      if (pinned) { setPinned(null); return true; }
      return false;
    },
    pinned: () => pinned,
  };
}
