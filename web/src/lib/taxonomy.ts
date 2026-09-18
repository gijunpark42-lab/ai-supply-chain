// taxonomy.ts — port of taxonomy.py, the single source of truth for the
// supply-chain vocabulary (layers, domains, colors, display names, order).
// Data files store SLUGS for `layer`/`domain`; display names come from here.

type Row = [slug: string, name: string, color: string];

// The 13 layers, TOP -> BOTTOM. This ORDER is canonical and drives column order.
export const LAYERS: Row[] = [
  ["application", "Application", "#a855f7"],
  ["ai_models", "AI Models", "#8b5cf6"],
  ["software_infra", "Software Infrastructure", "#6366f1"],
  ["cloud_infra", "Cloud Infrastructure", "#3b82f6"],
  ["system_integration", "System Integration", "#16a34a"],
  ["compute_hardware", "Compute Hardware", "#0ea5e9"],
  ["memory", "Memory", "#06b6d4"],
  ["interconnect", "Interconnect", "#14b8a6"],
  ["advanced_packaging", "Advanced Packaging", "#ec4899"],
  ["foundry", "Semiconductor Foundry", "#f97316"],
  ["equipment", "Semiconductor Equipment", "#f59e0b"],
  ["materials", "Semiconductor Materials", "#84cc16"],
  ["minerals", "Critical Minerals", "#a16207"],
];

// The 4 cross-cutting domains (drawn beside the stack, not inside it).
export const DOMAINS: Row[] = [
  ["power", "Power Infrastructure", "#dc2626"],
  ["thermal", "Thermal Management", "#0891b2"],
  ["security", "Security", "#7c3aed"],
  ["edge_ai", "Edge & Physical AI", "#db2777"],
];

// Derived lookups.
export const LAYER_ORDER: Record<string, number> = Object.fromEntries(
  LAYERS.map(([slug], i) => [slug, i])
);
export const LAYER_COLORS: Record<string, string> = Object.fromEntries(
  LAYERS.map(([slug, , color]) => [slug, color])
);
export const DOMAIN_COLORS: Record<string, string> = Object.fromEntries(
  DOMAINS.map(([slug, , color]) => [slug, color])
);
export const LAYER_NAMES: Record<string, string> = Object.fromEntries(
  LAYERS.map(([slug, name]) => [slug, name])
);
export const DOMAIN_NAMES: Record<string, string> = Object.fromEntries(
  DOMAINS.map(([slug, name]) => [slug, name])
);

// One color/name map covering both layers and domains (slug sets are disjoint).
export const GROUP_COLORS: Record<string, string> = { ...LAYER_COLORS, ...DOMAIN_COLORS };
export const GROUP_NAMES: Record<string, string> = { ...LAYER_NAMES, ...DOMAIN_NAMES };

// Domain order index (for Chain 2D right-panel ordering).
export const DOMAIN_ORDER: Record<string, number> = Object.fromEntries(
  DOMAINS.map(([slug], i) => [slug, i])
);

// Per-chain edge colors (ported from app.py CHAIN_COLORS). Edges are colored by chain.
export const CHAIN_COLORS: Record<string, string> = {
  nvidia_vera_rubin: "#76b900",
  google_tpu_v7_ironwood: "#4285f4",
  nvda_b200: "#ff6b35",
  optical_networking: "#8b5cf6",
  broadcom_custom_asic: "#f43f5e",
  hbm_memory: "#06d6a0",
  nand_flash: "#f59e0b",
  cpu_datacenter: "#ef4444",
  mlcc: "#0ea5e9",
  power_cooling: "#f97316",
  foundry: "#a78bfa",
  amd_mi450_helios: "#ed1c24",
  aws_trainium2: "#ff9900",
  packaging_substrate: "#14b8a6",
  tpu_v8t: "#1a73e8",
  tpu_v8i: "#34a853",
  amd_mi355: "#b91c1c",
  aws_trainium3: "#cc7a00",
  neocloud: "#2dd4bf",
  power_semiconductor: "#eab308",
  ai_bio: "#d946ef",
};

export const groupColor = (slug: string): string => GROUP_COLORS[slug] || "#94a3b8";
export const groupName = (slug: string): string => GROUP_NAMES[slug] || slug;
export const chainColor = (slug: string): string => CHAIN_COLORS[slug] || "#8b949e";

// Turn a chain slug into a readable label ("nvda_b200" -> "nvda b200").
export const slugLabel = (slug: string): string => slug.replace(/_/g, " ");
