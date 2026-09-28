// tower.ts — the pure logic behind the Supply-chain Tower page (/tower).
//
// The tower stacks the 13 layers as floors (Application on top, Critical Minerals at the
// bottom) with the cross-cutting domains as an annex beside it. Every company stands as a
// building on each floor it is filed under. This file decides WHAT the scene shows — which
// buildings light up, which links are drawn, what each floor's label says — and
// Tower3D.tsx only draws it. No three.js and no React here.

import type { VizLink, VizNode } from "./types";
import { DOMAINS, LAYERS } from "./taxonomy";

// ── Colors: height already says "how connected", so color says "where" ─────
// Concentration in Taiwan or Korea is an investing risk you can see at a glance.
export const COUNTRY_GROUPS: { name: string; color: string; codes: string[] }[] = [
  { name: "United States", color: "#60a5fa", codes: ["US"] },
  { name: "Korea", color: "#f472b6", codes: ["KR"] },
  { name: "Taiwan", color: "#34d399", codes: ["TW"] },
  { name: "Japan", color: "#f87171", codes: ["JP"] },
  { name: "China", color: "#fb923c", codes: ["CN", "HK"] },
  {
    name: "Europe",
    color: "#facc15",
    codes: ["DE", "CH", "GB", "FR", "NL", "IE", "DK", "IT", "SE", "ES", "BE", "AT", "FI", "NO", "LU", "PL"],
  },
  { name: "Other", color: "#94a3b8", codes: [] },
];

export function countryGroup(code: string | null | undefined) {
  return COUNTRY_GROUPS.find((g) => g.codes.includes(code || "")) || COUNTRY_GROUPS[COUNTRY_GROUPS.length - 1];
}

// ── Floors ──────────────────────────────────────────────────────────────────
export interface FloorDef {
  slug: string;
  name: string;
  color: string;
  annex: boolean; // true = a cross-cutting domain, drawn beside the main tower
}

// Top → bottom: the 13 layers, then the 4 domains.
export const FLOORS: FloorDef[] = [
  ...LAYERS.map(([slug, name, color]) => ({ slug, name, color, annex: false })),
  ...DOMAINS.map(([slug, name, color]) => ({ slug, name, color, annex: true })),
];
const FLOOR_INDEX: Record<string, number> = Object.fromEntries(FLOORS.map((f, i) => [f.slug, i]));

// Every floor a company stands on: each layer and domain it is filed under.
// (Corning is on Interconnect AND Advanced Packaging — one building on each.)
export function floorsOf(node: VizNode): string[] {
  return [...(node.layers || []), ...(node.domains || [])];
}

// One building = one company on one floor.
export const buildingKey = (id: string, floor: string) => `${id}|${floor}`;

// "1 supplier" / "3 suppliers".
const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

// The floor a company works on IN ONE CHAIN: the layer/domain of its product there
// (SK Hynix sits on Memory in an HBM chain). Falls back to its first floor.
export function chainFloorOf(node: VizNode, chain: string): string {
  const p = (node.products || []).find((x) => x.chain === chain && (x.layer || x.domain));
  return (p && (p.layer || p.domain)) || floorsOf(node)[0];
}

// ── A product chain, read floor by floor ───────────────────────────────────
export interface ChainInfo {
  id: string; // "nvidia_vera_rubin"
  company: string; // the chain's anchor, as its file names it ("NVIDIA", "SK Hynix / Samsung / Micron")
  chain_focus: string;
}

// A company's role in one chain, read from the chain's own links (supplier → customer):
//   anchor   = the company the chain is about (NVIDIA for Vera Rubin)
//   supplier = its links lead UP to an anchor (SK Hynix → TSMC → NVIDIA)
//   customer = an anchor's links lead DOWN to it (NVIDIA → Foxconn → Microsoft → OpenAI)
//   member   = in the chain but on neither side (or the chain has no anchor)
// A company on both sides (links run both ways) counts on the side it is nearer to. Equally
// near, the side with more anchors wins: NVIDIA buys HBM from all three HBM makers and sells
// chips to one of them, so it is a customer of the HBM chain. A full tie counts as supply
// (Cadence sells NVIDIA its EDA tools and buys its GPUs): the question here is supply.
export type MemberRole = "anchor" | "supplier" | "customer" | "member";

