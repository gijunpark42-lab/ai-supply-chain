"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { VizNode, VizLink } from "@/lib/types";
import { BADGE_EMOJI } from "@/lib/signals";
import { LAYERS, DOMAINS, GROUP_COLORS, groupName } from "@/lib/taxonomy";
import { useLang } from "@/lib/i18n";
import "./Graph.css";

// react-force-graph-3d is ESM + touches window/three at import time, so we load
// it client-side into state. This (unlike next/dynamic) forwards `ref` correctly,
// which we need for camera / force config / screen projection.

interface Props {
  nodes: VizNode[]; // ALL nodes (stable) — filtering is show/hide, not add/remove
  links: VizLink[]; // ALL links (stable)
  visibleIds: Set<string>;
  visibleChains: Set<string>;
  dimStale: boolean;
  glass: boolean;
  focusId: string | null;
  onNodeClick: (n: VizNode) => void;
  onBackgroundClick: () => void;

  // ── Optional additions (all have safe defaults) ──
  // Lets the graph change the focused company itself: Reset / Esc send null,
  // and clicking a node while focus mode is on walks the focus to that node.
  // Wire it to the same setter that feeds `focusId` (page.tsx: setFocusId).
  onFocusChange?: (id: string | null) => void;
  // Show the layer-color legend overlay (default true).
  showLegend?: boolean;
  // Max number of name labels drawn in focus mode (default 80). Labels are
  // ordered nearest-hop first, then by degree, so hubs keep theirs.
  labelLimit?: number;
}

interface LogoObj {
  n: any;
  chip: HTMLDivElement;
  img: HTMLImageElement;
  rWorld: number;
  dead?: boolean;
}

interface LabelObj {
  n: any;
  el: HTMLDivElement;
  rWorld: number;
}

// The focused neighborhood: which nodes/links are "in", and how many hops away
// each node sits (0 = the focused company itself).
interface Focus {
  id: string;
  nodes: Set<string>;
  links: Set<any>;
  hop: Map<string, number>;
}

const MIN_R = 9;
const STALE_COLOR = "#3a3f46";
// Opacity multipliers for everything OUTSIDE the focused neighborhood. They ride
// on the color string: three-forcegraph multiplies its material opacity by the
// alpha of an rgba() color, so dimming costs nothing per frame.
const DIM_NODE = 0.1;
const DIM_LINK = 0.08;

// A link endpoint is a raw id string before the force sim runs, and the node
// object afterwards. Module scope so the memoised accessors below can use it.
const linkId = (e: any) => (typeof e === "object" ? e.id : e);

// "#rrggbb" (or "#rgb") → "rgba(r, g, b, a)". Anything else is returned as is.
const alphaCache = new Map<string, string>();
function withAlpha(hex: string, a: number): string {
  const key = hex + "|" + a;
  const hit = alphaCache.get(key);
  if (hit) return hit;
  let out = hex;
  const m = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(hex || "");
  if (m) {
    let h = m[1];
    if (h.length === 3) h = h[0] + h[0] + h[1] + h[1] + h[2] + h[2];
    const r = parseInt(h.slice(0, 2), 16);
    const g = parseInt(h.slice(2, 4), 16);
    const b = parseInt(h.slice(4, 6), 16);
    out = `rgba(${r}, ${g}, ${b}, ${a})`;
  }
  alphaCache.set(key, out);
  return out;
}

const escHtml = (s: string) => String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;");

// True when a world point sits behind the camera. Projecting such a point gives
// mirrored screen coordinates, so overlays for it must be hidden. Uses the
// camera's view matrix directly (column-major Matrix4: row 2 = z) to avoid
// importing three just for one Vector3.
function behindCamera(cam: any, x: number, y: number, z: number): boolean {
  const e = cam && cam.matrixWorldInverse && cam.matrixWorldInverse.elements;
  if (!e) return false;
  const cz = e[2] * x + e[6] * y + e[10] * z + e[14];
  return cz > -(cam.near || 0.1);
}

