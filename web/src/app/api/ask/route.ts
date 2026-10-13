// /api/ask — "Ask the Graph", the answer step.
//
// By the time a request lands here the browser has already (1) asked
// /api/ask/rewrite for 2–4 search queries plus an intent and (2) run
// lib/retrieval.ts over the union of those queries and the original question.
// It sends the question, the snippets it picked and the intent:
//
//   POST { question, snippets: Snippet[], intent?: "lookup"|"compare"|"rank"|"timeline",
//          lang?: "en"|"ko", history?: [{question, answer}, …] }
//   (`history` = the earlier turns of the same thread, so follow-ups work;
//    `lang` = the answer language the user picked)
//
// and receives newline-delimited JSON (NDJSON), one object per line:
//   {"type":"text","text":"..."}      answer fragments in order
//   {"type":"step","tool":"open_company"|"search_facts","target":"…","facts":n}
//                                     Claude chose to look further (one line per lookup)
//   {"type":"facts","snippets":[…]}   facts a lookup numbered after the snippets, in order
//   {"type":"done","model":"claude-opus-5-5"|…,"effort":"xhigh"|"default",
//                  "engine":"anthropic"|"groq"|"openai-compatible",
//                  "latency_ms":n,"citations":[n,…],"usage":{…},"stop_reason":"…",
//                  "lookups":n}       once, last
//   {"type":"error","error":"..."}    only if an upstream stream breaks mid-way
// Before anything is streamed, problems come back as plain JSON with a real
// HTTP status: 400 bad input, 413 too big, 429 rate limit (10 per minute per
// IP), 503 {code:"no_api_key"} nothing is configured, 503 {code:"busy"} every
// engine failed after retries, 502 / 504 for API failures a retry cannot fix.
//
// Two answer engines, tried in order:
//   1. CLAUDE — the Claude API (ANTHROPIC_API_KEY): Claude Opus 5.5 with
//      adaptive thinking at effort "xhigh", streamed. Since 2026-10-12 it
//      replaces the owner's local runner (local-ask/), so the site no longer
//      depends on the PC being on. Claude also gets a map of every company,
//      graph lookups (a company two hops out, one company, keyword search —
//      lib/askAgent.ts) and web search, and decides by itself how far to look —
//      at most MAX_LOOKUP_ROUNDS rounds. The SDK retries 429 / 5xx / 529 by itself,
//      and a safety-classifier refusal is re-run server-side on the fallback
//      model Anthropic recommends. If Claude fails BEFORE anything is streamed
//      and engine 2 is configured, the question quietly goes there instead.
//   2. API — optional: any OpenAI-compatible service (ASK_BASE_URL + ASK_API_KEY)
//      / Groq (GROQ_API_KEY); ASK_MODEL pins a model name. Free tiers answer 429
//      and 503 often, so the call is retried with exponential backoff (1 s, 2 s,
//      4 s + jitter), alternating between the best models the service lists.
// Both engines get the SAME prompt from lib/askPrompt.mjs, so their answers
// differ only by model, never by instructions.
//
// Why a server route at all? The model API key must never reach the browser.
// It lives only in environment variables (Vercel → Settings → Environment
// Variables, or web/.env — git-ignored — when running locally).