export interface ChainMember {
  node: VizNode;
  product: string; // what this company makes in this chain
  role: MemberRole;
}

// A floor with only this many suppliers (or fewer) is a bottleneck: one or two companies
// there can set the price, or stop the whole chain.
export const BOTTLENECK_MAX = 2;

export interface PathFloor {
  floor: FloorDef;
  members: ChainMember[]; // best-connected first
  counts: Record<MemberRole, number>;
  warn: boolean; // a bottleneck: 1–2 suppliers on this floor
}

// The chain's anchor companies. A chain file may name several ("SK Hynix / Samsung /
// Micron"); every one that is a company in this chain counts. Themes ("Neocloud", "AI Bio")
// have none — their floors get plain counts and no bottleneck flags.
function anchorsOf(info: ChainInfo | undefined, byId: Map<string, VizNode>, chain: string): string[] {
  return (info?.company || "")
    .split("/")
    .map((name) => name.trim())
    .filter((name) => byId.get(name)?.products.some((p) => p.chain === chain));
}

// Everyone reachable from `start` by following `next`, with how many links it took.
// Breadth-first (one ring of neighbours at a time), so each count is the shortest way.
function reach(next: Map<string, string[]>, start: string[]): Map<string, number> {
  const steps = new Map<string, number>();
  let ring = [...start];
  for (let d = 1; ring.length; d++) {
    const nextRing: string[] = [];
    for (const id of ring) {
      for (const n of next.get(id) || []) {
        if (steps.has(n) || start.includes(n)) continue;
        steps.set(n, d);
        nextRing.push(n);
      }
    }
    ring = nextRing;
  }
  return steps;
}

// Every floor the chain touches, top → bottom, each member with its role.
export function chainPath(nodes: VizNode[], links: VizLink[], chain: string, info: ChainInfo | undefined): PathFloor[] {
  const byId = new Map(nodes.map((n) => [n.id, n]));

  // Direction comes from the chain's own links, not from the floor order: an EDA vendor
  // sits high in the stack but SUPPLIES NVIDIA.
  const toCustomers = new Map<string, string[]>();
  const toSuppliers = new Map<string, string[]>();
  for (const l of links) {
    if (l.chain !== chain) continue;
    (toCustomers.get(l.source) || toCustomers.set(l.source, []).get(l.source)!).push(l.target);
    (toSuppliers.get(l.target) || toSuppliers.set(l.target, []).get(l.target)!).push(l.source);
  }
  const anchors = anchorsOf(info, byId, chain);
  const upstream = reach(toSuppliers, anchors); // steps from a supplier up to an anchor
  const downstream = reach(toCustomers, anchors); // steps from an anchor down to a customer
  // How many anchors a company sells to directly, and buys from directly.
  const sellsTo = (id: string) => anchors.filter((a) => toCustomers.get(id)?.includes(a)).length;
  const buysFrom = (id: string) => anchors.filter((a) => toCustomers.get(a)?.includes(id)).length;
  const roleOf = (id: string): MemberRole => {
    if (anchors.includes(id)) return "anchor";
    const up = upstream.get(id);
    const down = downstream.get(id);
    if (up !== undefined && down !== undefined && up === down) {
      return buysFrom(id) > sellsTo(id) ? "customer" : "supplier";
    }
    if (up !== undefined && (down === undefined || up < down)) return "supplier";
    if (down !== undefined) return "customer";
    return "member";
  };

  const perFloor: Record<string, ChainMember[]> = {};
  for (const node of nodes) {
    const seen = new Set<string>();
    for (const p of node.products || []) {
      const floor = p.chain === chain ? p.layer || p.domain : null;
      if (!floor || seen.has(floor)) continue;
      seen.add(floor);
      (perFloor[floor] ||= []).push({ node, product: p.product, role: roleOf(node.id) });
    }
  }

  const path: PathFloor[] = [];
  for (const floor of FLOORS) {
    const members = perFloor[floor.slug];
    if (!members) continue;
    members.sort((a, b) => b.node.degree - a.node.degree);
    const counts: Record<MemberRole, number> = { anchor: 0, supplier: 0, customer: 0, member: 0 };
    for (const m of members) counts[m.role]++;
    // A bottleneck is a SUPPLY floor with one or two suppliers. A floor of customers with one
    // company that also sells back into the chain (a cloud leasing capacity to NVIDIA) is not.
    const supplyFloor = counts.supplier >= counts.customer;
    path.push({ floor, members, counts, warn: supplyFloor && counts.supplier > 0 && counts.supplier <= BOTTLENECK_MAX });
  }
  return path;
}

