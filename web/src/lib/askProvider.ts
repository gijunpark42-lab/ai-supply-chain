// askProvider.ts — SERVER-ONLY helpers shared by the two Ask routes:
//   /api/ask          (the answer: the Claude API first, then an OpenAI-compatible API)
//   /api/ask/rewrite  (the query-rewrite step that runs before retrieval)
// It reads API keys from process.env, so it must never be imported by a client
// component.
//
// Two kinds of service:
//   • the Claude API (ANTHROPIC_API_KEY), through the official SDK
//     @anthropic-ai/sdk. Since 2026-10-12 it answers every question with
//     Claude Opus 5.5 — it replaced the local runner (local-ask/). This Ask
//     tab is the ONLY part of the project that pays for the Claude API;
//     enrichment and coding stay in Claude Code on the owner's machine.
//   • optional fallbacks that speak the OpenAI "chat completions" protocol
//     (Groq, OpenRouter…) — plain fetch, ONE request builder covers them all.

import Anthropic from "@anthropic-ai/sdk";
import type { NextRequest } from "next/server";

// ── The Claude API ─────────────────────────────────────────────────────────

/** The model for both Ask steps (the answer and the query rewrite). */
export const CLAUDE_MODEL = "claude-opus-5-5";

/**
 * Opus 5.5's safety classifiers occasionally decline a harmless question. With
 * these two request fields the API re-runs a declined request on the model
 * Anthropic recommends for that case, inside the same call, instead of
 * returning the refusal. Spread into every Claude request.
 */
export const CLAUDE_REFUSAL_FALLBACK: { betas: string[]; fallbacks: "default" } = {
  betas: ["server-side-fallback-2026-07-01"],
  fallbacks: "default",
};

let claude: Anthropic | null = null;

/**
 * The Claude API client, or null when ANTHROPIC_API_KEY is not set. Made once
 * per warm instance. The SDK itself retries 429 / 5xx / "overloaded" (529)
 * and network errors twice, with backoff.
 */
export function claudeClient(): Anthropic | null {
  if (!process.env.ANTHROPIC_API_KEY?.trim()) return null;
  claude ??= new Anthropic(); // reads ANTHROPIC_API_KEY from the environment
  return claude;
}

// ── Provider resolution (the OpenAI-compatible fallbacks) ──────────────────

export interface Provider {
  /** For error messages: "Groq", "the configured OpenAI-compatible". */
  name: string;
  /** Short id the UI badge shows next to the model id. */
  engine: "groq" | "openai-compatible";
  /** OpenAI-compatible root (…/v1). */
  baseUrl: string;
  apiKey: string;
  /** The built-in default model; ASK_MODEL overrides it. */
  model: string;
  /** Which env var holds the key — for the error text. */
  envVar: string;
}

/**
 * Which service to call, decided by which env vars exist (first match wins).
 * Defaults are the cheapest capable model on each service.
 */
export function resolveProvider(): Provider | null {
  const env = process.env;
  const model = env.ASK_MODEL?.trim();
  if (env.ASK_BASE_URL && env.ASK_API_KEY)
    return {
      name: "the configured OpenAI-compatible",
      engine: "openai-compatible",
      baseUrl: env.ASK_BASE_URL.replace(/\/+$/, ""),
      apiKey: env.ASK_API_KEY,
      model: model || "gpt-4o-mini",
      envVar: "ASK_API_KEY",
    };
  if (env.GROQ_API_KEY)
    return {
      name: "Groq",
      engine: "groq",
      baseUrl: "https://api.groq.com/openai/v1",
      apiKey: env.GROQ_API_KEY,
      model: model || "llama-3.3-70b-versatile",
      envVar: "GROQ_API_KEY",
    };
  return null;
}

// ── Model discovery ────────────────────────────────────────────────────────
// Free-tier services retire model names often. Unless ASK_MODEL pins one, ask
// the OpenAI-compatible service
// for its model list (GET /models) and rank the ones we recognise. The raw
// list is cached per warm instance for an hour; ranking is recomputed per
// purpose ("best" for answers, "cheap" for the query rewrite).

const MODEL_CACHE_MS = 3_600_000;
const modelCache = new Map<string, { at: number; ids: string[] }>();

export type Prefer = "best" | "cheap";

/** Rank the service's model ids for one purpose, best first (at most 3). [] = nothing recognised. */
export function rankModels(p: Provider, ids: string[], prefer: Prefer): string[] {
  const out: string[] = [];
  const push = (id?: string | null) => {
    if (id && !out.includes(id)) out.push(id);
  };
  if (p.engine === "groq") {
    const best = ["llama-3.3-70b-versatile", "openai/gpt-oss-120b", "openai/gpt-oss-20b", "llama-3.1-8b-instant"];
    const cheap = ["llama-3.1-8b-instant", "openai/gpt-oss-20b", "llama-3.3-70b-versatile", "openai/gpt-oss-120b"];
    for (const want of prefer === "cheap" ? cheap : best) if (ids.includes(want)) push(want);
    push(ids.find((id) => /llama/i.test(id) && /70b/i.test(id)));
  }
  if (ids.includes(p.model)) push(p.model); // the built-in default, as a last resort
  return out.slice(0, 3);
}

