// data.ts — fetch the curated JSON and enrich the merged graph into the
// VizNode / VizLink shapes the 3D graph and panel consume. Ports app.py's
// degree / incoming-index / node-build loops (lines ~461-569).

import type {
  MergedGraph,
  GraphNode,
  VizNode,
  VizLink,
  LogoManifest,
  OtherRelation,
} from "./types";
import { GROUP_COLORS, CHAIN_COLORS } from "./taxonomy";
import { nodeSignalMeta } from "./signals";

export async function fetchJson<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Failed to fetch ${url}: ${res.status}`);
  return res.json();
}

export interface VizData {
  nodes: VizNode[];
  links: VizLink[]; // the AI edges (what the graph draws by default)
  // Non-AI relationships between two graph companies, drawn only when the viewer asks
  // ("Show non-AI relationships"). One whose other end is not a node is listed in the panel only.
  otherLinks: VizLink[];
  byId: Map<string, VizNode>;
}

// Non-AI links are one muted color, so they never read as a chain.
export const OTHER_LINK_COLOR = "#a8a29e";

export function buildViz(
  graph: MergedGraph,
  manifest: LogoManifest,
  reportKeys: Set<string>
): VizData {
  // Degree = in + out edges per node → drives sphere size.
  const degree: Record<string, number> = {};
  for (const e of graph.edges) {
    degree[e.source] = (degree[e.source] || 0) + 1;
    degree[e.target] = (degree[e.target] || 0) + 1;
  }

  // Who supplies INTO each node (incoming) and who each node supplies (outgoing).
  const incoming: Record<string, VizNode["incoming"]> = {};
  const outgoing: Record<string, VizNode["outgoing"]> = {};
  for (const e of graph.edges) {
    (incoming[e.target] ||= []).push({
      source: e.source,
      relationship: e.relationship,
      contracts: e.contracts || [],
    });
    (outgoing[e.source] ||= []).push({
      target: e.target,
      relationship: e.relationship,
      contracts: e.contracts || [],
      chain: e.chain,
    });
  }

  // All node ids — lets nodeSignalMeta tell "Samsung Q2 …" (own call) apart from
  // "Samsung Foundry Q2 …" (a different node's call) when judging freshness.
  const allIds = graph.nodes.map((n) => n.id);
  const isNode = new Set(allIds);

  // Non-AI relationships (other_edges) per company, from each side: for the supplier the
  // other company is a customer, for the customer it is a supplier; partners are partners.
  // They never count toward `degree`, so sphere sizes stay those of the AI map.
  const other: Record<string, OtherRelation[]> = {};
  for (const e of graph.other_edges || []) {
    const partner = e.relation === "partner";
    const base = { product: e.relationship, refs: e.refs || [] };
    (other[e.source] ||= []).push({ ...base, company: e.target, role: partner ? "partner" : "customer", isNode: isNode.has(e.target) });
    (other[e.target] ||= []).push({ ...base, company: e.source, role: partner ? "partner" : "supplier", isNode: isNode.has(e.source) });
  }

  const nodes: VizNode[] = graph.nodes.map((node: GraphNode) => {
    const layers = node.layers || [];
    const domains = node.domains || [];
    const primary = layers[0] || domains[0] || "unknown";
    const deg = degree[node.id] || 0;
    const val = Math.max(4, Math.floor(Math.pow(deg, 1.5)));
    const { badges, lastData, stale } = nodeSignalMeta(node.quarterly_data, node.id, allIds);
    const logo = manifest[node.id];
    return {
      ...node,
      primary,
      color: GROUP_COLORS[primary] || "#94a3b8",
      val,
      degree: deg,
      incoming: incoming[node.id] || [],
      outgoing: outgoing[node.id] || [],
      other: other[node.id] || [],
      badges,
      lastData,
      stale,
      logo: logo ? `/logos/${encodeURIComponent(logo.file)}` : null,
      logoBg: logo ? logo.bg : null,
      hasReport: reportKeys.has(node.id),
    };
  });

  const byId = new Map(nodes.map((n) => [n.id, n]));

  const links: VizLink[] = graph.edges.map((e) => ({
    source: e.source,
    target: e.target,
    relationship: e.relationship,
    contracts: (e.contracts || []).slice(0, 3),
    chain: e.chain,
    color: CHAIN_COLORS[e.chain] || "#8b949e",
    scope: "ai",
  }));

  // Only links whose BOTH ends are graph nodes can be drawn (the 3D engine needs both spheres).
  const otherLinks: VizLink[] = (graph.other_edges || [])
    .filter((e) => isNode.has(e.source) && isNode.has(e.target))
    .map((e) => ({
      source: e.source,
      target: e.target,
      relationship: e.relationship,
      contracts: [],
      chain: "",
      color: OTHER_LINK_COLOR,
      scope: "other",
      relation: e.relation, // "partner" links get no direction arrow (Graph3D)
    }));

  return { nodes, links, otherLinks, byId };
}