import Anthropic from "@anthropic-ai/sdk";
import type { BetaMessageStream } from "@anthropic-ai/sdk/lib/BetaMessageStream";
import type {
  BetaContentBlock,
  BetaMessageParam,
  BetaTextBlockParam,
  BetaToolResultBlockParam,
  BetaToolUseBlock,
} from "@anthropic-ai/sdk/resources/beta/messages/messages";
import { NextRequest, NextResponse } from "next/server";
import {
  normalizeIntent,
  normalizeLang,
  normalizeHistory,
  buildSystemPrompt,
  buildUserMessage,
  extractCitations,
  LOOKUP_RULES,
} from "@/lib/askPrompt.mjs";
import {
  ASK_TOOLS,
  WEB_TOOLS,
  FactBook,
  companyMapBlock,
  runLookup,
  webStepOf,
  webSourcesOf,
} from "@/lib/askAgent";
import {
  CLAUDE_MODEL,
  CLAUDE_REFUSAL_FALLBACK,
  claudeClient,
  type Provider,
  resolveProvider,
  pickModels,
  buildChatRequest,
  RETRYABLE_STATUSES,
  backoffMs,
  sleep,
  isTimeout,
  makeDeadline,
  rateLimited,
  clientIp,
} from "@/lib/askProvider";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// ── Timing budget ──────────────────────────────────────────────────────────
// Vercel kills the function after `maxDuration` seconds (Next.js needs a
// literal here). With Fluid compute — on by default — the Hobby plan allows up
// to 300 s; without it only 60 s. If a deploy ever fails on this line, change
// the number to 60: every timeout below is DERIVED from it, so the route keeps
// working with a shorter wait instead of breaking.
export const maxDuration = 300;

const BUDGET_MS = (maxDuration - 10) * 1000; // leave 10 s of headroom before Vercel's cut-off

// Claude: it thinks first (hidden), then the answer streams. The owner's
// default is "xhigh" (2026-10-12) — one step below "max"; Opus 5.5's own
// default is "medium".
const CLAUDE_EFFORT = "xhigh";
// Hidden thinking counts against this limit too. 64k leaves xhigh all the room
// it wants to think over a large context plus a long answer (owner: quality
// first); it caps the output cost of one round at about $1.28 (Opus 5.5: $20
// per million output tokens) — real rounds use a fraction of it.
const CLAUDE_MAX_TOKENS = 64_000;
// Looking further (lib/askAgent.ts): Claude may spend at most this many rounds
// on lookups; the round after that must answer (tool_choice "none"). The same
// happens once less than ANSWER_RESERVE_MS of the budget is left — an xhigh
// answer still needs time to think and write.
const MAX_LOOKUP_ROUNDS = 3;
const ANSWER_RESERVE_MS = 120_000;

const API_FETCH_TIMEOUT_MS = 60_000; // one API call, including reading the stream
const API_MAX_RETRIES = 3; // after the first attempt: waits of 1 s, 2 s, 4 s (+ jitter)
const API_MIN_ATTEMPT_MS = 8_000; // do not start an attempt with less than this left

// Output budget: three sections (answer / evidence / gaps) can run to ~1,000
// tokens, and on "thinking" models the hidden reasoning counts against the
// same limit — with 1,500 a
// ranking question came back empty, cut at the limit before any visible text.
const MAX_TOKENS = 4000;

// ── Request limits (the browser sends ≤60k chars of snippets + ≤16k of history; these are ceilings) ──
const MAX_BODY_BYTES = 400_000;
const MAX_QUESTION_CHARS = 500;
const MAX_SNIPPETS = 150;
const MAX_SNIPPET_TEXT = 4_000; // a signal (≤2,000) plus its figure
const MAX_TOTAL_TEXT = 80_000;
const MAX_FIELD = 160; // company / target / chain / label / date

// Rate limit: 10 questions per minute per IP (see askProvider.ts for the caveat).
const RATE_LIMIT = 10;
const RATE_WINDOW_MS = 60_000;

// ── Input validation ───────────────────────────────────────────────────────

interface InSnippet {
  kind: "signal" | "contract";
  company: string;
  target?: string;
  chain: string;
  label: string;
  date: string;
  text: string;
  topics?: string[];
}

interface AskBody {
  question: string;
  snippets: InSnippet[];
  intent: string;
  lang: string; // "en" | "ko" | "zh" | "ja"
  history: { question: string; answer: string }[]; // earlier turns of the thread, oldest first
}

const str = (v: unknown, max: number): string | null =>
  typeof v === "string" && v.length <= max ? v : null;

