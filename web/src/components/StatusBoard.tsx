"use client";

import { useMemo, useState } from "react";
import type { VizNode } from "@/lib/types";
import { t, name as localName, useLang } from "@/lib/i18n";

// Status board — the market board enrich_status.py writes into graph/enrich_status.json
// (key "board"; the same content as ENRICH_STATUS.md in the repo). It answers the user's
// question "which enrich should I run next?": the ordered Run next list with the reasons,
// then per home market (US, Korea, Taiwan, Japan, Europe, China) what is current, overdue,
// never enriched or waiting. Company names open the node panel; commands copy for Claude Code.

export interface BoardMarket {
  id: string;
  name: string;
  command: string;
  companies: number;
  call_current: number;
  overdue: { company: string; last_call: string }[];
  never: string[];
  nothing: string[];
  dart_never: string[];
  marked: { company: string; source: string; why: string | null; recheck: string | null }[];
  feeds: number;
  waiting: Record<string, number>;
  collectors: Record<string, string | null>;
}

export interface Board {
  today: string;
  markets: BoardMarket[];
  next_actions: { command: string; reasons: string[] }[];
  setup: string[];
  // judgments left for the user (enrich_status.py ask), open until resolved
  questions?: { subject: string; question: string; label: string | null; at: string }[];
  shared: {
    ir: { last_sync: string | null; days: number | null; due: boolean; feeds?: number };
    conference: { last_sync: string | null; days: number | null; due: boolean };
  };
  verify_pending: number;
  notes: { at: string; market: string; text: string }[];
}

const WAITING_NAMES: Record<string, string> = {
  us: "call",
  intl: "call",
  tw: "call",
  dart: "DART filing",
  conference: "conference",
  ir: "IR release",
  kind: "IR deck",
  krcalls: "call",
};

const waitingText = (w: Record<string, number>) =>
  Object.entries(w)
    .sort()
    .map(([pid, n]) => `${n} ${WAITING_NAMES[pid] ? t(WAITING_NAMES[pid]) : pid}`)
    .join(", ");

