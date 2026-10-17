"use client";

// LabMetricsSection.tsx — "AI lab metrics" in the company panel (2026-10-17).
//
// For the graph nodes that are AI labs (OpenAI, Anthropic …): the latest annualized
// revenue, funding rounds, compute / power deals, and the lab's models with their
// benchmark scores. Collected every night by a script into graph/ai_labs.json →
// /data/ai_labs.json. Only nodes that appear as a lab's `node_id` get the section.
// Not a signal: own file, own section. Every row links to its source.

import { useMemo, useState, type ReactNode } from "react";
import { t, useLang } from "@/lib/i18n";
import {
  fmtMoney,
  fmtScore,
  isRunRate,
  loadAiLabs,
  useFeed,
  type AiLabsFile,
  type Benchmark,
  type Lab,
  type LabModel,
} from "@/lib/companyFeeds";
import { DayChip, FeedHead, ShowAllToggle, SourceLink, previewRows } from "./FeedParts";

const byDateDesc = <T extends { date?: string | null }>(a: T, b: T) => (b.date || "").localeCompare(a.date || "");

// "1.2 GW" (one decimal at most).
const fmtGw = (gw: number) => gw.toLocaleString("en-US", { maximumFractionDigits: 1 }) + " GW";

// A lab's models: `models[].lab` names the lab by its id (or, in an older file, by
// its node id), so both are accepted, ignoring case.
function labModels(file: AiLabsFile, lab: Lab): LabModel[] {
  const keys = new Set([lab.id, lab.node_id].filter((s): s is string => !!s).map((s) => s.toLowerCase()));
  return (file.models || [])
    .filter((m) => keys.has((m.lab || "").toLowerCase()))
    .sort((a, b) => (b.release_date || "").localeCompare(a.release_date || ""));
}

// The benchmark columns that have at least one score for these models, in the file's
// order; a score id missing from `benchmarks` still gets a column, labelled by its id.
function benchColumns(file: AiLabsFile, models: LabModel[]): Benchmark[] {
  const used = new Set(models.flatMap((m) => Object.keys(m.scores || {})));
  const known = (file.benchmarks || []).filter((b) => used.has(b.id));
  const knownIds = new Set(known.map((b) => b.id));
  const extra = [...used].filter((id) => !knownIds.has(id)).sort().map((id) => ({ id, label: id, higher_is_better: true }));
  return [...known, ...extra];
}

function Stat({ k, v, sub }: { k: string; v: string; sub?: ReactNode }) {
  return (
    <div className="np-lab-stat">
      <div className="np-lab-stat-k">{k}</div>
      <div className="np-lab-stat-v">{v}</div>
      {sub && <div className="np-lab-stat-d">{sub}</div>}
    </div>
  );
}

