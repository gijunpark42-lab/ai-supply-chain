"use client";

import { useEffect, useId, useRef, useState } from "react";
import { CHAIN_COLORS, LAYERS, DOMAINS, slugLabel } from "@/lib/taxonomy";
import { t, useLang } from "@/lib/i18n";
import "./Sidebar.css";

// Optional: how many currently VISIBLE nodes each chain / layer / domain has.
// page.tsx computes it from `visibleIds` (see INTEGRATION_NOTES/ui-nodepanel.md);
// when it is not passed the rows simply show no counts.
export interface VisibleCounts {
  chains: Record<string, number>;
  layers: Record<string, number>;
  domains: Record<string, number>;
}

interface Props {
  // On phones/tablets the sidebar is an off-canvas drawer: `open` slides it in,
  // `onClose` is the ✕ button. On desktop the CSS ignores both and it is always
  // a pinned column.
  open: boolean;
  onClose: () => void;
  glass: boolean;
  setGlass: (v: boolean) => void;
  chains: Set<string>;
  layers: Set<string>;
  domains: Set<string>;
  toggle: (kind: "chain" | "layer" | "domain", slug: string) => void;
  bulk: (kind: "chain" | "layer" | "domain", on: boolean) => void;
  dimStale: boolean;
  setDimStale: (v: boolean) => void;
  visibleCounts?: VisibleCounts;
}

// Remember collapse state across sessions (guarded for SSR).
function usePersistedBool(key: string, def: boolean): [boolean, (v: boolean) => void] {
  const [v, setV] = useState(def);
  useEffect(() => {
    try {
      const s = localStorage.getItem(key);
      if (s !== null) setV(s === "1");
    } catch {}
  }, [key]);
  const set = (nv: boolean) => {
    setV(nv);
    try {
      localStorage.setItem(key, nv ? "1" : "0");
    } catch {}
  };
  return [v, set];
}

function AllNone({ kind, bulk }: { kind: "chain" | "layer" | "domain"; bulk: Props["bulk"] }) {
  const stop = (fn: () => void) => (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    fn();
  };
  return (
    <span className="allnone">
      <button aria-label={t(`Select all ${kind}s`)} onClick={stop(() => bulk(kind, true))}>{t("All")}</button>
      <span>·</span>
      <button aria-label={t(`Clear all ${kind}s`)} onClick={stop(() => bulk(kind, false))}>{t("None")}</button>
    </span>
  );
}

function Row({
  checked,
  onChange,
  color,
  label,
  title,
  count,
}: {
  checked: boolean;
  onChange: () => void;
  color: string;
  label: string;
  title: string;
  count?: number; // visible-node count; undefined = counts not available
}) {
  return (
    <label className="check-row" title={title}>
      <input type="checkbox" checked={checked} onChange={onChange} />
      <span className="dot" style={{ background: color }} />
      <span className="row-label">{label}</span>
      {count !== undefined && (
        <span className={"sbx-cnt" + (count === 0 ? " zero" : "")} title={t("{n} visible companies", { n: count })}>
          {count}
        </span>
      )}
    </label>
  );
}

function Section({
  storageKey,
  title,
  kind,
  bulk,
  forceOpen,
  count,
  children,
}: {
  storageKey: string;
  title: string;
  kind: "chain" | "layer" | "domain";
  bulk: Props["bulk"];
  forceOpen: boolean;
  count: number;
  children: React.ReactNode;
}) {
  const [open, setOpen] = usePersistedBool(`sb.${storageKey}`, storageKey === "chains");
  const show = open || forceOpen;
  const bodyId = useId();
  return (
    <div className="sb-section">
      <div className="sb-head">
        <button className="sbx-section-toggle" aria-expanded={show} aria-controls={bodyId} onClick={() => setOpen(!open)}>
          <span className="sb-caret" aria-hidden="true">{show ? "▾" : "▸"}</span>
          <span className="sb-title">{title}</span>
          {count > 0 && <span className="sb-count">{count}</span>}
        </button>
        <AllNone kind={kind} bulk={bulk} />
      </div>
      <div className="sb-body" id={bodyId} hidden={!show}>{children}</div>
    </div>
  );
}