/** Returns the cleaned body, or a string describing what is wrong with it. */
function parseBody(raw: unknown): AskBody | string {
  if (!raw || typeof raw !== "object") return "Body must be a JSON object.";
  const b = raw as Record<string, unknown>;

  const question = typeof b.question === "string" ? b.question.trim() : "";
  if (!question) return "Missing 'question'.";
  if (question.length > MAX_QUESTION_CHARS)
    return `Question is too long (max ${MAX_QUESTION_CHARS} characters).`;

  if (!Array.isArray(b.snippets)) return "Missing 'snippets' array.";
  if (b.snippets.length > MAX_SNIPPETS) return `Too many snippets (max ${MAX_SNIPPETS}).`;

  const snippets: InSnippet[] = [];
  let total = 0;
  for (const s of b.snippets as unknown[]) {
    if (!s || typeof s !== "object") return "Each snippet must be an object.";
    const o = s as Record<string, unknown>;
    const kind = o.kind === "signal" || o.kind === "contract" ? o.kind : null;
    const company = str(o.company, MAX_FIELD);
    const chain = str(o.chain, MAX_FIELD);
    const label = str(o.label, MAX_FIELD);
    const date = str(o.date, 20);
    const text = str(o.text, MAX_SNIPPET_TEXT);
    if (!kind || company === null || chain === null || label === null || date === null || text === null)
      return "A snippet has a missing or oversized field.";
    const target = o.target === undefined ? undefined : str(o.target, MAX_FIELD);
    if (target === null) return "A snippet has an invalid 'target'.";
    const topics = Array.isArray(o.topics)
      ? (o.topics as unknown[]).filter((t): t is string => typeof t === "string").slice(0, 10)
      : undefined;
    total += text.length;
    if (total > MAX_TOTAL_TEXT) return `Snippet text exceeds ${MAX_TOTAL_TEXT} characters in total.`;
    snippets.push({ kind, company, target, chain, label, date, text, topics });
  }
  // Unknown or missing intent simply means "lookup"; unknown language means English;
  // the history is trimmed to the last few complete turns (see askPrompt.mjs).
  return {
    question,
    snippets,
    intent: normalizeIntent(b.intent),
    lang: normalizeLang(b.lang),
    history: normalizeHistory(b.history),
  };
}

// ── NDJSON helpers ─────────────────────────────────────────────────────────

const NDJSON_HEADERS = {
  "content-type": "application/x-ndjson; charset=utf-8",
  "cache-control": "no-store",
  "x-accel-buffering": "no", // tell proxies not to buffer the stream
};

interface Usage {
  input_tokens: number;
  output_tokens: number;
}

/** The last line of every answer stream, in one place so both engines agree on its shape. */
function doneLine(o: {
  model: string;
  effort: string; // "xhigh" (Claude), "default" (OpenAI-compatible API)
  engine: string;
  startedAt: number;
  citations: number[];
  usage: Usage;
  stopReason: string | null;
  lookups?: number; // Claude only: how many lookups it decided to make (0 = the snippets were enough)
}) {
  return {
    type: "done",
    model: o.model,
    effort: o.effort,
    engine: o.engine,
    latency_ms: Date.now() - o.startedAt,
    citations: o.citations,
    usage: o.usage,
    stop_reason: o.stopReason,
    lookups: o.lookups ?? 0,
  };
}

// ── Engine 1: the Claude API ───────────────────────────────────────────────

type Deadline = ReturnType<typeof makeDeadline>;

/** Why an engine could not answer, in the route's error shape. Never echoes the key. */
interface EngineError {
  status: number;
  error: string;
  upstream_status?: number;
}

/** Everything one Claude answer needs across its rounds (a round = one API call). */
interface AgentRun {
  client: Anthropic;
  system: BetaTextBlockParam[];
  /** The conversation so far — grows by one assistant + one tool-result message per lookup round. */
  messages: BetaMessageParam[];
  /** False when the graph could not be loaded: then no map, no tools — snippets only. */
  lookups: boolean;
  /** Web search on (turned off for the request if the API says it is not enabled). */
  web: boolean;
  book: FactBook;
  deadline: Deadline;
}

