"use client";

import { useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode } from "react";
import type { VizNode, VizLink } from "@/lib/types";
import {
  retrieveWithMeta,
  retrieveUnion,
  suggestQuestions,
  type Snippet,
  type RetrievalResult,
} from "@/lib/retrieval";
// The prompt module is plain JavaScript shared with the server routes and the
// local runner (tsconfig has allowJs); only its no-model helpers are used here.
import { guessIntent, normalizeIntent, LOCAL_MODEL_ID } from "@/lib/askPrompt.mjs";
import { t, name, useLang, type Lang } from "@/lib/i18n";
import { slugLabel } from "@/lib/taxonomy";
import { SignalBody, SourceBadge } from "./SignalText";
import "./AskGraph.css";

// AskGraph — the "Ask" tab. Type a question → three steps:
//   1. POST /api/ask/rewrite turns it into 2–4 search queries in the graph's
//      vocabulary plus an intent (lookup / compare / rank / timeline). If that
//      step is down or slow (8 s) the question alone is searched and the intent
//      is guessed locally — the step is a nice-to-have, never a blocker.
//   2. lib/retrieval.ts searches the graph IN THE BROWSER for the question and
//      every rewritten query and merges the results (retrieveUnion).
//   3. POST /api/ask streams the model's answer, which may only use those
//      snippets and must cite them as [n]. The local engine (`claude -p` on the
//      owner's machine, Opus at max effort) sends the whole answer in ONE line
//      after up to a minute of silence — hence the phase line with a counter.
// Each [n] renders as a chip that reveals the underlying snippet (company
// clickable → NodePanel), and "Context used" lists everything that was sent.
// The thread is a CONVERSATION: a follow-up question carries the last few
// completed Q&A pairs (history) to the rewrite step and to the model, so
// "what about Samsung?" is understood. The answer language follows the site's
// language switch (EN / 한국어 / 中文 / 日本語). Turns stay in component state only —
// nothing is persisted, nothing is sent except the question, the snippets, the
// intent, the language and the history.

type Status = "loading" | "streaming" | "done" | "error";
/** Sub-steps of "loading", shown as the phase line under the question. */
type Phase = "rewriting" | "reading" | "thinking";
// askPrompt.mjs declares Intent only as a JSDoc typedef, so TypeScript gets its own copy.
type Intent = "lookup" | "compare" | "rank" | "timeline";
/** Which back-end answered, as reported by the route's "done" line. */
type Engine = "local" | "groq" | "openai-compatible";
/** One earlier Q&A pair, as sent to the server for a follow-up question. */
interface HistoryTurn {
  question: string;
  answer: string;
}

interface Turn {
  id: number;
  question: string;
  lang: Lang; // the language this answer was requested in
  meta: RetrievalResult; // snippets + what the question parser recognised
  queries: string[]; // the rewritten queries that were ALSO searched ([] = none)
  intent: Intent;
  phase: Phase; // meaningful only while status === "loading"
  thinkingSince?: number; // Date.now() when /api/ask was called — drives "Thinking… 12 s"
  answer: string;
  status: Status;
  error?: string;
  model?: string; // the real model id ("claude-opus-5")
  effort?: string; // reasoning effort the engine ran at ("max", "low", …)
  engine?: Engine | string;
  latencyMs?: number; // the route's own measurement of how long the answer took
  citations?: number[]; // the [n] numbers the route found in the answer (stored, not rendered yet)
  usage?: { input_tokens: number; output_tokens: number };
  stopReason?: string | null;
}

const MAX_TURNS = 8; // turns kept on screen; older ones scroll off the top of the thread
const HISTORY_TURNS = 4; // completed turns sent along with a follow-up question …
const HISTORY_ANSWER_CHARS = 2000; // … each answer trimmed to this many characters
const REWRITE_TIMEOUT_MS = 8_000; // past this the rewrite step is skipped, not waited for
const SLOW_HINT_AFTER_S = 15; // seconds of "Thinking…" before the local-engine caption shows

const PHASE_LABEL: Record<Phase, string> = {
  rewriting: "Rewriting the question…",
  reading: "Reading the graph…",
  thinking: "Thinking…",
};