// One line per floor, shared by the floor tags in 3D and the side panel:
// "★ NVIDIA · 1 supplier", "⚠ only 2 suppliers", "15 customers", "4 companies".
export function floorSummary(pf: PathFloor): string {
  const { anchor, supplier, customer, member } = pf.counts;
  const parts: string[] = [];
  if (anchor) {
    const names = pf.members.filter((m) => m.role === "anchor").map((m) => m.node.id);
    parts.push(`★ ${names.slice(0, 2).join(", ")}${names.length > 2 ? ` +${names.length - 2}` : ""}`);
  }
  if (supplier) parts.push((pf.warn ? "⚠ only " : "") + plural(supplier, "supplier", "suppliers"));
  if (customer) parts.push(plural(customer, "customer", "customers"));
  if (member) {
    // Next to suppliers or customers they are "others"; in a chain without an anchor, just companies.
    const mixed = anchor + supplier + customer > 0;
    parts.push(mixed ? plural(member, "other", "others") : plural(member, "company", "companies"));
  }
  return parts.join(" · ");
}

// ── What the 3D scene shows ─────────────────────────────────────────────────
export interface TowerEdge {
  from: string; // building key of the supplier
  to: string; // building key of the customer
  color: string;
}

export interface FloorNote {
  text: string;
  warn: boolean;
}

export interface TowerView {
  lit: Set<string> | null; // buildings to light up; null = every building normal
  edges: TowerEdge[];
  labels: Set<string>; // buildings whose name tag shows
  notes: Record<string, FloorNote>; // text after each floor's name
  tint?: Map<string, string>; // buildings painted in a mode's color instead of their country's
  marks?: Map<string, string>; // a symbol in front of a building's name tag (signal mode: ⚡ 📈 …)
}

// Nothing picked: every building normal, the best-connected company of each floor named.
export function defaultView(nodes: VizNode[]): TowerView {
  const perFloor: Record<string, VizNode[]> = {};
  for (const n of nodes) for (const f of floorsOf(n)) (perFloor[f] ||= []).push(n);
  const labels = new Set<string>();
  const notes: Record<string, FloorNote> = {};
  for (const [floor, list] of Object.entries(perFloor)) {
    list.sort((a, b) => b.degree - a.degree);
    labels.add(buildingKey(list[0].id, floor));
    notes[floor] = { text: plural(list.length, "company", "companies"), warn: false };
  }
  return { lit: null, edges: [], labels, notes };
}

// A chain picked: its companies lit on the floor they work on for it, its links drawn.
export function chainView(nodes: VizNode[], links: VizLink[], chain: string, path: PathFloor[]): TowerView {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const lit = new Set<string>();
  const notes: Record<string, FloorNote> = {};
  for (const pf of path) {
    for (const m of pf.members) lit.add(buildingKey(m.node.id, pf.floor.slug));
    notes[pf.floor.slug] = { text: floorSummary(pf), warn: pf.warn };
  }
  const edges: TowerEdge[] = [];
  for (const l of links) {
    if (l.chain !== chain) continue;
    const s = byId.get(l.source);
    const t = byId.get(l.target);
    if (!s || !t) continue;
    const from = buildingKey(s.id, chainFloorOf(s, chain));
    const to = buildingKey(t.id, chainFloorOf(t, chain));
    lit.add(from);
    lit.add(to);
    edges.push({ from, to, color: l.color });
  }
  // Name tags: the best-connected members of each floor (a tag on every one would pile up).
  const labels = new Set<string>();
  for (const pf of path) for (const m of pf.members.slice(0, LABELS_PER_FLOOR)) labels.add(buildingKey(m.node.id, pf.floor.slug));
  return { lit, edges, labels, notes };
}