/** One API call. Past the round / time limits the call gets tool_choice "none": answer now. */
function startRound(run: AgentRun, round: number): BetaMessageStream {
  const mustAnswer = round >= MAX_LOOKUP_ROUNDS || run.deadline.remaining() < ANSWER_RESERVE_MS;
  return run.client.beta.messages.stream(
    {
      model: CLAUDE_MODEL,
      max_tokens: CLAUDE_MAX_TOKENS,
      thinking: { type: "adaptive" },
      output_config: { effort: CLAUDE_EFFORT },
      system: run.system,
      ...(run.lookups
        ? {
            tools: run.web ? [...ASK_TOOLS, ...WEB_TOOLS] : ASK_TOOLS,
            tool_choice: { type: mustAnswer ? "none" : "auto" } as const,
          }
        : {}),
      messages: run.messages,
      // Also cache the conversation so far, so the next round re-reads it cheaply.
      cache_control: { type: "ephemeral" },
      ...CLAUDE_REFUSAL_FALLBACK,
    },
    // Bounds the whole call: the SDK's retries and the streamed answer included.
    { signal: AbortSignal.timeout(Math.max(1, run.deadline.remaining())) }
  );
}

/**
 * Ask Claude. Returns the NDJSON answer stream once the API has ACCEPTED the
 * first call — or, if it refused before anything was streamed (bad key, outage
 * after the SDK's own retries, our deadline), the error to report instead.
 */
async function askClaude(
  client: Anthropic,
  system: string,
  user: string,
  snippets: InSnippet[],
  deadline: Deadline
): Promise<{ ok: true; body: ReadableStream<Uint8Array> } | ({ ok: false } & EngineError)> {
  // The company map comes from the graph file; if it cannot be read, answer
  // from the snippets alone (the behaviour before lookups existed).
  let map: BetaTextBlockParam | null = null;
  try {
    map = companyMapBlock();
  } catch (e: any) {
    console.warn(`[ask] company map unavailable, answering from the snippets only: ${e?.message || e}`);
  }
  const run: AgentRun = {
    client,
    system: map ? [map, { type: "text", text: `${system}\n\n${LOOKUP_RULES}` }] : [{ type: "text", text: system }],
    messages: [{ role: "user", content: user }],
    lookups: map !== null,
    web: map !== null,
    book: new FactBook(snippets),
    deadline,
  };
  for (;;) {
    const first = startRound(run, 0);
    // Build the NDJSON stream FIRST: it subscribes to the answer text at once,
    // so no fragment can arrive before anyone is listening.
    const body = agentToNdjson(run, first);
    try {
      await first.withResponse(); // resolves when Claude accepts the request; throws on 4xx / 5xx
      return { ok: true, body };
    } catch (e) {
      body.cancel().catch(() => {});
      // Web search / fetch must be enabled for the organisation in the Claude
      // Console; if they are not, answer without them rather than not at all.
      if (run.web && e instanceof Anthropic.BadRequestError && /web.?(search|fetch)/i.test(e.message)) {
        console.warn(`[ask] web tools unavailable, answering without them: ${e.message}`);
        run.web = false;
        continue;
      }
      return { ok: false, ...claudeError(e) };
    }
  }
}

/** A Claude API failure as the status + message the browser should see (most specific class first). */
function claudeError(e: unknown): EngineError {
  if (e instanceof Anthropic.AuthenticationError || e instanceof Anthropic.PermissionDeniedError)
    return {
      status: 502,
      upstream_status: e.status,
      error: `The Claude API rejected the server's API key (${e.status}). Check ANTHROPIC_API_KEY in Vercel → Settings → Environment Variables and redeploy.`,
    };
  // Rate limit, overload (529) or an outage: the SDK has already retried twice.
  if (e instanceof Anthropic.RateLimitError || e instanceof Anthropic.InternalServerError)
    return { status: 503, upstream_status: e.status, error: "Ask is busy, try again" };
  // Our own deadline fired.
  if (e instanceof Anthropic.APIUserAbortError || isTimeout(e))
    return { status: 504, error: "The model took too long to answer." };
  if (e instanceof Anthropic.APIConnectionError) return { status: 503, error: "Ask is busy, try again" };
  if (e instanceof Anthropic.APIError)
    return { status: 502, upstream_status: e.status, error: `The Claude API rejected the request (${e.status}): ${e.message}` };
  return { status: 502, error: `Could not reach the Claude API: ${(e as Error)?.message || String(e)}` };
}

