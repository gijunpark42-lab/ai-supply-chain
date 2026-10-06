// yahoo.ts — shared Yahoo Finance symbol mapping (used by /api/quote and
// /api/earnings). Turns the project's (ticker, exchange) into a Yahoo symbol.

const SYMBOL_OVERRIDE: Record<string, string> = {
  BESI: "BESI.AS",
  "6600.T": "285A.T", // Kioxia listed under code 285A
  "222800": "222800.KQ", // Simmtech (KOSDAQ, filed as KRX)
  "033170.KS": "033170.KQ", // Signetics (KOSDAQ)
  "RR.": "RR.L", // Rolls-Royce: the LSE code has a trailing dot
};

// Exchange → Yahoo suffix for tickers stored WITHOUT one. US listings need none;
// most Asian tickers in company_metadata already carry their suffix (.TW/.T/.HK).
const EXCHANGE_SUFFIX: Record<string, string> = {
  TSE: ".T",
  KOSPI: ".KS",
  KRX: ".KS",
  KOSDAQ: ".KQ", // KOSDAQ is .KQ on Yahoo, NOT .KS
  TWSE: ".TW",
  SZSE: ".SZ",
  XETRA: ".DE",
  AMS: ".AS",
  "Euronext Amsterdam": ".AS",
  EPA: ".PA",
  "Euronext Paris": ".PA",
  MIL: ".MI",
  STO: ".ST",
  "OMX Stockholm": ".ST",
  "OMX Helsinki": ".HE",
  OSE: ".OL",
  SIX: ".SW",
  HKEX: ".HK",
  VIE: ".VI",
  LSE: ".L",
  IDX: ".JK",
};

// US lines (ADRs, NY-registry shares, OTC ADRs) → the home listing. Market cap is
// valued on the home shares, so an ADR premium (TSM trades well above 2330.TW) never
// leaks into the company's size. US-only listings of foreign companies stay as they are.
const HOME_LISTING: Record<string, string> = {
  TSM: "2330.TW",
  ASX: "3711.TW",
  UMC: "2303.TW",
  IMOS: "8150.TW",
  BABA: "9988.HK",
  BIDU: "9888.HK",
  GDS: "9698.HK",
  KC: "3896.HK",
  NVO: "NOVO-B.CO",
  SNY: "SAN.PA",
  AZN: "AZN.L",
  SHEL: "SHEL.L",
  RHHBY: "ROP.SW", // Roche non-voting equity (Genussschein); ROG.SW returns nothing
  BAYRY: "BAYN.DE",
  NOK: "NOKIA.HE",
  STM: "STMPA.PA",
  ASML: "ASML.AS",
};

export function homeSymbol(symbol: string): string {
  return HOME_LISTING[symbol] || symbol;
}

export function yahooSymbol(
  ticker?: string | null,
  exchange?: string | null
): string | null {
  const t = (ticker || "").trim();
  if (!t) return null;
  if (SYMBOL_OVERRIDE[t]) return SYMBOL_OVERRIDE[t];
  if (t.includes(".")) return t; // already carries a Yahoo suffix
  const suf = exchange ? EXCHANGE_SUFFIX[exchange] : undefined;
  if (suf) return t + suf;
  if (/^\d+$/.test(t)) return t + ".KS"; // legacy fallback: bare numeric = KRX
  return t; // plain US / ADR ticker works as-is
}
