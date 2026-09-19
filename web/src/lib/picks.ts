// picks.ts — the two ranked baskets the Picks tab tracks.
//
// These came out of a one-quarter screen (hold 2026-09-18 → ~2026-12-18) run
// across every listed company in the graph: 178 US-listed names and 35
// Korea-listed names, each scored on guided sequential acceleration, backlog /
// sold-out visibility, drawdown versus the 6-month high, and whether a report
// lands inside the holding window.
//
// `entry` is the 2026-09-18 CLOSE (US 16:00 ET, Korea 15:30 KST) and is FROZEN
// on purpose: it is the baseline every return on the page is measured from, so
// it must never be recomputed from live data.

export interface Pick {
  rank: number;
  company: string; // must match the graph node id, so a click opens its NodePanel
  ticker: string; // as displayed
  symbol: string; // Yahoo symbol for /api/quotes
  exchange: string;
  entry: number; // 2026-09-18 close
  currency: "USD" | "KRW";
  note: string; // the one line the pick rests on
}

export interface Basket {
  key: string;
  label: string;
  blurb: string;
  picks: Pick[];
}

// Every pick once, keyed by Yahoo symbol. Rank is NOT stored here: it comes from
// the position in the ordered lists below, so reordering can never desync it.
const P: Record<string, Omit<Pick, "rank">> = {
  "ALAB": { company: "Astera Labs", ticker: "ALAB", symbol: "ALAB", exchange: "NASDAQ", entry: 303.25, currency: "USD",
    note: "Q3 guided +40% QoQ at ~72% gross margin; Scorpio X engagements went from 10 to the high teens." },
  "MTSI": { company: "MACOM", ticker: "MTSI", symbol: "MTSI", exchange: "NASDAQ", entry: 275.86, currency: "USD",
    note: "FQ4 guided +23% QoQ; book-to-bill a record 1.6 (1.3 → 1.5 → 1.6); operating margin 31.5% → ~37%." },
  "WDC": { company: "Western Digital", ticker: "WDC", symbol: "WDC", exchange: "NASDAQ", entry: 441.36, currency: "USD",
    note: "Guided +45% YoY; the vast majority of 2027 is under LTA; revenue is gated by supply, not demand." },
  "SNDK": { company: "Sandisk", ticker: "SNDK", symbol: "SNDK", exchange: "NASDAQ", entry: 1791.82, currency: "USD",
    note: "Revenue +51% QoQ at 84.6% gross margin; eight multi-year agreements running out to five years." },
  "MU": { company: "Micron", ticker: "MU", symbol: "MU", exchange: "NASDAQ", entry: 1015.80, currency: "USD",
    note: "Record $41.5B (+74% QoQ) at 84.9% gross margin; management calls 2027 tighter than 2026." },
  "AVGO": { company: "Broadcom", ticker: "AVGO", symbol: "AVGO", exchange: "NASDAQ", entry: 357.61, currency: "USD",
    note: "Q4 AI revenue guided +30% QoQ to $21.7B; FY27 AI ~$115B; 2027 wafers, memory and substrates locked in." },
  "COHR": { company: "Coherent", ticker: "COHR", symbol: "COHR", exchange: "NYSE", entry: 317.36, currency: "USD",
    note: "FY27 fully booked with take-or-pay LTAs; backlog runs through end-CY2027; next quarter guided +12% QoQ." },
  "CIEN": { company: "Ciena", ticker: "CIEN", symbol: "CIEN", exchange: "NYSE", entry: 348.80, currency: "USD",
    note: "Backlog $8.5B heading above $10B; FY27 guided to a minimum of 30% growth; components secured to 2029." },
  "AXTI": { company: "AXT", ticker: "AXTI", symbol: "AXTI", exchange: "NASDAQ", entry: 70.03, currency: "USD",
    note: "Q3 ~+39% QoQ and already permit-secured; indium phosphide substrates are the optical bottleneck." },
  "FN": { company: "Fabrinet", ticker: "FN", symbol: "FN", exchange: "NYSE", entry: 388.55, currency: "USD",
    note: "Six straight quarters of accelerating growth; guided +43% YoY; capacity going from $5.8B to $9.8B." },
  "TTMI": { company: "TTM Technologies", ticker: "TTMI", symbol: "TTMI", exchange: "NASDAQ", entry: 117.97, currency: "USD",
    note: "Q3 guided +12% QoQ; book-to-bill 1.49; 90-day backlog +81%; data-centre revenue +91%." },
  "MKSI": { company: "MKS Instruments", ticker: "MKSI", symbol: "MKSI", exchange: "NASDAQ", entry: 252.08, currency: "USD",
    note: "Q3 guide implies semiconductor growth accelerating past +50% YoY, with visibility through 2027." },
  "CRDO": { company: "Credo", ticker: "CRDO", symbol: "CRDO", exchange: "NASDAQ", entry: 175.89, currency: "USD",
    note: "Revenue +115% YoY; management guided the shape of FY27 at +20% then +30% QoQ into the back half." },
  "MPWR": { company: "Monolithic Power Systems", ticker: "MPWR", symbol: "MPWR", exchange: "NASDAQ", entry: 1217.80, currency: "USD",
    note: "Q3 guided +17% QoQ; enterprise data +45% QoQ; book-to-bill well above 1 and a $1B buyback." },
  "AMAT": { company: "Applied Materials", ticker: "AMAT", symbol: "AMAT", exchange: "NASDAQ", entry: 444.57, currency: "USD",
    note: "2026 growth guide raised three times — above 20%, then 30%, then approaching 40%." },
  "000660.KS": { company: "SK Hynix", ticker: "000660", symbol: "000660.KS", exchange: "KOSPI", entry: 1857000, currency: "KRW",
    note: "Q2 revenue +50.9% QoQ at a 76% operating margin with fabs at 100%; NVIDIA sees memory pricing rising into 2027." },
  "009150.KS": { company: "Samsung Electro-Mechanics", ticker: "009150", symbol: "009150.KS", exchange: "KOSPI", entry: 1388000, currency: "KRW",
    note: "Three supply contracts starting 2027 (Si capacitor $1,035M, MLCC $294M, MLCC $779M); MLCC ASP +13.9%." },
  "005930.KS": { company: "Samsung", ticker: "005930", symbol: "005930.KS", exchange: "KOSPI", entry: 261000, currency: "KRW",
    note: "Q2 revenue +28% QoQ at a 52% operating margin, memory at 100% utilisation; HBM4 above half of HBM from Q3." },
};