// Readable name for each engine the route can report (footer badge).
const ENGINE_LABEL: Record<string, string> = {
  groq: "Groq",
  "openai-compatible": "OpenAI-compatible",
};

export default function AskGraph({
  nodes,
  links,
  onOpen,
}: {
  nodes: VizNode[];
  links: VizLink[];
  onOpen: (id: string) => void;
}) {
  const [q, setQ] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState(false);
  const [setupNeeded, setSetupNeeded] = useState(false);
  // Answer language = the site language (lib/i18n.tsx, header switch).
  const { lang } = useLang();
  const ctrlRef = useRef<AbortController | null>(null);
  const nextId = useRef(1);

  const suggestions = useMemo(() => suggestQuestions(nodes), [nodes]);

  // Leaving the tab mid-answer: cancel the request instead of leaking it.
  useEffect(() => () => ctrlRef.current?.abort(), []);

  const patch = (id: number, fn: (t: Turn) => Turn) =>
    setTurns((ts) => ts.map((t) => (t.id === id ? fn(t) : t)));

  async function ask(raw: string) {
    const question = raw.trim();
    if (!question || busy) return;

    // 1) Create the turn at once. A first retrieval on the question alone fills
    //    the match row immediately; the union below replaces it a moment later.
    const id = nextId.current++;
    // The earlier completed turns of this thread — what makes a follow-up work.
    const history = historyFrom(turns);
    const turn: Turn = {
      id,
      question,
      lang,
      meta: retrieveWithMeta(question, nodes, links),
      queries: [],
      intent: guessIntent(question) as Intent,
      phase: "rewriting",
      answer: "",
      status: "loading",
    };
    // Oldest first, like a chat; the new turn is appended and scrolled into view.
    setTurns((ts) => [...ts, turn].slice(-MAX_TURNS));
    setQ("");
    scrollToTurn(id);

    // One AbortController per turn. ask() refuses to start while `busy`, so the
    // controller here is never the previous turn's; `finally` clears both.
    setBusy(true);
    const ctrl = new AbortController();
    ctrlRef.current = ctrl;
    try {
      // 2) Rewrite: extra search phrasings + the intent. Never throws — on any
      //    failure it returns no queries and a locally guessed intent.
      const { queries, intent } = await rewriteQuestion(question, history, ctrl.signal);
      if (ctrl.signal.aborted) return; // the tab was left / Clear was clicked meanwhile

      // 3) Retrieval on the union: the question first, then each rewritten query.
      const meta = retrieveUnion([question, ...queries], nodes, links);
      patch(id, (t) => ({ ...t, meta, intent, queries: meta.queries.slice(1), phase: "reading" }));

      // Nothing matched → say so locally; no point paying for a model call.
      if (meta.snippets.length === 0) {
        patch(id, (t) => ({ ...t, status: "done", answer: noMatchMessage(meta) }));
        return;
      }

      // 4) Ask the server route, which holds the API key (or forwards to the
      //    local runner), and stream the answer.
      patch(id, (t) => ({ ...t, phase: "thinking", thinkingSince: Date.now() }));
      const res = await fetch("/api/ask", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ question, snippets: meta.snippets, intent, lang, history }),
        signal: ctrl.signal,
      });
      if (!res.ok) {
        // Before the stream starts the route answers with JSON: 400 / 413 / 429 /
        // 502 / 504 {error}, 503 {error, code:"no_api_key"} (→ setup notice) or
        // 503 {error:"Ask is busy, try again", code:"busy"}. All show their text.
        const j: any = await res.json().catch(() => ({}));
        if (res.status === 503 && j?.code === "no_api_key") setSetupNeeded(true);
        throw new Error(j?.error || `Request failed (${res.status})`);
      }
      if (!res.body) throw new Error("The server sent an empty response.");

      // The route answers with one JSON object per line (NDJSON). An API engine
      // sends many small "text" lines; the local engine sends ONE with the whole answer.
      const handleLine = (line: string) => {
        let ev: any;
        try {
          ev = JSON.parse(line);
        } catch {
          return;
        }
        if (ev.type === "text") {
          patch(id, (t) => ({ ...t, status: "streaming", answer: t.answer + ev.text }));
        } else if (ev.type === "done") {
          patch(id, (t) => ({
            ...t,
            status: "done",
            model: ev.model,
            effort: typeof ev.effort === "string" ? ev.effort : undefined,
            engine: ev.engine,
            latencyMs: typeof ev.latency_ms === "number" ? ev.latency_ms : undefined,
            citations: Array.isArray(ev.citations) ? ev.citations : undefined,
            usage: ev.usage,
            stopReason: ev.stop_reason ?? null,
          }));
        } else if (ev.type === "error") {
          // Keep whatever text already arrived; only flag a hard error if there is none.
          patch(id, (t) => ({ ...t, status: t.answer ? "done" : "error", error: ev.error }));
        }
      };

      const reader = res.body.getReader();
      const dec = new TextDecoder();
      let buf = "";
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        let nl: number;
        while ((nl = buf.indexOf("\n")) >= 0) {
          const line = buf.slice(0, nl).trim();
          buf = buf.slice(nl + 1);
          if (line) handleLine(line);
        }
      }
      if (buf.trim()) handleLine(buf.trim());
      // A stream that ended without a "done" line still counts as finished.
      patch(id, (t) => (t.status === "done" || t.status === "error" ? t : { ...t, status: "done" }));
    } catch (e: any) {
      if (e?.name === "AbortError") return;
      patch(id, (t) => ({ ...t, status: "error", error: e?.message || String(e) }));
    } finally {
      if (ctrlRef.current === ctrl) ctrlRef.current = null;
      setBusy(false);
    }
  }

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    ask(q);
  };

  const inConversation = turns.length > 0;

  // The question box: above the suggestions for a fresh start, BELOW the thread
  // once a conversation is running (a follow-up is typed under the last answer).
  const form = (
    <form className={"ask-form" + (inConversation ? " ask-form-follow" : "")} onSubmit={onSubmit}>
      <input
        type="text"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder={inConversation ? t("Ask a follow-up…") : t("e.g. Who supplies HBM4 for NVIDIA Vera Rubin?")}
        maxLength={500}
        disabled={busy}
        aria-label={inConversation ? t("Your follow-up question") : t("Your question")}
        autoComplete="off"
      />
      <button type="submit" className="btn ask-send" disabled={busy || !q.trim()}>
        {busy ? t("Thinking…") : inConversation ? t("Follow up") : t("Ask")}
      </button>
    </form>
  );

  return (
    <div className="ask">
      <h3>💬 {t("Ask the Graph")}</h3>
      <p className="caption ask-intro">
        {t("Ask in English or Korean; the answer comes in the language picked at the top of the page. The answer is written only from the signals and contracts stored in this graph (transcript-grounded data) — every claim is cited to its source label, and when the graph does not contain the answer it says so. Follow-up questions see the earlier answers of the conversation.")}
      </p>

      {setupNeeded && <SetupNotice />}

      {!inConversation && form}

      {!inConversation && suggestions.length > 0 && (
        <div className="ask-chips" aria-label={t("Suggested questions")}>
          {/* The chip shows the question in the site language; the ENGLISH question is
              what gets asked (retrieval matches the graph's English vocabulary). */}
          {suggestions.map((s) => (
            <button key={s} type="button" className="ask-chip" disabled={busy} onClick={() => ask(s)}>
              {t(s)}
            </button>
          ))}
        </div>
      )}

      {inConversation && (
        <div className="ask-thread" aria-live="polite">
          <div className="ask-thread-head">
            <span className="caption">
              {t("Conversation · {n} of up to {max} turns — a follow-up sees the earlier answers. Kept only while this tab is open.", { n: turns.length, max: MAX_TURNS })}
            </span>
            <button
              type="button"
              className="copy-btn ask-clear"
              onClick={() => {
                ctrlRef.current?.abort();
                setTurns([]);
              }}
            >
              {t("New conversation")}
            </button>
          </div>
          {turns.map((t) => (
            <TurnView key={t.id} turn={t} onOpen={onOpen} />
          ))}
        </div>
      )}

      {inConversation && form}
    </div>
  );
}