/**
 * What may be sent back after a turn. If a safety classifier declined mid-turn
 * and the fallback model took over (a "fallback" block marks the switch), the
 * blocks BEFORE the switch must not be echoed back except plain text.
 */
function echoable(content: BetaContentBlock[]): BetaContentBlock[] {
  const cut = content.map((b) => b.type as string).lastIndexOf("fallback");
  return cut < 0 ? content : content.filter((b, i) => i > cut || b.type === "text");
}

// ── Claude rounds → NDJSON ─────────────────────────────────────────────────
// Only the answer text is forwarded; the thinking stays on the server (its text
// is empty by default anyway, and Opus 5.5 puts any words between tool calls
// into thinking, not into the answer). Between rounds the browser gets one
// "step" line per lookup and a "facts" line with the facts it numbered, so the
// [n] chips work for them too. If a safety classifier declines mid-answer, the
// fallback model CONTINUES the same text on the same stream — nothing already
// sent is taken back — so the fragments can go straight through.

function agentToNdjson(run: AgentRun, first: BetaMessageStream): ReadableStream<Uint8Array> {
  const enc = new TextEncoder();
  let text = "";
  let current = first;

  return new ReadableStream<Uint8Array>({
    // start() runs synchronously inside `new ReadableStream`, so the first
    // round's "text" listener is attached before the request can produce anything.
    async start(controller) {
      const send = (obj: unknown) => {
        try {
          controller.enqueue(enc.encode(JSON.stringify(obj) + "\n"));
        } catch {
          /* the browser already left */
        }
      };
      const onText = (delta: string) => {
        text += delta;
        send({ type: "text", text: delta });
      };
      // Web search runs on Anthropic's side inside a round: report each search
      // as a "step" and the web pages Claude saw as "web" lines.
      let lookups = 0;
      const webSent = new Set<string>();
      const queriesSent = new Set<string>();
      const onBlock = (block: BetaContentBlock) => {
        const step = webStepOf(block);
        if (step) {
          lookups++;
          // The same query can come back twice (e.g. re-run inside dynamic filtering) — show it once.
          if (!queriesSent.has(step.target)) send({ type: "step", ...step, facts: 0 });
          queriesSent.add(step.target);
        }
        // Every page Claude saw: read in full, returned by a search, or cited.
        const fetched = step?.tool === "web_fetch" ? [{ url: step.target, title: step.target }] : [];
        const pages = [...fetched, ...webSourcesOf(block)].filter((p) => !webSent.has(p.url));
        for (const p of pages) webSent.add(p.url);
        if (pages.length) send({ type: "web", sources: pages });
      };
      first.on("text", onText);
      first.on("contentBlock", onBlock);

      // Input counts everything the model read: new tokens + cache reads + cache writes.
      const usage: Usage = { input_tokens: 0, output_tokens: 0 };
      const read = { cached: 0, written: 0, fresh: 0 }; // the same input, split for the cost log
      try {
        for (let round = 0; ; round++) {
          if (round > 0) {
            current = startRound(run, round);
            current.on("text", onText);
            current.on("contentBlock", onBlock);
          }
          const msg = await current.finalMessage();
          read.fresh += msg.usage.input_tokens;
          read.cached += msg.usage.cache_read_input_tokens ?? 0;
          read.written += msg.usage.cache_creation_input_tokens ?? 0;
          usage.input_tokens = read.fresh + read.cached + read.written;
          usage.output_tokens += msg.usage.output_tokens;

          // A long server-side search turn can pause; send it back as-is and the API resumes it.
          if (msg.stop_reason === "pause_turn") {
            run.messages.push({ role: "assistant", content: echoable(msg.content) });
            continue;
          }

          // Finished: an answer (end_turn), the token limit or a refusal. Lookups run
          // only on a clean "tool_use" stop — a call cut off by max_tokens may be truncated.
          const calls = msg.content.filter((b): b is BetaToolUseBlock => b.type === "tool_use");
          if (msg.stop_reason !== "tool_use" || calls.length === 0) {
            // One line per answer in the Vercel logs, to keep an eye on cost.
            console.info(
              `[ask] answered: ${round + 1} rounds, ${lookups} lookups, input ${read.fresh} new + ${read.written} cache-write + ${read.cached} cache-read, output ${usage.output_tokens}, ${Date.now() - run.deadline.start} ms`
            );
            send(
              doneLine({
                model: msg.model, // the model that actually answered (the fallback model after a refusal)
                effort: CLAUDE_EFFORT,
                engine: "anthropic",
                startedAt: run.deadline.start,
                citations: extractCitations(text, run.book.count),
                usage,
                stopReason: msg.stop_reason,
                lookups,
              })
            );
            break;
          }

          // Run every lookup of this round; all results go back in ONE user message.
          run.messages.push({ role: "assistant", content: echoable(msg.content) });
          const results: BetaToolResultBlockParam[] = calls.map((call) => {
            const r = runLookup(call.name, call.input, run.book);
            lookups++;
            send({ type: "step", ...r.step });
            if (r.newFacts.length) send({ type: "facts", snippets: r.newFacts });
            return { type: "tool_result", tool_use_id: call.id, content: r.content, ...(r.isError ? { is_error: true } : {}) };
          });
          run.messages.push({ role: "user", content: results });
        }
      } catch (e: any) {
        const why =
          e instanceof Anthropic.APIUserAbortError || isTimeout(e) ? "The model took too long to finish." : e?.message || String(e);
        send({ type: "error", error: `Stream interrupted: ${why}` });
      } finally {
        try {
          controller.close();
        } catch {
          /* already cancelled */
        }
      }
    },
    cancel() {
      current.abort(); // the browser left: stop generating (and paying for) tokens
    },
  });
}