const LABELS_PER_FLOOR = 3;
const PARTNER_LABELS = 12;

// A company picked: all its buildings and every company it trades with, links in chain colors.
export function companyView(nodes: VizNode[], links: VizLink[], id: string): TowerView {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const me = byId.get(id);
  const lit = new Set<string>();
  if (me) for (const f of floorsOf(me)) lit.add(buildingKey(id, f));
  const edges: TowerEdge[] = [];
  for (const l of links) {
    if (l.source !== id && l.target !== id) continue;
    const s = byId.get(l.source);
    const t = byId.get(l.target);
    if (!s || !t) continue;
    const from = buildingKey(s.id, chainFloorOf(s, l.chain));
    const to = buildingKey(t.id, chainFloorOf(t, l.chain));
    lit.add(from);
    lit.add(to);
    edges.push({ from, to, color: l.color });
  }
  // Name tags: the company on every floor, plus its best-connected partners.
  const degreeOf = (key: string) => byId.get(key.split("|")[0])?.degree || 0;
  const mine = [...lit].filter((k) => k.startsWith(id + "|"));
  const partners = [...lit].filter((k) => !k.startsWith(id + "|")).sort((a, b) => degreeOf(b) - degreeOf(a));
  const labels = new Set([...mine, ...partners.slice(0, PARTNER_LABELS)]);
  return { lit, edges, labels, notes: defaultView(nodes).notes };
}

// ── Signal mode: what the latest sourced signals say ────────────────────────
// The badges come from each company's own recent entries (lib/signals.ts reads them). Listed
// in priority order: a building with several takes the first one's color.
export const SIGNALS = [
  { key: "tight", mark: "⚡", label: "Supply tight", color: "#f59e0b" },
  { key: "guideup", mark: "📈", label: "Guidance raised", color: "#22c55e" },
  { key: "capex", mark: "🏗️", label: "Capacity expanding", color: "#a78bfa" },
  { key: "lta", mark: "📜", label: "Long-term contracts", color: "#38bdf8" },
];

export function signalView(nodes: VizNode[]): TowerView {
  const lit = new Set<string>();
  const tint = new Map<string, string>();
  const marks = new Map<string, string>();
  const counts: Record<string, Record<string, number>> = {}; // floor → signal key → companies
  const best: Record<string, VizNode> = {}; // floor → its best-connected company with a signal
  for (const node of nodes) {
    const found = SIGNALS.filter((s) => node.badges.includes(s.key));
    if (!found.length) continue;
    for (const floor of floorsOf(node)) {
      const key = buildingKey(node.id, floor);
      lit.add(key);
      tint.set(key, found[0].color);
      marks.set(key, found.map((s) => s.mark).join(""));
      counts[floor] ||= {};
      for (const s of found) counts[floor][s.key] = (counts[floor][s.key] || 0) + 1;
      if (!best[floor] || node.degree > best[floor].degree) best[floor] = node;
    }
  }
  const notes: Record<string, FloorNote> = {};
  for (const [floor, c] of Object.entries(counts)) {
    notes[floor] = { text: SIGNALS.filter((s) => c[s.key]).map((s) => `${s.mark} ${c[s.key]}`).join("  "), warn: false };
  }
  const labels = new Set(Object.entries(best).map(([floor, n]) => buildingKey(n.id, floor)));
  return { lit, edges: [], labels, notes, tint, marks };
}

// ── Generation compare: who joins and who drops out from one generation to the next ──
export const GENERATIONS: { from: string; to: string; label: string }[] = [
  { from: "nvda_b200", to: "nvidia_vera_rubin", label: "NVIDIA Blackwell → Rubin" },
  { from: "amd_mi355", to: "amd_mi450_helios", label: "AMD MI355 → MI450 Helios" },
  { from: "aws_trainium2", to: "aws_trainium3", label: "AWS Trainium2 → Trainium3" },
  { from: "google_tpu_v7_ironwood", to: "tpu_v8t", label: "Google TPU v7 → v8t" },
];

export const GEN_COLORS = { added: "#22c55e", dropped: "#ef4444", staying: "#cbd5e1" };