// ── One question + its answer ──────────────────────────────────────────────

function TurnView({ turn, onOpen }: { turn: Turn; onOpen: (id: string) => void }) {
  useLang();
  const [active, setActive] = useState<number | null>(null); // which [n] chip is open
  const { snippets, companies, chains, topics } = turn.meta;
  const activeSnippet = active !== null ? snippets[active - 1] : undefined;
  // "Thinking… 12 s" counts from the moment /api/ask was called (the local
  // engine can take a minute) and stops when the turn finishes or the card unmounts.
  const thinking = turn.status === "loading" && turn.phase === "thinking";
  const seconds = useElapsedSeconds(turn.thinkingSince, thinking);

  const matched: ReactNode[] = [];
  if (companies.length) matched.push(<span key="c"><b>{companies.map(name).join(", ")}</b></span>);
  if (chains.length) matched.push(<span key="ch">{t("chains:")} {chains.map(slugLabel).join(", ")}</span>);
  if (topics.length) matched.push(<span key="t">{t("topics:")} {topics.map(slugLabel).join(", ")}</span>);

  return (
    <article className="ask-turn" id={`ask-turn-${turn.id}`}>
      <p className="ask-q">{turn.question}</p>
      <div className="ask-match">
        {t(snippets.length === 1 ? "{n} snippet matched" : "{n} snippets matched", { n: snippets.length })}
        {matched.length > 0 && <> · </>}
        {matched.map((m, i) => (
          <span key={i}>
            {i > 0 && " · "}
            {m}
          </span>
        ))}
        {turn.queries.length > 0 && (
          <div className="ask-queries">
            {t("intent:")} {t(turn.intent)} · {t("searched:")} {turn.queries.join(" · ")}
          </div>
        )}
      </div>

      {turn.status === "loading" && (
        <div className="ask-thinking">
          <span className="ask-phase">
            {t(PHASE_LABEL[turn.phase])}
            {/* aria-hidden: the thread is an aria-live region — announce the phase once, not every second */}
            {thinking && <span aria-hidden="true"> {seconds} s</span>}
          </span>
          {thinking && seconds >= SLOW_HINT_AFTER_S && (
            <div className="ask-hint">
              {t("The local engine (Opus, max effort) takes 15–60 s for most questions and up to a few minutes for a ranking in Korean.")}
            </div>
          )}
        </div>
      )}

      {turn.answer && (
        <div className="ask-a">
          <AnswerBody
            text={turn.answer}
            count={snippets.length}
            active={active}
            onCite={(n) => setActive(active === n ? null : n)}
            streaming={turn.status === "streaming"}
          />
        </div>
      )}

      {turn.error && <div className="ask-err">⚠ {turn.error}</div>}

      {activeSnippet && (
        <SnippetView s={activeSnippet} n={active as number} onOpen={onOpen} highlight />
      )}

      {(turn.status === "done" || turn.status === "error") && (
        <div className="ask-foot">
          {(turn.model || turn.engine) && (
            <span>
              {modelBadge(turn)}
              {turn.latencyMs !== undefined && <> · {(turn.latencyMs / 1000).toFixed(1)} s</>}
              {/* Some OpenAI-compatible streams send no usage — then just name the model. */}
              {turn.usage && turn.usage.input_tokens + turn.usage.output_tokens > 0 && (
                <>
                  {" "}· {t("{in} in / {out} out tokens", { in: turn.usage.input_tokens.toLocaleString(), out: turn.usage.output_tokens.toLocaleString() })}
                </>
              )}
            </span>
          )}
          {turn.stopReason === "max_tokens" && <span>· {t("answer cut at the token limit")}</span>}
          {turn.stopReason === "refusal" && <span>· {t("the model declined to answer this")}</span>}
        </div>
      )}

      {snippets.length > 0 && (
        <details className="ask-context">
          <summary>{t("Context used — {n} snippets sent to the model", { n: snippets.length })}</summary>
          <ol>
            {snippets.map((s, i) => (
              <li key={i}>
                <SnippetView s={s} n={i + 1} onOpen={onOpen} clamp />
              </li>
            ))}
          </ol>
        </details>
      )}
    </article>
  );
}

