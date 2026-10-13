// newsSummary.ts — what the /news terminal shows when a headline or filing is
// clicked: a short summary of it plus every map company it names.
//
// The summary is always in English (user, 2026-10-13), whatever the source's
// language, and comes from Google's free Gemini API (lib/gemini.ts) — never the
// Claude API. Without a key, or when Gemini refuses (free-tier limit), the
// article's own lead paragraphs stand in.
// Display only, like lib/news.ts: nothing is stored.
//
// Server-only.

import { inflateRawSync } from "node:zlib";
import { SEC_UA } from "./filings";
import { generate, isEnglish } from "./gemini";
import { decodeEntities, tagCompanies, tickerOf, type Digest } from "./news";

const UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36";
const MAX_ARTICLE_CHARS = 12_000;

export interface NewsSummary {
  url: string; // the article itself (Google News links resolved)
  summary: string;
  kind: "ai" | "lead" | "feed" | "none"; // where the summary came from
  companies: string[]; // map companies named anywhere in the article
  tickers: Record<string, string | null>;
  others: string[]; // tickers in the article that are not map companies
}

export interface SummaryRequest {
  url: string;
  title: string;
  blurb: string; // the feed's own summary
}

// ── Google News links → the real article ──────────────────────────────────
// news.google.com/rss/articles/<id> is a JS redirect. The article page carries a
// signature + timestamp that Google's own batchexecute call trades for the URL.
async function resolveGoogleNews(link: string): Promise<string | null> {
  try {
    const id = new URL(link).pathname.split("/").pop();
    if (!id) return null;
    const html = await (
      await fetch(`https://news.google.com/rss/articles/${id}`, { headers: { "User-Agent": UA }, cache: "no-store", signal: AbortSignal.timeout(8000) })
    ).text();
    const sg = html.match(/data-n-a-sg="([^"]+)"/)?.[1];
    const ts = html.match(/data-n-a-ts="([^"]+)"/)?.[1];
    if (!sg || !ts) return null;
    const req = [
      "Fbv4je",
      `["garturlreq",[["X","X",["X","X"],null,null,1,1,"US:en",null,1,null,null,null,null,null,0,1],"X","X",1,[1,1,1],1,1,null,0,0,null,0],"${id}",${ts},"${sg}"]`,
    ];
    const res = await fetch("https://news.google.com/_/DotsSplashUi/data/batchexecute", {
      method: "POST",
      cache: "no-store",
      headers: { "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8", "User-Agent": UA },
      body: "f.req=" + encodeURIComponent(JSON.stringify([[req]])),
      signal: AbortSignal.timeout(8000),
    });
    const parsed = JSON.parse((await res.text()).split("\n\n")[1]);
    const url = JSON.parse(parsed[0][2])[1];
    return typeof url === "string" && /^https?:\/\//.test(url) ? url : null;
  } catch {
    return null;
  }
}

// ── The article text ──────────────────────────────────────────────────────

const strip = (html: string) => decodeEntities(html.replace(/<[^>]+>/g, " ")).replace(/\s+/g, " ").trim();

interface PageText {
  paragraphs: string[];
  description: string;
}

