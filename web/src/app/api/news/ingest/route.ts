// /api/news/ingest — the /news terminal's background job, run by Vercel Cron every
// 5 minutes (vercel.json): rates the new Top News stories and summarizes the News /
// Filings items that are new since the last run (lib/digests.ts, lib/top.ts).
// Display only: it writes ratings and summaries to the Runtime Cache, nothing else.
//
// Vercel Cron sends "Authorization: Bearer $CRON_SECRET"; anything else is turned
// away, so no one can make it spend the DART / Gemini allowances. Locally (no
// CRON_SECRET, not on Vercel) it runs for anyone.

import { NextRequest, NextResponse } from "next/server";
import { ingest } from "@/lib/digests";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 300;

export async function GET(req: NextRequest) {
  const secret = process.env.CRON_SECRET?.trim();
  const allowed = secret ? req.headers.get("authorization") === `Bearer ${secret}` : !process.env.VERCEL;
  if (!allowed) return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  const result = await ingest();
  console.log(`[news] ingest: ${JSON.stringify(result)}`);
  return NextResponse.json(result, { headers: { "Cache-Control": "no-store" } });
}