// ── One snippet (used for the open citation and the context list) ──────────

function SnippetView({
  s,
  n,
  onOpen,
  highlight,
  clamp,
}: {
  s: Snippet;
  n: number;
  onOpen: (id: string) => void;
  highlight?: boolean;
  clamp?: boolean;
}) {
  return (
    <div className={"ask-snip" + (highlight ? " on" : "")}>
      <div className="ask-snip-head">
        <span className="ask-n">[{n}]</span>
        <span className={"ask-kind " + s.kind}>{t(s.kind)}</span>
        <button type="button" className="ask-co" onClick={() => onOpen(s.company)} title={t("Open {name}", { name: name(s.company) })}>
          {name(s.company)}
        </button>
        {s.target && (
          <>
            <span>→</span>
            <button type="button" className="ask-co" onClick={() => onOpen(s.target!)} title={t("Open {name}", { name: name(s.target) })}>
              {name(s.target)}
            </button>
          </>
        )}
        {s.chain && <span className="ask-chain">· {slugLabel(s.chain)}</span>}
        <span className="ask-label">
          · <SourceBadge label={s.label} /> {s.label}
        </span>
      </div>
      {/* The open citation shows the whole snippet; the "Context used" list
          clamps each one to two lines with a More toggle. */}
      {clamp ? (
        <div className="ask-snip-text">
          <SignalBody text={s.text} />
        </div>
      ) : (
        <div className="ask-snip-text">{s.text}</div>
      )}
    </div>
  );
}

