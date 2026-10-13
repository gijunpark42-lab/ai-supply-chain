// /api/ask/rewrite — "Ask the Graph", step 1: turn the user's question into
// 2–4 search queries in the graph's own vocabulary, plus an intent.
//
//   POST { question, history?: [{question, answer}, …] }   (history = earlier turns, for follow-ups)
//   → 200 { queries: string[], intent: "lookup"|"compare"|"rank"|"timeline", model?: string, fallback?: true }
//
// Why: the browser's search (lib/retrieval.ts) is keyword-based. "Who has the
// biggest cloud compute capacity" shares no words with the entries that answer
// it ("capex guidance", "GW commitments", "data center backlog"), so the
// snippets never surfaced and the model rightly said the graph had nothing.
// A model rewrites the question into the words the entries actually use;
// the browser then searches the union of those queries and the original.
// With ANTHROPIC_API_KEY set that model is Claude Opus 5.5 at effort "low"
// (a short JSON reply, so little thinking); otherwise the cheapest model of the
// OpenAI-compatible service.
//
// This step must never block a question: on ANY problem (no key, timeout,
// overload, malformed reply) it still answers 200 with no queries and an intent
// guessed from a few English cues — the browser just searches the original.
// Only no sign-in (401 {code:"signin"}), bad input (400), the rate limit (429) and
// "no provider at all" (503 {code:"no_api_key"}) are real errors.

import { NextRequest, NextResponse } from "next/server";
import { auth } from "@clerk/nextjs/server";
import { REWRITE_PROMPT, guessIntent, parseRewrite, buildRewriteUser } from "@/lib/askPrompt.mjs";
import {
  CLAUDE_MODEL,
  CLAUDE_REFUSAL_FALLBACK,
  claudeClient,
  resolveProvider,
  pickModels,
  buildChatRequest,
  RETRYABLE_STATUSES,
  sleep,
  rateLimited,
  clientIp,
} from "@/lib/askProvider";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 20;

const MAX_QUESTION_CHARS = 500;
const RATE_LIMIT = 20; // per minute per IP — twice the answer route's, one rewrite per question
const RATE_WINDOW_MS = 60_000;
const ATTEMPT_TIMEOUT_MS = 8_000;
const RETRY_WAIT_MS = 800;
const MAX_TOKENS = 1000; // the JSON reply is ~40 tokens, but a thinking model's hidden reasoning counts too

export async function POST(req: NextRequest) {
  // Signed-in users only, like /api/ask (middleware.ts runs Clerk on this route).
  const { userId } = await auth();
  if (!userId)
    return NextResponse.json({ error: "Sign in to use Ask.", code: "signin" }, { status: 401 });

  if (rateLimited("rewrite", clientIp(req), RATE_LIMIT, RATE_WINDOW_MS))
    return NextResponse.json({ error: "Too many requests. Try again shortly." }, { status: 429 });

  let body: any;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "Body is not valid JSON." }, { status: 400 });
  }
  const question = typeof body?.question === "string" ? body.question.trim() : "";
  if (!question) return NextResponse.json({ error: "Missing 'question'." }, { status: 400 });
  if (question.length > MAX_QUESTION_CHARS)
    return NextResponse.json({ error: `Question is too long (max ${MAX_QUESTION_CHARS} characters).` }, { status: 400 });

  // What the browser gets when the model cannot be used: no rewritten queries,
  // an intent from a few English cues. Never an error.
  const fallback = () =>
    NextResponse.json({ queries: [], intent: guessIntent(question), fallback: true }, { status: 200 });

  // Claude first, when ANTHROPIC_API_KEY is set.
  const client = claudeClient();
  if (client) {
    try {
      const msg = await client.beta.messages.create(
        {
          model: CLAUDE_MODEL,
          max_tokens: MAX_TOKENS,
          thinking: { type: "adaptive" },
          output_config: { effort: "low" },
          system: REWRITE_PROMPT,
          // Earlier questions of the thread go in too, so "what about Samsung?"
          // becomes a standalone query.
          messages: [{ role: "user", content: buildRewriteUser(question, body?.history) }],
          ...CLAUDE_REFUSAL_FALLBACK,
        },
        { timeout: ATTEMPT_TIMEOUT_MS, maxRetries: 1 }
      );
      if (msg.stop_reason === "refusal") return fallback();
      let text = "";
      for (const block of msg.content) if (block.type === "text") text += block.text;
      const { queries, intent } = parseRewrite(text, question);
      return NextResponse.json({ queries, intent, model: msg.model }, { status: 200 });
    } catch (e: any) {
      console.warn(`[ask/rewrite] Claude API unavailable (${e?.status ?? e?.name ?? "error"}) — searching the original question only.`);
      return fallback();
    }
  }

  const provider = resolveProvider();
  if (!provider)
    return NextResponse.json(
      { error: "No model API key configured (ANTHROPIC_API_KEY, ASK_API_KEY or GROQ_API_KEY)", code: "no_api_key" },
      { status: 503 }
    );

  const candidates = await pickModels(provider, "cheap");
  let jsonObject = true; // ask for a JSON object; dropped if the service rejects the parameter

  for (let attempt = 0; attempt < 2; attempt++) {
    const model = candidates[attempt % candidates.length];
    if (attempt > 0) await sleep(RETRY_WAIT_MS);

    const { url, headers, body: reqBody } = buildChatRequest(provider, model, {
      system: REWRITE_PROMPT,
      // Earlier questions of the thread go in too, so "what about Samsung?"
      // becomes a standalone query.
      user: buildRewriteUser(question, body?.history),
      stream: false,
      temperature: 0,
      maxTokens: MAX_TOKENS,
      jsonObject,
    });

    let res: Response;
    try {
      res = await fetch(url, {
        method: "POST",
        headers,
        body: JSON.stringify(reqBody),
        cache: "no-store",
        signal: AbortSignal.timeout(ATTEMPT_TIMEOUT_MS),
      });
    } catch {
      continue; // network error or timeout → one more try, then the fallback
    }

    if (!res.ok) {
      let detail = "";
      try {
        const j: any = await res.json();
        detail = j?.error?.message || "";
      } catch {
        /* not JSON */
      }
      // Some OpenAI-compatible services do not know `response_format`: retry plain.
      if (res.status === 400 && jsonObject && /response_format/i.test(detail)) {
        jsonObject = false;
        attempt--; // same model, without the parameter
        continue;
      }
      if (RETRYABLE_STATUSES.has(res.status)) continue;
      console.warn(`[ask/rewrite] ${provider.name} API rejected the request (${res.status}${detail ? `: ${detail}` : ""})`);
      return fallback();
    }

    let text = "";
    try {
      const j: any = await res.json();
      text = j?.choices?.[0]?.message?.content;
    } catch {
      continue;
    }
    if (typeof text !== "string") continue;

    const { queries, intent } = parseRewrite(text, question);
    return NextResponse.json({ queries, intent, model }, { status: 200 });
  }

  console.warn(`[ask/rewrite] ${provider.name} API unavailable — searching the original question only.`);
  return fallback();
}