// ── Engine 2: the model API, with backoff and model failover ───────────────

type ApiOutcome =
  | { ok: true; upstream: Response; model: string }
  | { ok: false; status: number; error: string; upstream_status?: number };

async function callApi(
  provider: Provider,
  candidates: string[],
  system: string,
  user: string,
  deadline: Deadline
): Promise<ApiOutcome> {
  let lastStatus: number | undefined;
  let lastDetail = "";
  let model = candidates[0];

  for (let attempt = 0; attempt <= API_MAX_RETRIES; attempt++) {
    // Alternate between the ranked models: a free-tier overload is per model.
    model = candidates[attempt % candidates.length];

    if (attempt > 0) {
      const wait = backoffMs(attempt);
      if (deadline.remaining() < wait + API_MIN_ATTEMPT_MS) break;
      await sleep(wait);
    }
    if (deadline.remaining() < API_MIN_ATTEMPT_MS) break;

    const { url, headers, body } = buildChatRequest(provider, model, {
      system,
      user,
      stream: true,
      temperature: 0.2, // grounded summarisation: low creativity, faithful numbers
      maxTokens: MAX_TOKENS,
    });

    let res: Response;
    try {
      res = await fetch(url, {
        method: "POST",
        headers,
        body: JSON.stringify(body),
        cache: "no-store",
        // Bounds the whole exchange, including reading the stream.
        signal: AbortSignal.timeout(Math.min(API_FETCH_TIMEOUT_MS, Math.max(1, deadline.remaining()))),
      });
    } catch (e: any) {
      // A network hiccup is worth a retry; a timeout means the budget is nearly gone.
      lastDetail = isTimeout(e) ? "timed out" : `could not reach ${provider.name} API`;
      lastStatus = undefined;
      if (isTimeout(e)) break;
      continue;
    }

    if (res.ok && res.body) return { ok: true, upstream: res, model };

    // Non-2xx: read the detail once (never echo the key or headers).
    lastStatus = res.status;
    try {
      const j: any = await res.json();
      lastDetail = j?.error?.message || "";
    } catch {
      lastDetail = "";
    }
    if (RETRYABLE_STATUSES.has(res.status)) continue;
    // A wrong model name may be fixed by the next candidate — try it without waiting.
    if (res.status === 404 && candidates.length > 1 && attempt < API_MAX_RETRIES) continue;

    // Anything else is an error a retry cannot fix: explain it.
    const api = `${provider.name} API`;
    if (res.status === 401 || res.status === 403)
      return {
        ok: false,
        status: 502,
        upstream_status: res.status,
        error: `The ${api} rejected the server's API key (${res.status}). Check ${provider.envVar} in Vercel → Settings → Environment Variables and redeploy.`,
      };
    if (res.status === 404)
      return {
        ok: false,
        status: 502,
        upstream_status: 404,
        error: `Model "${model}" was not found by the ${api} — set ASK_MODEL to a model that service offers.`,
      };
    return {
      ok: false,
      status: 502,
      upstream_status: res.status,
      error: `The ${api} rejected the request (${res.status})${lastDetail ? `: ${lastDetail}` : "."}`,
    };
  }

  // Retries exhausted, or no time left for another attempt.
  console.warn(`[ask] ${provider.name} API unavailable after retries (status ${lastStatus ?? "none"}${lastDetail ? `: ${lastDetail}` : ""}; model ${model})`);
  return {
    ok: false,
    status: 503,
    upstream_status: lastStatus,
    error: "Ask is busy, try again",
  };
}