// ── Answer rendering: paragraphs, "- " bullets, "1." lists, **bold**, [n] chips, sections ──

// [3]  [2, 5]  [2-4]  — one or more snippet numbers inside square brackets.
const INLINE_RE = /(\*\*[^*]+\*\*|\[\d{1,2}(?:\s*[,\-–]\s*\d{1,2})*\])/g;
// "1. text" / "2) text" — a numbered-list item.
const NUMBERED_RE = /^(\d{1,2})[.)]\s+(.*)$/;
// The three sections the answer prompt asks for, at the start of a paragraph or
// list item, with or without ** ** around them: "Best answer:", "**Evidence:**",
// "**Gaps**:" — and their Korean / Chinese / Japanese labels (askPrompt.mjs
// LANGUAGE_RULES). A full-width colon "：" is accepted too.
const SECTION_RE = /^(?:\*\*)?(Best answer|Evidence|Gaps|답변|근거|빈틈|答案|依据|缺口|回答|根拠|不足)(?:\*\*)?[:：](?:\*\*)?\s*(.*)$/i;

/** "2, 4-6" → [2, 4, 5, 6], keeping only numbers that exist in the context list. */
function citeNumbers(inner: string, count: number): number[] {
  const out: number[] = [];
  for (const part of inner.split(",")) {
    const range = /^\s*(\d{1,2})\s*[-–]\s*(\d{1,2})\s*$/.exec(part);
    if (range) {
      const a = +range[1];
      const b = +range[2];
      if (b >= a && b - a < 10) for (let x = a; x <= b; x++) out.push(x);
    } else {
      const x = parseInt(part, 10);
      if (!isNaN(x)) out.push(x);
    }
  }
  return out.filter((x) => x >= 1 && x <= count);
}

