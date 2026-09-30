"use client";

import { useMemo, useState } from "react";
import type { VizNode } from "@/lib/types";
import {
  TRANSITIONS,
  computeTransition,
  type GenStatus,
  type TransitionRow,
} from "@/lib/transitions";
import { GROUP_COLORS, groupName, slugLabel } from "@/lib/taxonomy";
import { t, trJoined, name, useLang } from "@/lib/i18n";

interface Props {
  nodes: VizNode[];
  byId: Map<string, VizNode>;
  onSelect: (n: VizNode) => void;
}

const STATUS_META: Record<GenStatus, { icon: string; title: string; cls: string; note: string }> = {
  retained: {
    icon: "✅",
    title: "Retained",
    cls: "retained",
    note: "in both generations — watch the content delta",
  },
  gained: {
    icon: "📈",
    title: "New in next gen",
    cls: "gained",
    note: "won a socket it didn't have in the current generation",
  },
  lost: {
    icon: "⚠️",
    title: "Not in next gen",
    cls: "lost",
    note: "lost the socket — or not yet added to the new chain",
  },
};

function RowLine({ r, byId, onSelect }: { r: TransitionRow; byId: Props["byId"]; onSelect: Props["onSelect"] }) {
  const changed = r.productFrom && r.productTo && r.productFrom !== r.productTo;
  return (
    <div
      className="gen-row"
      onClick={() => {
        const n = byId.get(r.id);
        if (n) onSelect(n);
      }}
      title={groupName(r.primary)}
    >
      <span className="dot" style={{ background: GROUP_COLORS[r.primary] || "#94a3b8" }} />
      <div>
        <div className="gen-name">{name(r.id)}</div>
        <div className="gen-prod">
          {r.status === "retained" &&
            (changed ? (
              <>
                {trJoined(r.productFrom)} <span className="gen-arrow">→</span> {trJoined(r.productTo)}
              </>
            ) : (
              trJoined(r.productTo || r.productFrom)
            ))}
          {r.status === "gained" && (
            <>
              {trJoined(r.productTo)}
              {r.toChains.length > 0 && (
                <span className="gen-chains"> · {r.toChains.map(slugLabel).join(" · ")}</span>
              )}
            </>
          )}
          {r.status === "lost" && trJoined(r.productFrom)}
        </div>
      </div>
    </div>
  );
}

export default function Generations({ nodes, byId, onSelect }: Props) {
  useLang();
  const [sel, setSel] = useState(TRANSITIONS[0].key);

  const results = useMemo(
    () => new Map(TRANSITIONS.map((t) => [t.key, computeTransition(nodes, t)])),
    [nodes]
  );
  const cur = results.get(sel)!;

  const buckets: GenStatus[] = ["gained", "retained", "lost"];

  return (
    <div>
      <h3>🔀 {t("Generation Transitions")}</h3>
      <p className="caption">
        {t("Who keeps, gains, or loses a socket when an accelerator platform moves to its next generation — and how the content changes (HBM3E → HBM4, copper → optical, …). Computed from the curated chains; click a company for details.")}
      </p>

      <div className="gen-picker">
        {TRANSITIONS.map((tn) => {
          const r = results.get(tn.key)!;
          return (
            <button
              key={tn.key}
              className={"gen-pick" + (sel === tn.key ? " on" : "")}
              onClick={() => setSel(tn.key)}
            >
              <span className="gen-pick-vendor">{name(tn.vendor)}</span>
              <span className="gen-pick-label">{tn.short}</span>
              <span className="gen-pick-counts">
                <em className="g">📈{r.counts.gained}</em>
                <em className="r">✅{r.counts.retained}</em>
                <em className="l">⚠️{r.counts.lost}</em>
              </span>
            </button>
          );
        })}
      </div>

      <p className="caption" style={{ margin: "0.4rem 0 0.8rem" }}>
        <b style={{ color: "var(--ap-text)" }}>{t(cur.t.label)}</b> — {t("{n} companies across both generations.", { n: cur.rows.length })}
      </p>

      <div className="gen-grid">
        {buckets.map((st) => {
          const meta = STATUS_META[st];
          const rows = cur.rows.filter((r) => r.status === st);
          return (
            <div key={st} className={"gen-col " + meta.cls}>
              <div className="gen-col-head">
                {meta.icon} {t(meta.title)} ({rows.length})
              </div>
              <div className="gen-col-note">{t(meta.note)}</div>
              {rows.map((r) => (
                <RowLine key={r.id} r={r} byId={byId} onSelect={onSelect} />
              ))}
              {rows.length === 0 && <div className="gen-empty">{t("none")}</div>}
            </div>
          );
        })}
      </div>
    </div>
  );
}