function LabBlock({ lab, file, showName }: { lab: Lab; file: AiLabsFile; showName: boolean }) {
  // Which lists are opened with "Show all (N)": "revenue", "funding", "deals", "models".
  const [openSet, setOpenSet] = useState<Set<string>>(new Set());
  const isOpen = (k: string) => openSet.has(k);
  const toggle = (k: string) =>
    setOpenSet((prev) => {
      const next = new Set(prev);
      next.has(k) ? next.delete(k) : next.add(k);
      return next;
    });

  const revenue = useMemo(() => [...(lab.revenue || [])].sort(byDateDesc), [lab]);
  const funding = useMemo(() => [...(lab.funding || [])].sort(byDateDesc), [lab]);
  const deals = useMemo(() => [...(lab.deals || [])].sort(byDateDesc), [lab]);
  const models = useMemo(() => labModels(file, lab), [file, lab]);
  const benches = useMemo(() => benchColumns(file, models), [file, models]);
  // Best score per benchmark among this lab's models (bold in the table).
  const best = useMemo(() => {
    const m = new Map<string, number>();
    for (const b of benches) {
      const vals = models.map((x) => x.scores?.[b.id]).filter((v): v is number => typeof v === "number");
      if (vals.length > 1) m.set(b.id, b.higher_is_better ? Math.max(...vals) : Math.min(...vals));
    }
    return m;
  }, [benches, models]);

  // The headline is the newest run-rate / ARR point: a full-year total (same date, smaller number) is not an
  // annualized figure. Deals' GW are not added up: they overlap (a site can be part of a larger commitment).
  const rev = revenue.find((r) => isRunRate(r.type)) || revenue[0];
  const round = funding.find((f) => f.post_money_usd != null) || funding[0];

  if (!rev && !round && deals.length === 0 && models.length === 0) return null;

  return (
    <div className="np-lab">
      {showName && <div className="np-of-sub">{lab.id}</div>}

      {(rev || round || deals.length > 0) && (
        <div className="np-lab-stats">
          {rev && (
            <Stat
              k={t("Annualized revenue")}
              v={fmtMoney(rev.annualized_usd, "USD")}
              sub={
                <>
                  <DayChip iso={rev.date} />
                  {rev.type && <span className="np-src">{rev.type}</span>}
                  <SourceLink source={rev.source} url={rev.url} />
                </>
              }
            />
          )}
          {round && (
            <Stat
              k={t("Latest valuation")}
              v={round.post_money_usd != null ? fmtMoney(round.post_money_usd, "USD") : fmtMoney(round.amount_usd, "USD") || "—"}
              sub={
                <>
                  <DayChip iso={round.date} />
                  {round.round && <span className="np-src">{round.round}</span>}
                  <SourceLink source={round.source} url={round.url} />
                </>
              }
            />
          )}
          {deals.length > 0 && (
            <Stat
              k={t("Compute deals")}
              v={t(deals.length === 1 ? "{n} deal" : "{n} deals", { n: deals.length })}
            />
          )}
        </div>
      )}

      {revenue.length > 1 && (
        <div className="np-lab-list">
          {/* run-rate / ARR snapshots and full-year totals, each labelled with its type */}
          <div className="np-of-sub">{t("Revenue")}</div>
          {previewRows(revenue, isOpen("revenue")).map((r, i) => (
            <div className="np-fd-row np-sig-head" key={r.date + "|" + i}>
              <DayChip iso={r.date} />
              <b className="np-fd-amt">{fmtMoney(r.annualized_usd, "USD")}</b>
              {r.type && <span className="np-src">{r.type}</span>}
              <SourceLink source={r.source} url={r.url} />
            </div>
          ))}
          <ShowAllToggle total={revenue.length} open={isOpen("revenue")} onToggle={() => toggle("revenue")} />
        </div>
      )}

      {funding.length > 0 && (
        <div className="np-lab-list">
          <div className="np-of-sub">{t("Funding rounds")}</div>
          {previewRows(funding, isOpen("funding")).map((f, i) => (
            <div className="np-fd-row np-sig-head" key={f.date + "|" + f.round + "|" + i}>
              <DayChip iso={f.date} />
              <span className="np-fd-title">{f.round}</span>
              {f.amount_usd != null && <b className="np-fd-amt">{t("{amount} raised", { amount: fmtMoney(f.amount_usd, "USD") })}</b>}
              {f.post_money_usd != null && (
                <span className="np-src">{t("{amount} post-money", { amount: fmtMoney(f.post_money_usd, "USD") })}</span>
              )}
              <SourceLink source={f.source} url={f.url} />
            </div>
          ))}
          <ShowAllToggle total={funding.length} open={isOpen("funding")} onToggle={() => toggle("funding")} />
        </div>
      )}

      {deals.length > 0 && (
        <div className="np-lab-list">
          <div className="np-of-sub">{t("Deals")}</div>
          {previewRows(deals, isOpen("deals")).map((d, i) => (
            <div className="np-fd-row" key={d.date + "|" + d.counterparty + "|" + i}>
              <div className="np-sig-head">
                <DayChip iso={d.date} />
                <span className="np-fd-title">{d.counterparty}</span>
                {d.gw != null && <span className="np-tag">{fmtGw(d.gw)}</span>}
                {d.value_usd != null && <b className="np-fd-amt">{fmtMoney(d.value_usd, "USD")}</b>}
                <SourceLink source={d.source} url={d.url} />
              </div>
              {d.what && <div className="np-fd-detail">{d.what}</div>}
            </div>
          ))}
          <ShowAllToggle total={deals.length} open={isOpen("deals")} onToggle={() => toggle("deals")} />
        </div>
      )}

      {models.length > 0 && (
        <div className="np-lab-list">
          <div className="np-of-sub">{t("Models")}</div>
          <div className="np-tbl-wrap">
            <table className="np-tbl">
              <thead>
                <tr>
                  <th>{t("Model")}</th>
                  <th>{t("Released")}</th>
                  {benches.map((b) => (
                    <th
                      key={b.id}
                      className="num"
                      title={b.higher_is_better ? t("higher is better") : t("lower is better")}
                    >
                      {b.label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {previewRows(models, isOpen("models")).map((m, i) => (
                  <tr key={m.model + "|" + i}>
                    <td>
                      <div className="np-tbl-main">{m.model}</div>
                      <div className="np-tbl-sub">
                        <SourceLink source={m.source} url={m.url} />
                      </div>
                    </td>
                    <td>{m.release_date ? <DayChip iso={m.release_date} /> : "—"}</td>
                    {benches.map((b) => {
                      const v = m.scores?.[b.id];
                      const top = typeof v === "number" && best.get(b.id) === v;
                      return (
                        <td key={b.id} className={"num" + (top ? " np-tbl-best" : "")} title={top ? t("best among this lab's models") : undefined}>
                          {fmtScore(v)}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <ShowAllToggle total={models.length} open={isOpen("models")} onToggle={() => toggle("models")} />
        </div>
      )}
    </div>
  );
}

export default function LabMetricsSection({ companyId }: { companyId: string }) {
  useLang(); // re-render on a language change
  const file = useFeed(loadAiLabs);
  const labs = useMemo(() => (file?.labs || []).filter((l) => l.node_id === companyId), [file, companyId]);
  if (!file || labs.length === 0) return null;

  return (
    <section className="np-feed" aria-label={t("AI lab metrics")}>
      <FeedHead title={t("AI lab metrics")} updated={file.updated} />
      {/* Keyed by company + lab, so the lists start collapsed again for another company. */}
      {labs.map((lab) => (
        <LabBlock key={companyId + "|" + lab.id} lab={lab} file={file} showName={labs.length > 1} />
      ))}
      {file.attribution && <div className="np-fd-note">{file.attribution}</div>}
    </section>
  );
}