// Compact color key: the 13 layers in stack order, then the 4 domains. Useful
// when the Layers / Domains sections above are collapsed.
function Legend() {
  const [open, setOpen] = usePersistedBool("sb.legend", false);
  const legendId = useId();
  return (
    <div className="sbx-legend">
      <button className="sbx-legend-head" aria-expanded={open} aria-controls={legendId} onClick={() => setOpen(!open)}>
        <span className="sb-caret">{open ? "▾" : "▸"}</span>
        <span className="sb-title">{t("Legend")}</span>
        <span className="sb-count">{t("node colors")}</span>
      </button>
      {open && (
        <div className="sbx-legend-grid" id={legendId}>
          <div className="sbx-legend-sub">{t("Layers (top → bottom)")}</div>
          {LAYERS.map(([slug, name, color]) => (
            <span className="sbx-lg" key={slug} title={t(name)}>
              <span className="dot" style={{ background: color }} />
              {t(name)}
            </span>
          ))}
          <div className="sbx-legend-sub">{t("Domains")}</div>
          {DOMAINS.map(([slug, name, color]) => (
            <span className="sbx-lg" key={slug} title={t(name)}>
              <span className="dot" style={{ background: color }} />
              {t(name)}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

const CHAIN_SLUGS = Object.keys(CHAIN_COLORS);

export default function Sidebar({
  open,
  onClose,
  glass,
  setGlass,
  chains,
  layers,
  domains,
  toggle,
  bulk,
  dimStale,
  setDimStale,
  visibleCounts,
}: Props) {
  useLang(); // re-render on language change
  const [q, setQ] = useState("");
  const [mobile, setMobile] = useState(false);
  const drawerRef = useRef<HTMLElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const media = window.matchMedia("(max-width: 860px)");
    const update = () => setMobile(media.matches);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);

  useEffect(() => {
    if (!open || !mobile) return;
    const previous = document.activeElement as HTMLElement | null;
    closeRef.current?.focus();
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
      }
      if (event.key !== "Tab") return;
      const items = Array.from(drawerRef.current?.querySelectorAll<HTMLElement>(
        "button:not(:disabled), input:not(:disabled), a[href], [tabindex='0']"
      ) || []).filter((item) => item.getClientRects().length > 0);
      const first = items[0];
      const last = items[items.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last?.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first?.focus();
      }
    };
    document.addEventListener("keydown", handleKey);
    return () => {
      document.removeEventListener("keydown", handleKey);
      previous?.focus();
    };
  }, [open, mobile, onClose]);
  const query = q.trim().toLowerCase();
  // Match the displayed (translated) name and the English one.
  const match = (label: string, en = "") =>
    !query || label.toLowerCase().includes(query) || en.toLowerCase().includes(query);

  const chainRows = CHAIN_SLUGS.map((slug) => ({ slug, label: slugLabel(slug), color: CHAIN_COLORS[slug] })).filter(
    (r) => match(r.label, r.slug.replace(/_/g, " "))
  );
  const layerRows = LAYERS.filter(([, name]) => match(t(name), name));
  const domainRows = DOMAINS.filter(([, name]) => match(t(name), name));

  // How many checkboxes are currently OFF across the three sections — drives the
  // "Reset filters" button (disabled when there is nothing to reset).
  const offCount =
    CHAIN_SLUGS.length - chains.size + (LAYERS.length - layers.size) + (DOMAINS.length - domains.size);
  const reset = () => {
    bulk("chain", true);
    bulk("layer", true);
    bulk("domain", true);
    setQ("");
  };

  // Count lookup for a row; undefined when page.tsx did not pass counts.
  const cnt = (kind: keyof VisibleCounts, slug: string): number | undefined =>
    visibleCounts ? visibleCounts[kind][slug] || 0 : undefined;

  return (
    <aside id="graph-filters" ref={drawerRef} className={"sidebar" + (open ? " open" : "")}
      role={mobile && open ? "dialog" : undefined} aria-modal={mobile && open ? true : undefined}
      aria-label={t("Graph filters")}>
      <button ref={closeRef} className="sb-close" onClick={onClose} aria-label={t("Close filters")}>
        ✕
      </button>
      <p className="sbx-eyebrow">{t("EXPLORE THE NETWORK")}</p>
      <h2 className="sbx-heading">{t("Graph filters")}</h2>
      <p className="sbx-intro">{t("Narrow the Graph by product chain, layer, or domain. Other views have their own filters.")}</p>

      <input
        className="sb-search"
        type="search"
        placeholder={t("Filter chains, layers…")}
        aria-label={t("Find a chain, layer, or domain filter")}
        value={q}
        onChange={(e) => setQ(e.target.value)}
      />
      <div className="sbx-tools">
        <button
          className="sbx-reset"
          onClick={reset}
          disabled={offCount === 0 && !query}
          title={t("Turn every chain, layer and domain back on")}
        >
          ↺ {t("Reset filters")}
        </button>
        {offCount > 0 && (
          <span className="sbx-off">
            {t(offCount === 1 ? "{n} filter off" : "{n} filters off", { n: offCount })}
          </span>
        )}
      </div>
      <div className="sb-legend">
        <span className="dot" style={{ background: "#7dd3fc" }} /> {t("dot = each item's color in the graph")}
        {visibleCounts ? " · " + t("number = visible companies") : ""}
      </div>

      <Section
        storageKey="chains"
        title={t("Chains")}
        kind="chain"
        bulk={bulk}
        forceOpen={!!query}
        count={chainRows.length}
      >
        {chainRows.map((r) => (
          <Row
            key={r.slug}
            checked={chains.has(r.slug)}
            onChange={() => toggle("chain", r.slug)}
            color={r.color}
            label={r.label}
            title={`${r.label} — ${t("this chain's edge color in the graph")}`}
            count={cnt("chains", r.slug)}
          />
        ))}
        {chainRows.length === 0 && <div className="sb-empty">{t("no match")}</div>}
      </Section>

      <Section
        storageKey="layers"
        title={t("Layers")}
        kind="layer"
        bulk={bulk}
        forceOpen={!!query}
        count={layerRows.length}
      >
        {layerRows.map(([slug, name, color]) => (
          <Row
            key={slug}
            checked={layers.has(slug)}
            onChange={() => toggle("layer", slug)}
            color={color}
            label={t(name)}
            title={`${t(name)} — ${t("layer node color in the graph")}`}
            count={cnt("layers", slug)}
          />
        ))}
        {layerRows.length === 0 && <div className="sb-empty">{t("no match")}</div>}
      </Section>

      <Section
        storageKey="domains"
        title={t("Domains")}
        kind="domain"
        bulk={bulk}
        forceOpen={!!query}
        count={domainRows.length}
      >
        {domainRows.map(([slug, name, color]) => (
          <Row
            key={slug}
            checked={domains.has(slug)}
            onChange={() => toggle("domain", slug)}
            color={color}
            label={t(name)}
            title={`${t(name)} — ${t("domain node color in the graph")}`}
            count={cnt("domains", slug)}
          />
        ))}
        {domainRows.length === 0 && <div className="sb-empty">{t("no match")}</div>}
      </Section>

      <Legend />

      <hr className="sep" />

      <label className="check-row" title={t("Fade companies with no data in the last 180 days")}>
        <input type="checkbox" checked={dimStale} onChange={() => setDimStale(!dimStale)} />
        <span className="row-label">{t("Dim stale nodes (180d)")}</span>
      </label>

      <div className="sidebar-footer">
        <span className="sb-foot-label">⚙ {t("Appearance")}</span>
        <label className="check-row" title={t("Frosted-glass panel material")}>
          <input type="checkbox" checked={glass} onChange={() => setGlass(!glass)} />
          <span className="row-label">✨ {t("Liquid Glass")}</span>
        </label>
      </div>
    </aside>
  );
}