interface StreamMeta {
  engine: string;
  effort: string;
  fallbackModel: string;
  snippetCount: number;
  startedAt: number;
}

// ── OpenAI-compatible SSE → NDJSON ─────────────────────────────────────────
// Chat-completions streams are simpler: every event is "data: {json}" with the
// text in choices[0].delta.content, and the stream ends with "data: [DONE]".
// Some services (OpenAI, Groq) add a final chunk carrying `usage`; others may
// not — usage then stays at zero, which is fine.

function openAiSseToNdjson(upstream: ReadableStream<Uint8Array>, meta: StreamMeta): ReadableStream<Uint8Array> {
  const enc = new TextEncoder();
  const dec = new TextDecoder();
  const reader = upstream.getReader();
  let buf = "";
  let text = "";
  let inputTokens = 0;
  let outputTokens = 0;
  let stopReason: string | null = null;
  let model: string | null = null;

  return new ReadableStream<Uint8Array>({
    async start(controller) {
      const send = (obj: unknown) => controller.enqueue(enc.encode(JSON.stringify(obj) + "\n"));

      const handleLine = (line: string) => {
        if (!line.startsWith("data:")) return;
        const data = line.slice(5).trim();
        if (!data || data === "[DONE]") return;
        let ev: any;
        try {
          ev = JSON.parse(data);
        } catch {
          return;
        }
        if (ev?.error) {
          send({ type: "error", error: ev.error?.message || "The model stream reported an error." });
          return;
        }
        if (ev?.model) model = ev.model;
        const choice = ev?.choices?.[0];
        const piece = choice?.delta?.content;
        if (typeof piece === "string" && piece) {
          text += piece;
          send({ type: "text", text: piece });
        }
        // OpenAI-style services say "length" where Anthropic says "max_tokens";
        // the UI only knows the latter ("answer cut at the token limit").
        if (choice?.finish_reason)
          stopReason = choice.finish_reason === "length" ? "max_tokens" : choice.finish_reason;
        if (ev?.usage) {
          inputTokens = ev.usage.prompt_tokens ?? inputTokens;
          outputTokens = ev.usage.completion_tokens ?? outputTokens;
        }
      };

      try {
        while (true) {
          const { value, done } = await reader.read();
          if (done) break;
          buf += dec.decode(value, { stream: true }).replace(/\r\n/g, "\n");
          let nl: number;
          while ((nl = buf.indexOf("\n")) >= 0) {
            handleLine(buf.slice(0, nl));
            buf = buf.slice(nl + 1);
          }
        }
        if (buf.trim()) handleLine(buf);
        send(
          doneLine({
            model: model || meta.fallbackModel,
            effort: meta.effort,
            engine: meta.engine,
            startedAt: meta.startedAt,
            citations: extractCitations(text, meta.snippetCount),
            usage: { input_tokens: inputTokens, output_tokens: outputTokens },
            stopReason,
          })
        );
      } catch (e: any) {
        const msg = isTimeout(e) ? "The model took too long to finish." : e?.message || String(e);
        send({ type: "error", error: `Stream interrupted: ${msg}` });
      } finally {
        controller.close();
      }
    },
    cancel() {
      reader.cancel().catch(() => {});
    },
  });
}