export default function Graph3D({
  nodes,
  links,
  visibleIds,
  visibleChains,
  dimStale,
  glass,
  focusId,
  onNodeClick,
  onBackgroundClick,
  onFocusChange,
  showLegend = true,
  labelLimit = 80,
}: Props) {
  const { t, name, rev } = useLang();
  const fgRef = useRef<any>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const overlayRef = useRef<HTMLDivElement>(null);
  const labelsRef = useRef<HTMLDivElement>(null);
  const labelObjsRef = useRef<LabelObj[]>([]);
  const hoverIdRef = useRef<string | null>(null);
  const focusRef = useRef<string | null>(null);
  const rafRef = useRef<number | null>(null);
  const [size, setSize] = useState({ w: 800, h: 800 });
  const [FG, setFG] = useState<any>(null);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  // Hover also lives in state (not just the ref) so the particle / arrow accessors
  // below can re-evaluate. Node hover fires on enter+leave only, so this re-renders
  // a couple of times per interaction, not per frame.
  const [hoverNodeId, setHoverNodeId] = useState<string | null>(null);

  // Focus can be changed from inside (Reset / Esc / click-to-walk) as well as by
  // the `focusId` prop, so the prop is mirrored into local state and both write
  // to it. `onFocusChange` tells the parent so its search box stays in sync.
  const [localFocus, setLocalFocus] = useState<string | null>(focusId);
  useEffect(() => {
    setLocalFocus(focusId);
  }, [focusId]);
  const fid = localFocus;
  const [hops, setHops] = useState<1 | 2>(1);
  const [legendOpen, setLegendOpen] = useState(false);
  useEffect(() => {
    // Open by default on a desktop, folded on a phone where it would cover the map.
    setLegendOpen(window.innerWidth > 860);
  }, []);

  const changeFocus = useCallback(
    (id: string | null) => {
      setLocalFocus(id);
      focusRef.current = id;
      if (onFocusChange) onFocusChange(id);
    },
    [onFocusChange]
  );

  // Keep the latest visibility in a ref so the logo RAF loop reads fresh values
  // without rebuilding the overlay DOM on every filter toggle.
  const visRef = useRef(visibleIds);
  visRef.current = visibleIds;

  // Graph data is built ONCE from the full node/link set → stable identity →
  // the force simulation runs once and never reheats when filters change.
  const graphData = useMemo(
    () => ({ nodes: nodes as any, links: links as any }),
    [nodes, links]
  );

  useEffect(() => {
    let alive = true;
    import("react-force-graph-3d")
      .then((m) => alive && setFG(() => m.default))
      .catch((e) => alive && setLoadErr(e?.message || String(e)));
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setSize({ w: el.clientWidth, h: el.clientHeight }));
    ro.observe(el);
    setSize({ w: el.clientWidth, h: el.clientHeight });
    return () => ro.disconnect();
  }, []);

  const configuredRef = useRef(false);
  const configure = () => {
    const fg = fgRef.current;
    if (!fg || configuredRef.current) return;
    configuredRef.current = true;
    try {
      fg.d3Force("charge").strength(-400);
      fg.d3Force("link").distance(150);
    } catch {}
    // On a retina/4K display devicePixelRatio is 2-3, so the GPU renders 4-9x the
    // pixels of the canvas. Clamping to 1.5 is a huge fill-rate win and is visually
    // indistinguishable for spheres and lines.
    try {
      fg.renderer().setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
    } catch {}
    if ("ontouchstart" in window || navigator.maxTouchPoints > 0) {
      const c = fg.controls();
      c.rotateSpeed = 0.35;
      c.zoomSpeed = 0.5;
      c.panSpeed = 0.25;
    }
  };

  // ── Focus neighborhood ──────────────────────────────────────────────────
  // Walk `hops` steps out from the focused company over the links that are
  // currently visible (sidebar filters respected), in both directions — a
  // supplier's suppliers and a customer's customers both count.
  const focus = useMemo<Focus | null>(() => {
    if (!fid || !visibleIds.has(fid)) return null;
    const linkVisible = (l: any) =>
      visibleChains.has(l.chain) &&
      visibleIds.has(linkId(l.source)) &&
      visibleIds.has(linkId(l.target));
    const hop = new Map<string, number>([[fid, 0]]);
    let frontier = new Set<string>([fid]);
    for (let h = 1; h <= hops; h++) {
      const next = new Set<string>();
      for (const l of links as any[]) {
        if (!linkVisible(l)) continue;
        const s = linkId(l.source);
        const t = linkId(l.target);
        if (frontier.has(s) && !hop.has(t)) {
          hop.set(t, h);
          next.add(t);
        }
        if (frontier.has(t) && !hop.has(s)) {
          hop.set(s, h);
          next.add(s);
        }
      }
      frontier = next;
    }
    // A link is "in" when both ends are in — that also shows how the neighbors
    // connect to each other, not just to the center.
    const inLinks = new Set<any>();
    for (const l of links as any[])
      if (linkVisible(l) && hop.has(linkId(l.source)) && hop.has(linkId(l.target))) inLinks.add(l);
    return { id: fid, nodes: new Set(hop.keys()), links: inLinks, hop };
  }, [fid, hops, links, visibleIds, visibleChains]);

  // Build the logo overlay once per node set (not per filter change). The same
  // animation-frame loop also positions the focus-mode name labels.
  useEffect(() => {
    const overlay = overlayRef.current;
    if (!overlay) return;
    overlay.innerHTML = "";
    const logoNodes: LogoObj[] = [];
    for (const n of nodes as any[]) {
      if (!n.logo) continue;
      const chip = document.createElement("div");
      chip.className = "nlogo" + (n.logoBg === "dark" ? " dk" : "");
      const img = document.createElement("img");
      img.src = n.logo;
      img.alt = "";
      chip.appendChild(img);
      overlay.appendChild(chip);
      const o: LogoObj = { n, chip, img, rWorld: 4 * Math.cbrt(n.val) };
      img.onerror = () => {
        chip.remove();
        o.dead = true;
      };
      logoNodes.push(o);
    }

    const tick = () => {
      const fg = fgRef.current;
      const wrap = wrapRef.current;
      if (fg && wrap) {
        const cam = fg.camera();
        const halfH = wrap.clientHeight / 2;
        const perPx = halfH / Math.tan(((cam.fov / 2) * Math.PI) / 180);
        const W = wrap.clientWidth;
        const H = wrap.clientHeight;
        const vis = visRef.current;
        const c = cam.position;
        for (const o of logoNodes) {
          if (o.dead) continue;
          const n = o.n;
          if (n.x === undefined || !vis.has(n.id) || behindCamera(cam, n.x, n.y, n.z)) {
            o.chip.style.display = "none";
            continue;
          }
          const p = fg.graph2ScreenCoords(n.x, n.y, n.z);
          if (p.x < -80 || p.y < -80 || p.x > W + 80 || p.y > H + 80) {
            o.chip.style.display = "none";
            continue;
          }
          const d = Math.hypot(c.x - n.x, c.y - n.y, c.z - n.z);
          const rPx = (o.rWorld * perPx) / d;
          const forced = n.id === hoverIdRef.current || n.id === focusRef.current;
          if (rPx < MIN_R && !forced) {
            o.chip.style.display = "none";
            continue;
          }
          let w = Math.min(rPx * 1.8, 240);
          if (forced) w = Math.max(w, 40);
          o.img.style.width = w + "px";
          o.chip.style.padding = w * 0.07 + "px " + w * 0.11 + "px";
          o.chip.style.left = p.x + "px";
          o.chip.style.top = p.y + "px";
          o.chip.style.zIndex = forced ? "6" : "5";
          o.chip.style.display = "block";
        }
        // Name labels for the focused neighborhood (built by the effect below).
        // Placed just under each sphere; transform-only updates keep this cheap.
        for (const o of labelObjsRef.current) {
          const n = o.n;
          if (n.x === undefined || !vis.has(n.id) || behindCamera(cam, n.x, n.y, n.z)) {
            o.el.style.display = "none";
            continue;
          }
          const p = fg.graph2ScreenCoords(n.x, n.y, n.z);
          if (p.x < -60 || p.y < -40 || p.x > W + 60 || p.y > H + 40) {
            o.el.style.display = "none";
            continue;
          }
          const d = Math.hypot(c.x - n.x, c.y - n.y, c.z - n.z);
          const rPx = (o.rWorld * perPx) / d;
          o.el.style.transform = `translate3d(${p.x}px, ${p.y + rPx + 4}px, 0) translate(-50%, 0)`;
          o.el.style.display = "block";
        }
      }
      rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);
    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
  }, [nodes]);

  // Create one label element per focused node (capped). Positions come from the
  // RAF loop above, which reads labelObjsRef every frame.
  useEffect(() => {
    const host = labelsRef.current;
    if (!host) return;
    host.innerHTML = "";
    labelObjsRef.current = [];
    if (!focus) return;
    const byId = new Map<string, any>((nodes as any[]).map((n) => [n.id, n]));
    const ids = [...focus.nodes]
      .sort(
        (a, b) =>
          (focus.hop.get(a) || 0) - (focus.hop.get(b) || 0) ||
          (byId.get(b)?.degree || 0) - (byId.get(a)?.degree || 0) ||
          a.localeCompare(b)
      )
      .slice(0, Math.max(1, labelLimit));
    const objs: LabelObj[] = [];
    for (const id of ids) {
      const n = byId.get(id);
      if (!n) continue;
      const hop = focus.hop.get(id) || 0;
      const el = document.createElement("div");
      el.className = "gx-label" + (hop === 0 ? " focus" : hop === 1 ? " near" : "");
      el.textContent = name(id);
      el.style.borderLeftColor = n.color;
      host.appendChild(el);
      objs.push({ n, el, rWorld: 4 * Math.cbrt(n.val) });
    }
    labelObjsRef.current = objs;
    return () => {
      host.innerHTML = "";
      labelObjsRef.current = [];
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focus, nodes, labelLimit, rev]);

  // Fly the camera to a searched node (only if it is currently visible).
  useEffect(() => {
    focusRef.current = fid;
    if (!fid) return;
    const t = setTimeout(() => {
      const fg = fgRef.current;
      if (!fg) return;
      const node = (nodes as any[]).find((n) => n.id === fid);
      if (node && node.x !== undefined) {
        fg.cameraPosition(
          { x: (node.x || 0) + 80, y: node.y || 0, z: (node.z || 0) + 80 },
          node,
          1500
        );
      }
    }, 400);
    return () => clearTimeout(t);
  }, [fid, nodes]);

  // Esc leaves focus mode (ignored while typing in a text field).
  useEffect(() => {
    if (!fid) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA")) return;
      changeFocus(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [fid, changeFocus]);

  // ── Toolbar actions ─────────────────────────────────────────────────────
  // Frame the focused neighborhood if there is one, otherwise everything visible.
  const fitView = () => {
    const fg = fgRef.current;
    if (!fg) return;
    const set = focus ? focus.nodes : visibleIds;
    try {
      fg.zoomToFit(700, 40, (n: any) => set.has(n.id));
    } catch {}
  };
  // Leave focus mode, forget hover, and frame the whole visible graph again.
  const reset = () => {
    setHops(1);
    changeFocus(null);
    hoverIdRef.current = null;
    setHoverNodeId(null);
    const fg = fgRef.current;
    if (!fg) return;
    try {
      fg.zoomToFit(700, 40, (n: any) => visibleIds.has(n.id));
    } catch {}
  };

  // Legend rows: only the layers/domains that actually have a visible node.
  const legend = useMemo(() => {
    const counts = new Map<string, number>();
    for (const n of nodes) if (visibleIds.has(n.id)) counts.set(n.primary, (counts.get(n.primary) || 0) + 1);
    const rows: { slug: string; name: string; color: string; count: number }[] = [];
    for (const [slug, en, color] of [...LAYERS, ...DOMAINS]) {
      const c = counts.get(slug);
      if (c) rows.push({ slug, name: t(en), color, count: c });
    }
    let other = 0;
    for (const [slug, c] of counts) if (!(slug in GROUP_COLORS)) other += c;
    if (other) rows.push({ slug: "other", name: t("Other"), color: "#94a3b8", count: other });
    return rows;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nodes, visibleIds, rev]);

  // ── Accessors handed to the force graph (memoised: a new function identity
  //    makes the library re-walk every node/link's material) ──────────────
  const nodeColor = useCallback(
    (n: any) => {
      const base = dimStale && n.stale ? STALE_COLOR : n.color;
      return focus && !focus.nodes.has(n.id) ? withAlpha(base, DIM_NODE) : base;
    },
    [dimStale, focus]
  );
  const linkColor = useCallback(
    (l: any) => (focus && !focus.links.has(l) ? withAlpha(l.color, DIM_LINK) : l.color),
    [focus]
  );
  // Width grows with the number of contracts on the edge (capped so a busy hub
  // edge cannot turn into a pipe). 0 contracts = the thin structural line.
  const linkWidth = useCallback((l: any) => {
    const n = l.contracts ? l.contracts.length : 0;
    return n ? Math.min(1.2 + 0.6 * n, 3.2) : 0.5;
  }, []);
  // Hover tooltip: company · primary layer · chains count · last data date.
  const nodeLabel = useCallback(
    (n: any) => {
      const em = (n.badges || []).map((b: string) => BADGE_EMOJI[b] || "").join("");
      const chains = n.chains ? n.chains.length : 0;
      const meta = [
        groupName(n.primary),
        t(chains === 1 ? "{n} chain" : "{n} chains", { n: chains }),
        n.lastData ? t("last data {date}", { date: n.lastData }) : t("no dated signals"),
      ].join(" · ");
      const out = focus && !focus.nodes.has(n.id)
        ? `<div class="gx-tip-h">${escHtml(t("outside the current focus"))}</div>`
        : "";
      return (
        `<div class="gx-tip"><div class="gx-tip-t">${escHtml(name(n.id))}${em ? " " + em : ""}</div>` +
        `<div class="gx-tip-m">${escHtml(meta)}</div>${out}</div>`
      );
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [focus, rev]
  );

  // Particles and arrows are per-link THREE meshes: at 253 contract links (x2
  // particles) plus 1,104 arrows that was ~1,600 objects animating every frame,
  // whether or not anything was visible. Now only the links touching the hovered
  // or focused node get them — typically a handful.
  const emphasisId = hoverNodeId ?? fid;
  const touchesEmphasis = useCallback(
    (l: any) =>
      emphasisId != null &&
      (linkId(l.source) === emphasisId || linkId(l.target) === emphasisId),
    [emphasisId]
  );
  const linkParticles = useCallback(
    (l: any) => (touchesEmphasis(l) && l.contracts && l.contracts.length ? 2 : 0),
    [touchesEmphasis]
  );
  const linkArrowLength = useCallback(
    (l: any) => (touchesEmphasis(l) ? 4 : 0),
    [touchesEmphasis]
  );

  return (
    <div ref={wrapRef} className="graph-wrap gx-graph">
      <div ref={overlayRef} className="nodelogos" />
      <div ref={labelsRef} className="gx-labels" />
      {loadErr && <div className="graph-msg">{t("Failed to load 3D graph library:")} {loadErr}</div>}
      {!FG && !loadErr && <div className="graph-msg">{t("Initializing 3D engine…")}</div>}
      {FG && (
        <FG
          ref={fgRef}
          width={size.w}
          height={size.h}
          graphData={graphData}
          backgroundColor={glass ? "#262b35" : "#0d1117"}
          nodeLabel={nodeLabel}
          nodeColor={nodeColor}
          nodeVal={(n: any) => n.val}
          nodeOpacity={0.9}
          nodeVisibility={(n: any) => visibleIds.has(n.id)}
          linkVisibility={(l: any) =>
            visibleChains.has(l.chain) &&
            visibleIds.has(linkId(l.source)) &&
            visibleIds.has(linkId(l.target))
          }
          onNodeClick={(n: any) => {
            focusRef.current = n.id;
            // In focus mode a click walks the focus to the clicked company (when
            // the parent lets us change it), so you can follow a supply path hop
            // by hop. The detail panel opens either way.
            if (focus && onFocusChange && n.id !== focus.id) changeFocus(n.id);
            onNodeClick(n as VizNode);
          }}
          onNodeHover={(n: any) => {
            hoverIdRef.current = n ? n.id : null;
            setHoverNodeId(n ? n.id : null);
          }}
          onBackgroundClick={() => {
            focusRef.current = null;
            onBackgroundClick();
          }}
          linkColor={linkColor}
          linkOpacity={0.2}
          linkWidth={linkWidth}
          linkDirectionalArrowLength={linkArrowLength}
          linkDirectionalArrowRelPos={1}
          linkDirectionalArrowColor={(l: any) => l.color}
          linkDirectionalParticles={linkParticles}
          linkDirectionalParticleSpeed={0.005}
          linkDirectionalParticleColor={(l: any) => l.color}
          onEngineTick={configure}
        />
      )}

      {/* Overlay controls. Rendered even before the engine is ready so the layout
          does not jump; the handlers simply no-op until fgRef is set. */}
      <div className="gx-toolbar" role="toolbar" aria-label={t("Graph controls")}>
        <button type="button" className="gx-btn" onClick={fitView} title={t("Frame every visible company (or the focused neighborhood)")}>
          {t("Fit view")}
        </button>
        <button type="button" className="gx-btn" onClick={reset} title={t("Leave focus mode and frame the whole graph")}>
          {t("Reset")}
        </button>
        {focus && (
          <>
            <span className="gx-seg" role="group" aria-label={t("Neighborhood depth")}>
              <button
                type="button"
                className={"gx-seg-b" + (hops === 1 ? " on" : "")}
                aria-pressed={hops === 1}
                onClick={() => setHops(1)}
                title={t("Direct suppliers and customers only")}
              >
                {t("1 hop")}
              </button>
              <button
                type="button"
                className={"gx-seg-b" + (hops === 2 ? " on" : "")}
                aria-pressed={hops === 2}
                onClick={() => setHops(2)}
                title={t("Also the suppliers' suppliers and the customers' customers")}
              >
                {t("2 hops")}
              </button>
            </span>
            <span className="gx-chip" title={t("{n} companies within {h} hop(s) of {name}", { n: focus.nodes.size - 1, h: hops, name: name(focus.id) })}>
              {t("Focus:")} <b>{name(focus.id)}</b> · {t(focus.nodes.size - 1 === 1 ? "{n} neighbor" : "{n} neighbors", { n: focus.nodes.size - 1 })} · {t("Esc to exit")}
            </span>
          </>
        )}
      </div>

      {showLegend && (
        <div className={"gx-legend" + (legendOpen ? " open" : "")}>
          <button
            type="button"
            className="gx-legend-t"
            onClick={() => setLegendOpen((o) => !o)}
            aria-expanded={legendOpen}
            title={t("Node color = the company's primary layer")}
          >
            {t("Layers")} {legendOpen ? "▾" : "▸"}
          </button>
          {legendOpen && (
            <ul className="gx-legend-l">
              {legend.map((r) => (
                <li key={r.slug}>
                  <span className="gx-dot" style={{ background: r.color }} />
                  {r.name}
                  <span className="gx-n">{r.count}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