async function fetchArticle(url: string): Promise<PageText | null> {
  try {
    const res = await fetch(url, {
      headers: {
        // SEC answers only clients that name themselves.
        "User-Agent": /^https:\/\/www\.sec\.gov\//.test(url) ? SEC_UA : UA,
        "Accept-Language": "en-US,en;q=0.9,ko;q=0.8,ja;q=0.7,zh;q=0.6",
      },
      redirect: "follow",
      cache: "no-store",
      signal: AbortSignal.timeout(8000),
    });
    if (!res.ok) return null;
    const buf = await res.arrayBuffer();
    // Some Korean / Japanese sites still serve EUC-KR / Shift_JIS.
    const head = new TextDecoder("latin1").decode(buf.slice(0, 4096));
    const charset = (
      res.headers.get("content-type")?.match(/charset=([\w-]+)/i)?.[1] ||
      head.match(/<meta[^>]+charset=["']?([\w-]+)/i)?.[1] ||
      "utf-8"
    ).toLowerCase();
    let html: string;
    try {
      html = new TextDecoder(charset).decode(buf);
    } catch {
      html = new TextDecoder("utf-8").decode(buf);
    }
    html = html.replace(/<(script|style|noscript|svg|nav|footer|header|aside)[\s\S]*?<\/\1>/gi, " ");
    const meta = (prop: string) =>
      html.match(new RegExp(`<meta[^>]+(?:property|name)=["']${prop}["'][^>]+content=["']([^"']*)`, "i"))?.[1] ||
      html.match(new RegExp(`<meta[^>]+content=["']([^"']*)["'][^>]+(?:property|name)=["']${prop}["']`, "i"))?.[1] ||
      "";
    const description = strip(meta("og:description") || meta("description"));
    let paragraphs = Array.from(html.matchAll(/<p[\s>][\s\S]*?<\/p>/gi), (m) => strip(m[0])).filter(
      (p) => p.length >= (/[぀-鿿가-힯]/.test(p) ? 20 : 50)
    );
    // Sites that set the story in <br>-separated text, and SEC filings (<div>/<font>).
    if (paragraphs.join("").length < 300) {
      const body = html.match(/<article[\s\S]*?<\/article>/i)?.[0] || html.match(/<body[\s\S]*<\/body>/i)?.[0];
      if (body) paragraphs = [strip(body)];
    }
    return { paragraphs, description };
  } catch {
    return null;
  }
}

// DART's viewer page (main.do) is a frame; each section of the filing is served
// by viewer.do with the ids the page's table of contents lists.
async function dartText(url: string): Promise<PageText | null> {
  try {
    const get = async (u: string) =>
      (await fetch(u, { headers: { "User-Agent": UA }, cache: "no-store", signal: AbortSignal.timeout(8000) })).text();
    const rcpNo = new URL(url).searchParams.get("rcpNo");
    const page = await get(url);
    const nodes = new Map<string, Record<string, string>>(); // "1" → {dcmNo, eleId, offset, length, dtd}
    for (const m of page.matchAll(/node(\d+)\['(dcmNo|eleId|offset|length|dtd)'\]\s*=\s*"([^"]*)"/g))
      nodes.set(m[1], { ...nodes.get(m[1]), [m[2]]: m[3] });
    let sections = [...nodes.values()].filter((n) => n.dcmNo && n.length && n.length !== "0").slice(0, 6);
    // Exchange (KRX) filings are one HTML document with no table of contents: the
    // page calls viewDoc("rcpNo", "dcmNo", "0", "0", "0", "HTML") once instead.
    if (!sections.length) {
      const m = page.match(/viewDoc\("\d+",\s*"(\d+)",\s*"(\d+)",\s*"(\d+)",\s*"(\d+)",\s*"([^"]+)"/);
      if (m) sections = [{ dcmNo: m[1], eleId: m[2], offset: m[3], length: m[4], dtd: m[5] }];
    }
    const texts = await Promise.all(
      sections.map((n) =>
        get(
          `https://dart.fss.or.kr/report/viewer.do?rcpNo=${rcpNo}&dcmNo=${n.dcmNo}&eleId=${n.eleId}` +
            `&offset=${n.offset}&length=${n.length}&dtd=${n.dtd}`
        )
          .then((h) => strip(h.replace(/<(script|style)[\s\S]*?<\/\1>/gi, " ")))
          .catch(() => "")
      )
    );
    const paragraphs = texts.filter(Boolean);
    return paragraphs.length ? { paragraphs, description: "" } : null;
  } catch {
    return null;
  }
}

// EDINET's viewer is a script app; the filing itself comes from the API as a zip
// whose XBRL/PublicDoc/*.htm files are the readable report.
async function edinetText(url: string): Promise<PageText | null> {
  const key = process.env.EDINET_API_KEY?.trim();
  const docId = url.split("?")[1];
  if (!key || !docId) return null;
  try {
    const res = await fetch(`https://api.edinet-fsa.go.jp/api/v2/documents/${docId}?type=1&Subscription-Key=${key}`, {
      cache: "no-store",
      signal: AbortSignal.timeout(15_000),
    });
    if (!res.ok || !/zip|octet/.test(res.headers.get("content-type") || "")) return null;
    const files = unzip(Buffer.from(await res.arrayBuffer()), (name) => /PublicDoc\/[^/]+\.html?$/.test(name));
    const paragraphs = files
      .sort((a, b) => a.name.localeCompare(b.name))
      .map((f) => strip(f.data.toString("utf8").replace(/<(script|style)[\s\S]*?<\/\1>/gi, " ")))
      .filter(Boolean);
    return paragraphs.length ? { paragraphs, description: "" } : null;
  } catch {
    return null;
  }
}

/** The entries of a zip archive whose names pass `want` (stored or deflated). */
function unzip(buf: Buffer, want: (name: string) => boolean): { name: string; data: Buffer }[] {
  let eocd = buf.length - 22; // end-of-central-directory record, at most 64 KB from the end
  while (eocd >= 0 && buf.readUInt32LE(eocd) !== 0x06054b50) eocd--;
  if (eocd < 0) return [];
  const out: { name: string; data: Buffer }[] = [];
  let p = buf.readUInt32LE(eocd + 16);
  for (let i = buf.readUInt16LE(eocd + 10); i > 0 && buf.readUInt32LE(p) === 0x02014b50; i--) {
    const method = buf.readUInt16LE(p + 10);
    const size = buf.readUInt32LE(p + 20);
    const nameLen = buf.readUInt16LE(p + 28);
    const local = buf.readUInt32LE(p + 42);
    const name = buf.toString("utf8", p + 46, p + 46 + nameLen);
    p += 46 + nameLen + buf.readUInt16LE(p + 30) + buf.readUInt16LE(p + 32);
    if (!want(name)) continue;
    const start = local + 30 + buf.readUInt16LE(local + 26) + buf.readUInt16LE(local + 28);
    const raw = buf.subarray(start, start + size);
    out.push({ name, data: method === 8 ? inflateRawSync(raw) : raw });
  }
  return out;
}

// ── Gemini ────────────────────────────────────────────────────────────────

const SUMMARY_RULES =
  `You summarize news articles and company filings for a US investor's news terminal. Use only the text given. ` +
  `Always write in English, translating if the source is in another language. ` +
  `Give 3-5 short bullet points, each starting with "- ", most important first: ` +
  `what happened, the key numbers, and the companies involved. No intro line, no opinion, no investment advice. ` +
  `Keep tickers as written and give companies their English names. ` +
  `If the text is only a headline, write a single bullet that restates it and nothing more.`;

async function gemini(req: SummaryRequest, source: string): Promise<string | null> {
  const text = await generate(SUMMARY_RULES, `Headline: ${req.title}\n\n${source}\n\nWrite the summary in English.`);
  if (!text || isEnglish(text)) return text;
  // The small model sometimes answers in the source's language (Japanese → Japanese)
  // anyway; translating its few lines is something it does reliably.
  const translated = await generate(
    `Translate the user's bullet points into English. Keep the "- " bullets, numbers and tickers; ` +
      `give companies their English names. Output only the bullets.`,
    text
  );
  return translated || text;
}

// ── Reading a source ──────────────────────────────────────────────────────

interface Source {
  url: string; // the article itself (Google News links resolved)
  page: PageText | null;
  body: string; // article text, capped
  description: string;
  text: string; // what Gemini reads: feed blurb + page description + article text
}

async function readSource(req: SummaryRequest, maxChars = MAX_ARTICLE_CHARS): Promise<Source> {
  const isGoogle = /^https:\/\/news\.google\.com\//.test(req.url);
  const url = (isGoogle && (await resolveGoogleNews(req.url))) || req.url;
  const page = url.startsWith("https://news.google.com/")
    ? null
    : url.startsWith("https://dart.fss.or.kr/")
      ? await dartText(url)
      : url.startsWith("https://disclosure2.edinet-fsa.go.jp/")
        ? await edinetText(url)
        : await fetchArticle(url);
  const body = (page?.paragraphs || []).join("\n").slice(0, maxChars);
  const description = page?.description || "";
  const text = [
    req.blurb && `Feed summary: ${req.blurb}`,
    description && description !== req.blurb && `Page description: ${description}`,
    body && `Article text:\n${body}`,
  ]
    .filter(Boolean)
    .join("\n\n");
  return { url, page, body, description, text };
}

const tagsOf = (req: SummaryRequest, src: Source) =>
  tagCompanies([req.title, req.blurb, src.description, src.body].join("\n"));

// ── Putting it together ───────────────────────────────────────────────────

export async function summarize(req: SummaryRequest): Promise<NewsSummary> {
  const src = await readSource(req);
  let summary = await gemini(req, src.text);
  let kind: NewsSummary["kind"] = "ai";
  if (!summary) {
    // No AI: the feed's blurb if it says something, else the article's lead.
    const lead = (src.page?.paragraphs || []).slice(0, 3).join("\n\n").slice(0, 900);
    if (req.blurb.length >= 80) [summary, kind] = [req.blurb, "feed"];
    else if (lead) [summary, kind] = [lead, "lead"];
    else if (src.description || req.blurb) [summary, kind] = [src.description || req.blurb, "feed"];
    else [summary, kind] = ["", "none"];
  }

  const { companies, others } = tagsOf(req, src);
  const tickers: Record<string, string | null> = {};
  for (const id of companies) tickers[id] = tickerOf(id);
  return { url: src.url, summary, kind, companies, tickers, others };
}

const BATCH_CHARS = 4000; // article text per source when several share one Gemini call

/** Summaries for several sources in ONE Gemini call (how the ingest job stays far
 *  inside the free tier). A source Gemini skipped comes back null. */
export async function summarizeMany(reqs: SummaryRequest[]): Promise<(Digest | null)[]> {
  const sources = await Promise.all(reqs.map((r) => readSource(r, BATCH_CHARS)));
  const out = await generate(
    SUMMARY_RULES +
      " The user sends a JSON object of numbered sources. Return a JSON object with the same keys, each value " +
      "that source's bullet points as one string, one bullet per line.",
    JSON.stringify(Object.fromEntries(sources.map((s, n) => [n, `Headline: ${reqs[n].title}\n\n${s.text}`]))),
    { maxTokens: 4096, json: true }
  );
  let obj: any = null;
  try {
    obj = JSON.parse(out || "");
  } catch {
    if (out) console.warn(`[news] digest answer was not JSON: ${out.slice(0, 120)}`);
  }
  return reqs.map((req, n) => {
    const summary = obj?.[n];
    if (typeof summary !== "string" || !summary.trim()) return null;
    const { companies, others } = tagsOf(req, sources[n]);
    return { summary: summary.trim(), url: sources[n].url, companies, others };
  });
}