export default function StatusBoard({
  board,
  generated,
  nodes,
  onSelect,
}: {
  board: Board;
  generated: string;
  nodes: VizNode[];
  onSelect: (n: VizNode) => void;
}) {
  // Chrome only: reasons, setup lines, questions and notes are operator text (English).
  useLang();
  const [copied, setCopied] = useState<string | null>(null);
  const byId = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes]);
  const due = useMemo(() => new Set(board.next_actions.map((a) => a.command)), [board]);

  const copy = (text: string) => {
    try {
      navigator.clipboard?.writeText(text);
      setCopied(text);
      setTimeout(() => setCopied((c) => (c === text ? null : c)), 1400);
    } catch {}
  };

  // A company name opens its node panel when the graph has it; otherwise plain text.
  const name = (id: string, suffix?: string) => {
    const node = byId.get(id);
    const label = suffix ? `${localName(id)} (${suffix})` : localName(id);
    return node ? (
      <button key={label} type="button" className="co-link board-name" onClick={() => onSelect(node)} title={t("Open {name}", { name: localName(id) })}>
        {label}
      </button>
    ) : (
      <span key={label} className="board-name">
        {label}
      </span>
    );
  };

  const markets = board.markets.filter((m) => m.companies > 0);

  return (
    <div className="board">
      <h4 className="board-h">{t("Run next")}</h4>
      {board.next_actions.length === 0 ? (
        <p className="caption">{t("Nothing is due. Every market is current and no queue holds work.")}</p>
      ) : (
        <ol className="board-run">
          {board.next_actions.map((a, i) => (
            <li key={a.command}>
              <div className="run-head">
                <span className="run-n">{i + 1}</span>
                <code className="run-cmd">{a.command}</code>
                <button type="button" className="copy-btn" title={t("Copy \"{cmd}\"", { cmd: a.command })} onClick={() => copy(a.command)}>
                  {copied === a.command ? "✓ " + t("copied") : "📋 " + t("Copy")}
                </button>
              </div>
              <ul>
                {a.reasons.map((r, j) => (
                  <li key={j}>{r}</li>
                ))}
              </ul>
            </li>
          ))}
        </ol>
      )}
      <p className="board-shared">
        {t("Shared collectors (every market command runs them first when due): IR feeds synced")}{" "}
        {board.shared.ir.last_sync || t("never")}
        {board.shared.ir.feeds != null && <> ({t("{n} feeds", { n: board.shared.ir.feeds })})</>}
        {board.shared.ir.due && <b className="warn"> · {t("due")}</b>}; {t("conference listing walked")}{" "}
        {board.shared.conference.last_sync || t("never")}
        {board.shared.conference.due && <b className="warn"> · {t("due")}</b>}.{" "}
        {t("Opus verification queue: {n} label(s) waiting (runs at 5+). Board generated {date}.", { n: board.verify_pending, date: generated })}
      </p>

      {(board.setup.length > 0 || (board.questions?.length ?? 0) > 0) && (
        <>
          <h4 className="board-h">{t("Needs a decision or setup")}</h4>
          <ul className="board-setup">
            {(board.questions || []).map((q) => (
              <li key={q.subject} className="board-question">
                <b>{t("Question")} — {q.subject}:</b> {q.question}
                {q.label && <span className="muted"> · {t("source")}: {q.label}</span>}
                <span className="muted"> · {t("asked {date}", { date: q.at })}</span>
              </li>
            ))}
            {board.setup.map((s, i) => (
              <li key={i}>{s}</li>
            ))}
          </ul>
        </>
      )}

      <h4 className="board-h">{t("Markets")}</h4>
      <div className="tbl-wrap">
        <table className="data board-markets">
          <thead>
            <tr>
              <th>{t("Market")}</th>
              <th>{t("Command")}</th>
              <th>{t("Companies")}</th>
              <th>{t("Call current")}</th>
              <th>{t("Overdue")}</th>
              <th>{t("Never had a call")}</th>
              <th>{t("No own data")}</th>
              <th>{t("Waiting")}</th>
              <th>{t("IR feeds")}</th>
              <th>{t("Collector last ran")}</th>
            </tr>
          </thead>
          <tbody>
            {markets.map((m) => {
              const waiting = Object.values(m.waiting).reduce((a, b) => a + b, 0);
              return (
                <tr key={m.id}>
                  <td data-label={t("Market")}>
                    <b>{m.id}</b> <span className="muted">{m.name}</span>
                  </td>
                  <td data-label={t("Command")} className="cmd">
                    <code>{m.command}</code>
                    {due.has(m.command) && <span className="board-due"> · {t("run")}</span>}
                  </td>
                  <td data-label={t("Companies")}>{m.companies}</td>
                  <td data-label={t("Call current")}>{m.call_current}</td>
                  <td data-label={t("Overdue")} className={m.overdue.length ? "warn" : ""}>
                    {m.overdue.length}
                  </td>
                  <td data-label={t("Never had a call")}>{m.never.length}</td>
                  <td data-label={t("No own data")}>{m.nothing.length}</td>
                  <td data-label={t("Waiting")} className={waiting ? "bad" : ""}>
                    {waiting}
                  </td>
                  <td data-label={t("IR feeds")}>{m.feeds}</td>
                  <td data-label={t("Collector last ran")} className="nowrap">
                    {Object.entries(m.collectors)
                      .map(([pid, d]) => `${pid} ${d || t("never")}`)
                      .join(" · ")}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="caption">
        {t("Call current = the latest own earnings call is within the company's usual gap + 3 weeks. No own data = not one entry from the company's own documents yet (new nodes land here). Companies marked \"no source exists\" are left out of Overdue / Never until their recheck date.")}
      </p>

      <h4 className="board-h">{t("Details by market")}</h4>
      {markets.map((m) => {
        const empty =
          !m.overdue.length && !m.never.length && !m.dart_never.length && !m.marked.length && !Object.keys(m.waiting).length;
        return (
          <details key={m.id} className="board-market" open={due.has(m.command)}>
            <summary>
              {m.id} — {m.name} <code>{m.command}</code>
            </summary>
            {empty ? (
              <p className="caption">{t("Nothing missing.")}</p>
            ) : (
              <dl>
                {Object.keys(m.waiting).length > 0 && (
                  <>
                    <dt>{t("Waiting to enrich")}</dt>
                    <dd>{waitingText(m.waiting)}</dd>
                  </>
                )}
                {m.overdue.length > 0 && (
                  <>
                    <dt>{t("Overdue for a call")}</dt>
                    <dd>{m.overdue.map((r) => name(r.company, t("last {date}", { date: r.last_call })))}</dd>
                  </>
                )}
                {m.never.length > 0 && m.id !== "KR" && (
                  <>
                    <dt>{t("Never had a call")}</dt>
                    <dd>{m.never.map((c) => name(c))}</dd>
                  </>
                )}
                {m.dart_never.length > 0 && (
                  <>
                    <dt>{t("No DART filing")}</dt>
                    <dd>{m.dart_never.map((c) => name(c))}</dd>
                  </>
                )}
                {m.marked.length > 0 && (
                  <>
                    <dt>{t("Known gaps")}</dt>
                    <dd>
                      {m.marked.map((x) => (
                        <span key={x.company + x.source} className="board-gap">
                          {name(x.company)} — {x.source}: {x.why}
                          {x.recheck && <span className="muted"> ({t("recheck {date}", { date: x.recheck })})</span>}
                        </span>
                      ))}
                    </dd>
                  </>
                )}
              </dl>
            )}
          </details>
        );
      })}

      {board.notes.length > 0 && (
        <>
          <h4 className="board-h">{t("Coordinator notes")}</h4>
          <ul className="board-notes">
            {board.notes.map((n, i) => (
              <li key={i}>
                <span className="muted">
                  {n.at} {n.market}
                </span>{" "}
                {n.text}
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
