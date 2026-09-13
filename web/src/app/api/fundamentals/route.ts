// /api/fundamentals — valuation metrics (P/E, forward P/E, P/B, EV/EBITDA, ...) for a
// node's ticker. Free sources, no API key, no LLM. The market decides the primary source
// (Korea → Naver, Japan → Yahoo Japan, Taiwan → TWSE/TPEx, else Yahoo Finance) and
// Yahoo Finance fills any field the local source does not publish. See lib/fundamentals.ts.

import { NextRequest, NextResponse } from "next/server";
import { yahooSymbol } from "@/lib/yahoo";
import { empty, fill, localProvider, yahoo } from "@/lib/fundamentals";

export const runtime = "nodejs";

export async function GET(req: NextRequest) {
  const params = req.nextUrl.searchParams;
  const symbol = yahooSymbol(
    params.get("ticker") || params.get("symbol") || "",
    params.get("exchange")
  );
  if (!symbol) return NextResponse.json({ error: "no symbol" }, { status: 400 });

  const local = localProvider(symbol);
  // Run the local source and Yahoo in parallel; merge local first, Yahoo fills the gaps.
  const [a, b] = await Promise.all([local ? local(symbol) : null, yahoo(symbol)]);
  const out = fill(fill(empty(symbol), a), b);

  if (out.sources.length === 0) return NextResponse.json({ error: "no data" }, { status: 404 });
  out.as_of = new Date().toISOString().slice(0, 16).replace("T", " ");
  return NextResponse.json(out);
}
