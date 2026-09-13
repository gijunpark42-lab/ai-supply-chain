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
//   {"type":"text","text":"..."}      answer fragments in order (the local engine sends ONE)
//   {"type":"done","model":"claude-opus-5"|…,"effort":"max"|"default",
//                  "engine":"local"|"groq"|"openai-compatible",
//                  "latency_ms":n,"citations":[n,…],"usage":{…},"stop_reason":"…"}   once, last
//   {"type":"error","error":"..."}    only if an upstream stream breaks mid-way
// Before anything is streamed, problems come back as plain JSON with a real
// HTTP status: 400 bad input, 413 too big, 429 rate limit (10 per minute per
// IP), 503 {code:"no_api_key"} nothing is configured, 503 {code:"busy"} every
// engine failed after retries, 502 / 504 for API failures a retry cannot fix.
//
// Two answer engines, tried in order:
//   1. LOCAL — the owner's own PC running local-ask/server.mjs (the Claude Code
//      CLI: Opus at max effort), reached through a tunnel at LOCAL_ASK_URL with
//      the shared header x-ask-secret = ASK_SHARED_SECRET. First GET /health
//      (3 s — "is the PC on?"), then POST /answer (up to 3 min — Opus is slow).
//      ANY failure — PC off, tunnel down, timeout, bad JSON — falls through
//      silently; the user never sees a local error, only the fallback answer.
//   2. API — any OpenAI-compatible service (ASK_BASE_URL + ASK_API_KEY) / Groq
//      (GROQ_API_KEY); ASK_MODEL pins a model name. Gemini and the Anthropic
//      API were removed on 2026-09-11 — Claude answers come only from the
//      owner's local runner. Free tiers answer 429
//      and 503 often, so the call is retried with exponential backoff (1 s, 2 s,
//      4 s + jitter), alternating between the best models the service lists.
// Both engines get the SAME prompt from lib/askPrompt.mjs, so their answers
// differ only by model, never by instructions.
//
// When LOCAL_ASK_URL is unset the local step is skipped entirely: the deployed
// site never depends on the owner's machine being on.
//
// Why a server route at all? The model API key must never reach the browser.
// It lives only in environment variables (Vercel → Settings → Environment
// Variables, or web/.env — git-ignored — when running locally).

import { NextRequest, NextResponse } from "next/server";
import {
  LOCAL_MODEL_ID,
  normalizeIntent,
  normalizeLang,
  normalizeHistory,
  buildSystemPrompt,
  buildUserMessage,
  extractCitations,
} from "@/lib/askPrompt.mjs";
import {
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
// working with a shorter local wait instead of breaking.
export const maxDuration = 300;

const BUDGET_MS = (maxDuration - 10) * 1000; // leave 10 s of headroom before Vercel's cut-off
const LOCAL_HEALTH_TIMEOUT_MS = 3_000; // "is the PC on?"
// Opus at max effort needs 15–60 s for an English question and 3–4+ minutes
// for a Korean answer over 20+ snippets; the owner wants Opus at max, so wait
// nearly the whole Vercel budget (300 s on Hobby) before giving up. The runner's
// own ASK_TIMEOUT_MS is 300 s (local-ask/.env). The deadline math below caps the
// real wait at the budget minus the reserve (~285 s): Vercel kills the function at 300 s.
const LOCAL_ANSWER_TIMEOUT_MS = 300_000;
const LOCAL_MIN_ANSWER_MS = 10_000; // below this the local engine is not worth trying
const API_RESERVE_MS = 5_000; // headroom after the local wait (there is no API fallback in practice)
const API_FETCH_TIMEOUT_MS = 60_000; // one API call, including reading the stream
const API_MAX_RETRIES = 3; // after the first attempt: waits of 1 s, 2 s, 4 s (+ jitter)
const API_MIN_ATTEMPT_MS = 8_000; // do not start an attempt with less than this left

// Output budget: three sections (answer / evidence / gaps) can run to ~1,000
// tokens, and on "thinking" models the hidden reasoning counts against the
// same limit — with 1,500 a
// ranking question came back empty, cut at the limit before any visible text.
const MAX_TOKENS = 4000;

// ── Request limits (the browser sends ≤18k chars of snippets + ≤10k of history; these are ceilings) ──
const MAX_BODY_BYTES = 128_000;
const MAX_QUESTION_CHARS = 500;
const MAX_SNIPPETS = 60;
const MAX_SNIPPET_TEXT = 2_000;
const MAX_TOTAL_TEXT = 20_000;
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
  lang: string; // "en" | "ko"
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
  effort: string; // "max" (local Opus), "default" (API)
  engine: string;
  startedAt: number;
  citations: number[];
  usage: Usage;
  stopReason: string | null;
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
  };
}

// ── Engine 1: the local runner ─────────────────────────────────────────────