/**
 * The models to try, in order. One entry unless discovery found alternatives —
 * a second choice matters because free-tier "model overloaded" errors are per model.
 */
export async function pickModels(p: Provider, prefer: Prefer = "best"): Promise<string[]> {
  const pinned = process.env.ASK_MODEL?.trim();
  if (pinned) return [p.model];

  let ids: string[] | undefined = undefined;
  const cached = modelCache.get(p.baseUrl);
  if (cached && Date.now() - cached.at < MODEL_CACHE_MS) ids = cached.ids;
  if (ids === undefined) {
    ids = [];
    try {
      const r = await fetch(`${p.baseUrl}/models`, {
        headers: { authorization: `Bearer ${p.apiKey}` },
        cache: "no-store",
        signal: AbortSignal.timeout(8_000),
      });
      if (r.ok) {
        const j: any = await r.json();
        for (const m of (j?.data as any[]) || []) {
          const id = String(m?.id || "").replace(/^models\//, "");
          if (id) ids.push(id);
        }
        if (ids.length) modelCache.set(p.baseUrl, { at: Date.now(), ids });
      }
    } catch {
      /* discovery is best-effort: fall through to the default name */
    }
  }
  const ranked = rankModels(p, ids, prefer);
  return ranked.length ? ranked : [p.model];
}

// ── Request builder ────────────────────────────────────────────────────────

export interface ChatOptions {
  system: string;
  user: string;
  stream: boolean;
  temperature: number;
  maxTokens: number;
  /** Ask for a JSON object reply (the rewrite step). */
  jsonObject?: boolean;
}

/** The HTTP request for one model name (OpenAI chat-completions shape). Never logs the key. */
export function buildChatRequest(
  p: Provider,
  model: string,
  o: ChatOptions
): { url: string; headers: Record<string, string>; body: Record<string, unknown> } {
  const body: Record<string, unknown> = {
    model,
    max_tokens: o.maxTokens,
    stream: o.stream,
    temperature: o.temperature,
    messages: [
      { role: "system", content: o.system },
      { role: "user", content: o.user },
    ],
  };
  if (o.jsonObject) body.response_format = { type: "json_object" };
  return {
    url: `${p.baseUrl}/chat/completions`,
    headers: {
      "content-type": "application/json",
      authorization: `Bearer ${p.apiKey}`,
    },
    body,
  };
}

// ── Retry helpers ──────────────────────────────────────────────────────────

/** Statuses worth retrying: rate limit, and the "overloaded / unavailable" family. */
export const RETRYABLE_STATUSES = new Set([429, 500, 502, 503, 529]);

export const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

/** Exponential backoff: retry 1 → 1 s, 2 → 2 s, 3 → 4 s, each plus 0–500 ms of jitter
 *  so several waiting requests do not all hit the service in the same instant. */
export function backoffMs(retry: number): number {
  return 1000 * 2 ** (retry - 1) + Math.floor(Math.random() * 500);
}

/** True for the errors fetch throws when an AbortSignal.timeout fires. */
export function isTimeout(e: unknown): boolean {
  const name = (e as { name?: string } | null)?.name;
  return name === "TimeoutError" || name === "AbortError";
}

/** A countdown from the request start, so every step can ask "how long is left?". */
export function makeDeadline(budgetMs: number) {
  const start = Date.now();
  return {
    start,
    elapsed: () => Date.now() - start,
    remaining: () => budgetMs - (Date.now() - start),
  };
}

// ── Rate limit (per warm instance) ─────────────────────────────────────────
// In-memory, so it is per serverless instance and resets on a cold start — a
// speed bump against runaway scripts, not a billing guarantee (the real cap is
// the spend limit set in the Claude Console). Good enough for a personal tool.

const hits = new Map<string, number[]>();

/** True when `ip` already made `limit` requests to `bucket` inside the window. */
export function rateLimited(bucket: string, ip: string, limit: number, windowMs: number): boolean {
  const key = `${bucket}:${ip}`;
  const now = Date.now();
  const recent = (hits.get(key) || []).filter((t) => now - t < windowMs);
  if (recent.length >= limit) {
    hits.set(key, recent);
    return true;
  }
  recent.push(now);
  hits.set(key, recent);
  // Keep the map from growing forever on a long-lived instance.
  if (hits.size > 5_000) {
    for (const [k, v] of hits) if (!v.some((t) => now - t < windowMs)) hits.delete(k);
  }
  return false;
}

export function clientIp(req: NextRequest): string {
  const fwd = req.headers.get("x-forwarded-for");
  if (fwd) return fwd.split(",")[0].trim();
  return req.headers.get("x-real-ip") || "unknown";
}
