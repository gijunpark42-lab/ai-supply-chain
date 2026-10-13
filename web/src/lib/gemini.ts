// gemini.ts — the /news terminal's one AI: Google's Gemini API on the free tier
// (GEMINI_API_KEY). Never the Claude API, which only the Ask tab uses.
// It writes the click summaries (lib/newsSummary.ts) and puts non-English
// headlines and filing names into English (lib/news.ts, lib/filings.ts).
// Every caller has a no-AI fallback: without a key or at the free-tier limit,
// text simply stays as it was published.
//
// Server-only.

const GEMINI_MODEL = "gemini-flash-lite-latest";

export async function generate(
  system: string,
  user: string,
  opts: { maxTokens?: number; json?: boolean } = {}
): Promise<string | null> {
  const key = process.env.GEMINI_API_KEY?.trim();
  if (!key) return null;
  try {
    const res = await fetch(`https://generativelanguage.googleapis.com/v1beta/models/${GEMINI_MODEL}:generateContent`, {
      method: "POST",
      cache: "no-store",
      headers: { "Content-Type": "application/json", "x-goog-api-key": key },
      body: JSON.stringify({
        systemInstruction: { parts: [{ text: system }] },
        contents: [{ role: "user", parts: [{ text: user }] }],
        generationConfig: {
          temperature: 0.2,
          maxOutputTokens: opts.maxTokens ?? 800,
          ...(opts.json ? { responseMimeType: "application/json" } : {}),
        },
      }),
      signal: AbortSignal.timeout(30_000),
    });
    if (!res.ok) {
      console.warn(`[news] gemini ${res.status}: ${(await res.text()).replace(/\s+/g, " ").slice(0, 200)}`);
      return null;
    }
    const j = await res.json();
    const text = (j?.candidates?.[0]?.content?.parts || [])
      .map((p: any) => (p.thought ? "" : p.text || ""))
      .join("")
      .trim();
    return text || null;
  } catch (e) {
    console.warn(`[news] gemini failed: ${e}`);
    return null;
  }
}

// Korean, Japanese and Chinese script — what marks a headline as not English.
const CJK = /[぀-ヿ㐀-鿿가-힯]/;
// Below 50% Latin letters (company names and tickers stay Latin anyway) = not English.
export const isEnglish = (text: string) =>
  (text.match(/[A-Za-z]/g)?.length || 0) >= 0.5 * (text.match(/\p{L}/gu)?.length || 1);
export const needsEnglish = (text: string) => CJK.test(text);

// Translations already made, kept while the instance stays warm, so each refresh
// only sends Gemini the headlines that are new since the last one.
const english = new Map<string, string>();
const BATCH = 100; // headlines per Gemini call (~9 calls for a cold start: under the per-minute limit)
const MAX_MEMO = 20_000;

/** English for every Korean / Japanese / Chinese string in `texts` (a lookup:
 *  original → English). Strings Gemini could not translate are simply absent. */
export async function toEnglish(texts: string[]): Promise<Map<string, string>> {
  const todo = [...new Set(texts.filter((t) => needsEnglish(t) && !english.has(t)))];
  if (english.size + todo.length > MAX_MEMO) english.clear();
  const batches: string[][] = [];
  for (let i = 0; i < todo.length; i += BATCH) batches.push(todo.slice(i, i + BATCH));
  // Three calls at a time keeps a cold start under the free tier's per-minute limit.
  for (let i = 0; i < batches.length; i += 3) {
    await Promise.all(
      batches.slice(i, i + 3).map(async (batch) => {
        // Numbered keys, so an answer that drops or merges a line still lines up.
        const out = await generate(
          "Translate each value of the JSON object into natural English, as a news headline, filing title " +
            "or publisher name would read (a publisher keeps its own English or romanized name, e.g. 日本経済新聞 → Nikkei). " +
            "Keep company names in their usual English form and keep tickers and numbers. " +
            "Return a JSON object with the same keys, each value its English translation.",
          JSON.stringify(Object.fromEntries(batch.map((t, k) => [k, t]))),
          { maxTokens: 8192, json: true }
        );
        if (!out) return; // refused (free-tier limit): these wait for the next refresh
        try {
          const obj = JSON.parse(out);
          batch.forEach((t, k) => {
            const en = obj?.[k];
            if (typeof en === "string" && en.trim()) english.set(t, en.trim());
          });
        } catch {
          console.warn(`[news] translation answer was not JSON: ${out.slice(0, 120)}`);
        }
      })
    );
  }
  return english;
}