type Deadline = ReturnType<typeof makeDeadline>;

interface LocalAnswer {
  answer: string;
  citations: number[];
  model: string; // the real model id the CLI used ("claude-opus-5"), else "claude-code-local"
  effort: string; // the CLI's --effort ("max")
}

let warnedNoSecret = false;

/** True when LOCAL_ASK_URL is set — i.e. the owner wants the local engine tried. */
function localConfigured(): boolean {
  return Boolean(process.env.LOCAL_ASK_URL?.trim());
}

/**
 * Ask the owner's machine. Returns null on ANY problem — the caller then falls
 * through to the API engine, and the user never sees the local error.
 */
async function askLocal(body: AskBody, deadline: Deadline): Promise<LocalAnswer | null> {
  const base = process.env.LOCAL_ASK_URL?.trim().replace(/\/+$/, "");
  if (!base) return null;
  const secret = process.env.ASK_SHARED_SECRET;
  if (!secret) {
    if (!warnedNoSecret) console.warn("[ask] LOCAL_ASK_URL is set but ASK_SHARED_SECRET is missing — local engine skipped.");
    warnedNoSecret = true;
    return null;
  }
  // Give Opus up to 60 s, but always keep enough of the budget for the fallback.
  const answerTimeout = Math.min(LOCAL_ANSWER_TIMEOUT_MS, deadline.remaining() - API_RESERVE_MS);
  if (answerTimeout < LOCAL_MIN_ANSWER_MS) return null;

  try {
    // Stage 1 — a quick probe. If the PC is off or the tunnel is down this fails in ≤3 s.
    const health = await fetch(`${base}/health`, {
      headers: { "x-ask-secret": secret },
      cache: "no-store",
      signal: AbortSignal.timeout(LOCAL_HEALTH_TIMEOUT_MS),
    });
    if (!health.ok) throw new Error(`health returned ${health.status}`);
    const h: any = await health.json();
    if (h?.ok !== true) throw new Error("health did not report ok");

    // Stage 2 — the real question.
    const res = await fetch(`${base}/answer`, {
      method: "POST",
      headers: { "content-type": "application/json", "x-ask-secret": secret },
      body: JSON.stringify({
        question: body.question,
        snippets: body.snippets,
        intent: body.intent,
        lang: body.lang,
        history: body.history,
      }),
      cache: "no-store",
      signal: AbortSignal.timeout(answerTimeout),
    });
    if (!res.ok) throw new Error(`answer returned ${res.status}`);
    const j: any = await res.json();
    const answer = typeof j?.answer === "string" ? j.answer.trim() : "";
    if (!answer) throw new Error("answer was empty");

    const n = body.snippets.length;
    const fromRunner: number[] = Array.isArray(j.citations)
      ? (j.citations as unknown[]).filter((x): x is number => Number.isInteger(x) && (x as number) >= 1 && (x as number) <= n)
      : [];
    const str = (v: unknown) => (typeof v === "string" && v ? v : "");
    return {
      answer,
      citations: fromRunner.length ? fromRunner : extractCitations(answer, n),
      // The runner reports the model the CLI actually used (from its usage
      // report) — that is what the badge should show, not the alias "opus".
      model: str(j.model_id) || str(j.cli_model) || str(j.model) || LOCAL_MODEL_ID,
      effort: str(j.effort) || "?",
    };
  } catch (e: any) {
    const why = isTimeout(e) ? "timed out" : e?.message || String(e);
    console.warn(`[ask] local runner unavailable: ${why}`);
    return null;
  }
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

  // 3) Engine 1 — the owner's machine, if configured and awake.
  const local = await askLocal(parsed, deadline);
  if (local) {
    const lines = [
      { type: "text", text: local.answer },
      doneLine({
        model: local.model,
        effort: local.effort,
        engine: "local",
        startedAt: deadline.start,
        citations: local.citations,
        usage: { input_tokens: 0, output_tokens: 0 },
        stopReason: "end_turn",
      }),
    ];
    return new Response(lines.map((l) => JSON.stringify(l) + "\n").join(""), {
      status: 200,
      headers: NDJSON_HEADERS,
    });
  }

  // 4) Engine 2 — the model API. No key at all → tell the UI how to set one up.
  const provider = resolveProvider();
  if (!provider) {
    if (localConfigured())
      return NextResponse.json(
        { error: "Ask is busy, try again (the local runner is offline and no API key is configured)", code: "busy" },
        { status: 503 }
      );
    return NextResponse.json(
      { error: "No answer engine configured (LOCAL_ASK_URL, ASK_API_KEY or GROQ_API_KEY)", code: "no_api_key" },
      { status: 503 }
    );
  }

  const system = buildSystemPrompt(parsed.intent, parsed.lang);
  const user = buildUserMessage(parsed.question, parsed.snippets, parsed.intent, parsed.history);
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