export interface GenMember {
  node: VizNode;
  product: string; // what it makes in the generation it is in (the new one if in both)
}

export interface CompareRow {
  floor: FloorDef;
  added: GenMember[]; // only in the new generation: the winners of the transition
  dropped: GenMember[]; // only in the old one
  staying: GenMember[]; // in both
}

// Each company of a chain with the floor it works on there and its product.
function membersOf(nodes: VizNode[], chain: string) {
  const out = new Map<string, { node: VizNode; floor: string; product: string }>();
  for (const node of nodes) {
    const p = (node.products || []).find((x) => x.chain === chain && (x.layer || x.domain));
    if (p) out.set(node.id, { node, floor: (p.layer || p.domain)!, product: p.product });
  }
  return out;
}

export function compareChains(nodes: VizNode[], from: string, to: string): CompareRow[] {
  const old = membersOf(nodes, from);
  const next = membersOf(nodes, to);
  const rows = new Map<string, CompareRow>();
  const row = (slug: string) => {
    const floor = FLOORS[FLOOR_INDEX[slug]];
    if (!rows.has(slug)) rows.set(slug, { floor, added: [], dropped: [], staying: [] });
    return rows.get(slug)!;
  };
  for (const [id, m] of next) (old.has(id) ? row(m.floor).staying : row(m.floor).added).push({ node: m.node, product: m.product });
  for (const [id, m] of old) if (!next.has(id)) row(m.floor).dropped.push({ node: m.node, product: m.product });
  const byDegree = (a: GenMember, b: GenMember) => b.node.degree - a.node.degree;
  for (const r of rows.values()) [r.added, r.dropped, r.staying].forEach((list) => list.sort(byDegree));
  return FLOORS.filter((f) => rows.has(f.slug)).map((f) => rows.get(f.slug)!);
}

export function compareView(links: VizLink[], rows: CompareRow[], to: string): TowerView {
  const lit = new Set<string>();
  const tint = new Map<string, string>();
  const labels = new Set<string>();
  const notes: Record<string, FloorNote> = {};
  const addedIds = new Set<string>();
  for (const r of rows) {
    // Name tags: the best-connected newcomers and dropouts of each floor (the full lists are
    // in the side panel; a tag on every one would pile up).
    const put = (list: GenMember[], color: string, tags: number) => {
      list.forEach((m, i) => {
        const key = buildingKey(m.node.id, r.floor.slug);
        lit.add(key);
        tint.set(key, color);
        if (i < tags) labels.add(key);
      });
    };
    put(r.added, GEN_COLORS.added, 3);
    put(r.dropped, GEN_COLORS.dropped, 2);
    put(r.staying, GEN_COLORS.staying, 0);
    r.added.forEach((m) => addedIds.add(m.node.id));
    const parts = [];
    if (r.added.length) parts.push(`+${r.added.length} new`);
    if (r.dropped.length) parts.push(`−${r.dropped.length} gone`);
    if (r.staying.length) parts.push(`${r.staying.length} stay`);
    notes[r.floor.slug] = { text: parts.join(" · "), warn: false };
  }
  // The new generation's links: green where a newcomer is involved.
  const floorIn = new Map<string, string>();
  for (const r of rows) for (const m of [...r.added, ...r.staying]) floorIn.set(m.node.id, r.floor.slug);
  const edges: TowerEdge[] = [];
  for (const l of links) {
    if (l.chain !== to || !floorIn.has(l.source) || !floorIn.has(l.target)) continue;
    const isNew = addedIds.has(l.source) || addedIds.has(l.target);
    edges.push({
      from: buildingKey(l.source, floorIn.get(l.source)!),
      to: buildingKey(l.target, floorIn.get(l.target)!),
      color: isNew ? GEN_COLORS.added : "#64748b",
    });
  }
  return { lit, edges, labels, notes, tint };
}

// "SK Hynix Q2 FY2026 (07-23-2026)" -> "2026-07-23", for sorting a company's signals newest first.
export function labelDate(label: string): string {
  const m = /\((\d{2})-(\d{2})-(\d{4})\)/.exec(label || "");
  return m ? `${m[3]}-${m[1]}-${m[2]}` : "";
}