// ── The handler ────────────────────────────────────────────────────────────

export async function POST(req: NextRequest) {
  const deadline = makeDeadline(BUDGET_MS);

  // 1) Cheap protections first: rate limit and body size.
  if (rateLimited("ask", clientIp(req), RATE_LIMIT, RATE_WINDOW_MS))
    return NextResponse.json(
      { error: `Too many questions — the limit is ${RATE_LIMIT} per minute. Try again shortly.` },
      { status: 429 }
    );
  const declared = Number(req.headers.get("content-length") || 0);
  if (declared > MAX_BODY_BYTES)
    return NextResponse.json({ error: "Request too large." }, { status: 413 });
  const rawText = await req.text();
  if (rawText.length > MAX_BODY_BYTES)
    return NextResponse.json({ error: "Request too large." }, { status: 413 });

  // 2) Validate the shape before spending anything.
  let parsedJson: unknown;
  try {
    parsedJson = JSON.parse(rawText);
  } catch {
    return NextResponse.json({ error: "Body is not valid JSON." }, { status: 400 });
  }
  const parsed = parseBody(parsedJson);
  if (typeof parsed === "string") return NextResponse.json({ error: parsed }, { status: 400 });

  // 3) The prompt — the same for every engine.
  const system = buildSystemPrompt(parsed.intent, parsed.lang);
  const user = buildUserMessage(parsed.question, parsed.snippets, parsed.intent, parsed.history);
  const provider = resolveProvider(); // engine 2, or null when none is configured

  // 4) Engine 1 — Claude, when ANTHROPIC_API_KEY is set.
  const client = claudeClient();
  if (client) {
    const claude = await askClaude(client, system, user, parsed.snippets, deadline);
    if (claude.ok) return new Response(claude.body, { status: 200, headers: NDJSON_HEADERS });
    console.warn(`[ask] Claude API unavailable (status ${claude.upstream_status ?? "none"}): ${claude.error}`);
    if (!provider) {
      const body: Record<string, unknown> = { error: claude.error, upstream_status: claude.upstream_status };
      if (claude.status === 503) body.code = "busy";
      return NextResponse.json(body, { status: claude.status });
    }
    // Otherwise fall through: engine 2 answers this one.
  }

  // 5) Engine 2 — an OpenAI-compatible API. No key at all → tell the UI how to set one up.
  if (!provider)
    return NextResponse.json(
      { error: "No answer engine configured (ANTHROPIC_API_KEY, ASK_API_KEY or GROQ_API_KEY)", code: "no_api_key" },
      { status: 503 }
    );

  const candidates = await pickModels(provider, "best");
  const outcome = await callApi(provider, candidates, system, user, deadline);
  if (!outcome.ok) {
    const body: Record<string, unknown> = { error: outcome.error, upstream_status: outcome.upstream_status };
    if (outcome.status === 503) body.code = "busy";
    return NextResponse.json(body, { status: outcome.status });
  }

  // 5) Stream the answer down as NDJSON.
  const meta: StreamMeta = {
    engine: provider.engine,
    effort: "default",
    fallbackModel: outcome.model,
    snippetCount: parsed.snippets.length,
    startedAt: deadline.start,
  };
  const stream = openAiSseToNdjson(outcome.upstream.body!, meta);
  return new Response(stream, { status: 200, headers: NDJSON_HEADERS });
}
