// /api/news/summary?u=<article url>&t=<headline>&s=<feed blurb>
// — the English summary + related companies the /news terminal shows for a
// clicked headline or filing (lib/newsSummary.ts). Display only: nothing is stored.
//
// The CDN keeps each answer for a day, so an article is summarized once; a
// fallback answer given because Gemini refused (free-tier limit) is kept only
// 5 minutes so the next click tries again.

import { NextRequest, NextResponse } from "next/server";
import { cdnCache } from "@/lib/news";
import { summarize } from "@/lib/newsSummary";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(req: NextRequest) {
  const p = req.nextUrl.searchParams;
  const url = p.get("u") || "";
  if (!/^https?:\/\//.test(url)) return NextResponse.json({ error: "bad url" }, { status: 400 });

  const out = await summarize({
    url,
    title: (p.get("t") || "").slice(0, 400),
    blurb: (p.get("s") || "").slice(0, 1500),
  });
  const retrySoon = out.kind !== "ai" && !!process.env.GEMINI_API_KEY?.trim();
  return NextResponse.json(out, {
    headers: retrySoon ? cdnCache(300) : cdnCache(86400, 86400),
  });
}