function AnswerBody({
  text,
  count,
  active,
  onCite,
  streaming,
}: {
  text: string;
  count: number;
  active: number | null;
  onCite: (n: number) => void;
  streaming: boolean;
}) {
  // Inline pass: bold and citations. `key` seeds keep React keys unique per block.
  const inline = (s: string, key: string): ReactNode[] =>
    s.split(INLINE_RE).map((part, i) => {
      if (!part) return null;
      if (part.startsWith("**") && part.endsWith("**"))
        return <strong key={key + i}>{inline(part.slice(2, -2), key + i + "b")}</strong>;
      if (part.startsWith("[")) {
        const nums = citeNumbers(part.slice(1, -1), count);
        if (!nums.length) return <span key={key + i}>{part}</span>; // not a valid citation
        return (
          <span key={key + i} className="ask-cites">
            {nums.map((n) => (
              <button
                key={n}
                type="button"
                className={"ask-cite" + (active === n ? " on" : "")}
                onClick={() => onCite(n)}
                title={t("Show snippet {n}", { n })}
              >
                {n}
              </button>
            ))}
          </span>
        );
      }
      return <span key={key + i}>{part}</span>;
    });

  // A whole paragraph / list item: a leading section label becomes
  // <b class="ask-section">, the rest goes through the inline pass.
  const block = (s: string, key: string): ReactNode[] => {
    const m = SECTION_RE.exec(s);
    if (!m) return inline(s, key);
    const label = (
      <b key={key + "s"} className="ask-section">
        {m[1]}:
      </b>
    );
    return m[2] ? [label, " ", ...inline(m[2], key)] : [label];
  };

  // Block pass: blank line = paragraph break; consecutive "- " lines = one
  // bullet list; consecutive "1." / "2)" lines = one numbered list.
  const blocks: ReactNode[] = [];
  let list: { tag: "ul" | "ol"; start: number; items: string[] } | null = null;
  const flush = () => {
    if (!list) return;
    const k = list.tag + blocks.length;
    const items = list.items.map((li, i) => <li key={i}>{block(li, k + i)}</li>);
    blocks.push(
      list.tag === "ol" ? (
        <ol key={k} start={list.start}>
          {items}
        </ol>
      ) : (
        <ul key={k}>{items}</ul>
      )
    );
    list = null;
  };
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    if (!line) {
      flush();
      continue;
    }
    const bullet = /^[-•*]\s+(.*)$/.exec(line);
    const numbered = bullet ? null : NUMBERED_RE.exec(line);
    const item = bullet
      ? { tag: "ul" as const, text: bullet[1], start: 1 }
      : numbered
        ? { tag: "ol" as const, text: numbered[2], start: +numbered[1] }
        : null;
    if (item) {
      // A bullet right after a numbered item (or the reverse) starts a new list.
      if (!list || list.tag !== item.tag) {
        flush();
        list = { tag: item.tag, start: item.start, items: [] };
      }
      list.items.push(item.text);
      continue;
    }
    flush();
    const k = "p" + blocks.length;
    blocks.push(<p key={k}>{block(line.replace(/^#+\s*/, ""), k)}</p>);
  }
  flush();

  return (
    <>
      {blocks}
      {streaming && <span className="ask-cursor" aria-hidden="true" />}
    </>
  );
}

// ── Helpers ────────────────────────────────────────────────────────────────

/**
 * Step 2 — POST /api/ask/rewrite: extra search queries (0–4) and the intent.
 * The step is optional, so this NEVER throws: a non-200 answer (429 rate limit,
 * 503 no key, 400), a network error, a malformed body or the 8 s timeout all
 * fall back to "no extra queries + guess the intent locally", and the turn
 * carries on with the original question alone.
 */
async function rewriteQuestion(
  question: string,
  history: HistoryTurn[],
  turnSignal: AbortSignal
): Promise<{ queries: string[]; intent: Intent }> {
  const fallback = { queries: [] as string[], intent: guessIntent(question) as Intent };
  try {
    const res = await fetch("/api/ask/rewrite", {
      method: "POST",
      headers: { "content-type": "application/json" },
      // The earlier questions let the model turn "what about Samsung?" into a standalone query.
      body: JSON.stringify({ question, history }),
      signal: withTimeout(turnSignal, REWRITE_TIMEOUT_MS),
    });
    if (!res.ok) return fallback;
    const j: any = await res.json();
    const queries: string[] = (Array.isArray(j?.queries) ? j.queries : [])
      .filter((x: unknown): x is string => typeof x === "string" && x.trim() !== "")
      .slice(0, 4);
    // The route always sends an intent; anything unexpected becomes "lookup".
    return { queries, intent: normalizeIntent(j?.intent ?? fallback.intent) as Intent };
  } catch {
    return fallback; // timeout, offline, aborted, bad JSON — all the same: go on without rewrites
  }
}

/**
 * A signal that fires when the turn is cancelled OR after `ms`, whichever comes
 * first. AbortSignal.any() (Chrome 116+, Safari 17.4+, Firefox 124+) merges the
 * two; older browsers get the timeout alone — ask() re-checks the turn's own
 * signal right after the call, so a cancelled turn still stops there.
 */
function withTimeout(turnSignal: AbortSignal, ms: number): AbortSignal {
  const timeout = AbortSignal.timeout(ms);
  return typeof AbortSignal.any === "function" ? AbortSignal.any([turnSignal, timeout]) : timeout;
}

/**
 * Seconds elapsed since `since`, re-rendered once a second while `active`.
 * The interval is cleared when the turn finishes (active → false) or the card
 * unmounts (Clear, leaving the tab).
 */
function useElapsedSeconds(since: number | undefined, active: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active || since === undefined) return;
    setNow(Date.now());
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [active, since]);
  return since === undefined ? 0 : Math.max(0, Math.floor((now - since) / 1000));
}

/**
 * Footer badge: "<model> · effort <effort> · <where it ran>", e.g.
 * "claude-opus-5 · effort max · your machine" or "llama-3.3-70b-versatile · effort default · Groq".
 * Kept generic on purpose: other models will be mixed in later.
 */
function modelBadge(turn: Turn): string {
  const parts: string[] = [turn.model || (turn.engine === "local" ? LOCAL_MODEL_ID : "model")];
  if (turn.effort && turn.effort !== "default") parts.push(t("effort {e}", { e: turn.effort }));
  if (turn.engine === "local") parts.push(t("your machine"));
  else if (turn.engine) parts.push(ENGINE_LABEL[turn.engine] || turn.engine);
  return parts.join(" · ");
}

/**
 * The completed turns of the thread, oldest first, as the server wants them:
 * only turns a model actually answered (the local "nothing matched" message has
 * no model), the last HISTORY_TURNS of them, answers trimmed.
 */
function historyFrom(turns: Turn[]): HistoryTurn[] {
  const done = turns.filter((t) => t.status === "done" && t.answer && t.model);
  return done.slice(-HISTORY_TURNS).map((t) => ({
    question: t.question,
    answer: t.answer.slice(0, HISTORY_ANSWER_CHARS),
  }));
}

/** Bring a freshly added turn into view (it is rendered after this tick). */
function scrollToTurn(id: number) {
  setTimeout(() => {
    document.getElementById(`ask-turn-${id}`)?.scrollIntoView({ block: "start", behavior: "smooth" });
  }, 50);
}

function noMatchMessage(meta: RetrievalResult): string {
  if (meta.companies.length)
    return t(
      "The graph has a node for {names} but no stored signals or contracts matched this question, so there is nothing to answer from yet. Enrich its latest earnings call or filing to fill this in.",
      { names: meta.companies.map(name).join(", ") }
    );
  return t(
    "No stored signal or contract matched this question, so there is nothing to answer from. Try naming a company (SK Hynix, TSMC, Vertiv…) or a product generation (Vera Rubin, B200, MI450 Helios, TPU v8, Trainium3), or a topic like HBM, CoWoS, CPO or transformers."
  );
}

function SetupNotice() {
  return (
    <div className="ask-setup" role="status">
      <b>{t("Ask the Graph has no answer engine configured yet.")}</b>
      <ol>
        <li>
          <b>Default (Claude Opus on your own machine):</b> run the local runner (see{" "}
          <code>local-ask/README.md</code>) and set <code>LOCAL_ASK_URL</code> +{" "}
          <code>ASK_SHARED_SECRET</code> on Vercel.
        </li>
        <li>
          <b>Optional fallback for when the PC is off:</b> any OpenAI-compatible service via{" "}
          <code>ASK_BASE_URL</code> + <code>ASK_API_KEY</code>, or Groq at <code>console.groq.com</code>{" "}
          → <code>GROQ_API_KEY</code> (free tier). <code>ASK_MODEL</code> pins a model name.
        </li>
        <li>
          On Vercel: open the project → <b>Settings → Environment Variables</b> → add the variable
          for Production and Preview → <b>Deployments → Redeploy</b>. Locally: put the same line in{" "}
          <code>web/.env</code> (already git-ignored) and restart <code>npm run dev</code>.
        </li>
      </ol>
      The key never leaves the server — the browser only sends the question and the snippets.
      Every other tab works without it.
    </div>
  );
}