// Order = rank. Re-ranked on the real 2026-09-18 closes (the first pass had used
// 09-17 closes for US names): the 09-18 rebound cut the drawdown most for Sandisk
// (+11%) and Coherent (+7%), so they moved down; membership did not change.
const US_ORDER = ["ALAB", "MTSI", "WDC", "AVGO", "CIEN", "MU", "SNDK", "AXTI", "FN", "TTMI", "COHR", "MKSI", "CRDO", "MPWR", "AMAT"];
const GLOBAL_ORDER = ["ALAB", "000660.KS", "MTSI", "WDC", "AVGO", "CIEN", "MU", "SNDK", "AXTI", "FN", "009150.KS", "TTMI", "COHR", "005930.KS", "MKSI"];

const ranked = (order: string[]): Pick[] => order.map((sym, i) => ({ rank: i + 1, ...P[sym] }));
const US = ranked(US_ORDER);
const GLOBAL = ranked(GLOBAL_ORDER);

export const BASKETS: Basket[] = [
  {
    key: "us",
    label: "US 15",
    blurb: "Ranked from every US-listed company in the graph (178 names).",
    picks: US,
  },
  {
    key: "global",
    label: "US + Korea 15",
    blurb: "The same screen run across 178 US-listed and 35 Korea-listed names (213 total).",
    picks: GLOBAL,
  },
];

// The baseline every return on the page is measured from.
export const ENTRY_DATE = "2026-09-18";

// Every distinct symbol the tab has to quote.
export const ALL_SYMBOLS = Array.from(
  new Set(BASKETS.flatMap((b) => b.picks.map((p) => p.symbol)))
);

// ── Formatting shared by the Top-15 table and the full screened list ────────
export function money(v: number | null | undefined, cur: "USD" | "KRW"): string {
  if (v == null) return "—";
  return cur === "KRW"
    ? "₩" + Math.round(v).toLocaleString("en-US")
    : "$" + v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export function pct(v: number | null | undefined, digits = 2): string {
  if (v == null) return "—";
  return (v >= 0 ? "+" : "") + v.toFixed(digits) + "%";
}

// CSS suffix for a signed number: " up" / " down" / " flat" ("" when unknown).
export const tone = (v: number | null | undefined) =>
  v == null ? "" : v > 0 ? " up" : v < 0 ? " down" : " flat";

export interface Quote {
  price: number | null;
  prev_close: number | null;
  day_pct: number | null;
  currency: string | null;
  market_state: string | null;
  quote_time: number | null;
}
export type Quotes = Record<string, Quote>;
