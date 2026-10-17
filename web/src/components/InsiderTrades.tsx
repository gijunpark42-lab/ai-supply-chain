"use client";

// InsiderTrades.tsx — "Insider trades" in the company panel (2026-10-17).
//
// Trades by officers, directors and large holders from the last 365 days, collected
// every night by a script from insider filings (SEC Form 4, DART …) into
// graph/insiders.json → /data/insiders.json. Not a signal: own file, own section.
//
// Open-market buys and sells are what readers look for, so they are listed first.
// Option exercises, tax withholding, grants, gifts and other codes are mostly
// mechanical; they sit under a toggle. Renders nothing when the company has no rows.

import { useEffect, useMemo, useState } from "react";
import { t, useLang } from "@/lib/i18n";
import {
  fmtCount,
  fmtDay,
  fmtMoney,
  fmtPrice,
  loadInsiders,
  useFeed,
  type InsiderTrade,
  type InsiderType,
} from "@/lib/companyFeeds";
import { DayChip, FeedHead, ShowAllToggle, SourceLink, SourcesLine, previewRows } from "./FeedParts";

const TYPE_LABEL: Record<InsiderType, string> = {
  buy: "Buy",
  sell: "Sell",
  option_exercise: "Option exercise",
  tax_withholding: "Tax withholding",
  grant: "Grant",
  gift: "Gift",
  other: "Other",
};

const isMarketTrade = (r: InsiderTrade) => r.type === "buy" || r.type === "sell";

function TradeRow({ r }: { r: InsiderTrade }) {
  const type = TYPE_LABEL[r.type] ? r.type : "other";
  // "12,345 shares @ $123.45 · $1.5M · holds 1,234,567 after"
  const shares = fmtCount(r.shares);
  // a grant or gift is filed at a price of $0: no "@ $0.00  $0" noise, only a real price / value is shown
  const price = r.price != null && r.price > 0 ? fmtPrice(r.price, r.currency) : "";
  const value = r.value != null && r.value > 0 ? fmtMoney(r.value, r.currency) : "";
  const after = fmtCount(r.owned_after);
  const qty = [shares && t("{n} shares", { n: shares }), price && "@ " + price].filter(Boolean).join(" ");
  return (
    <div className="np-fd-row">
      <div className="np-sig-head">
        <span
          className={"np-fd-type np-it-" + type}
          title={r.code ? t("Transaction code {code}", { code: r.code }) : undefined}
        >
          {t(TYPE_LABEL[type])}
        </span>
        <DayChip iso={r.date} title={r.filed ? t("filed {date}", { date: fmtDay(r.filed) }) : undefined} />
        <span className="np-it-who">{r.insider}</span>
        {r.role && <span className="np-it-role">{r.role}</span>}
        {r.plan_10b5_1 && (
          <span className="np-tag np-it-plan" title={t("Traded under a pre-arranged Rule 10b5-1 trading plan")}>
            {t("10b5-1 plan")}
          </span>
        )}
        <SourceLink source={r.source} url={r.url} />
      </div>
      {(qty || value || after) && (
        <div className="np-fd-line np-it-fig">
          {qty && <span>{qty}</span>}
          {value && <b className="np-fd-amt">{value}</b>}
          {after && <span className="np-it-after">{t("holds {n} after", { n: after })}</span>}
        </div>
      )}
    </div>
  );
}

// Count and total value of one side (buys or sells). Only rows in `currency` are
// summed, so a company that reports in two currencies never adds them up.
function side(rows: InsiderTrade[], type: "buy" | "sell", currency: string) {
  const list = rows.filter((r) => r.type === type);
  const total = list.reduce((s, r) => s + ((r.currency || "USD") === currency && r.value != null ? r.value : 0), 0);
  return { n: list.length, value: total > 0 ? fmtMoney(total, currency) : "" };
}

export default function InsiderTrades({ companyId }: { companyId: string }) {
  useLang(); // re-render on a language change
  const file = useFeed(loadInsiders);
  const [openMain, setOpenMain] = useState(false); // "Show all" on buys / sells
  const [showOther, setShowOther] = useState(false); // the collapsed non-market group
  const [openOther, setOpenOther] = useState(false); // "Show all" inside that group
  useEffect(() => {
    setOpenMain(false);
    setShowOther(false);
    setOpenOther(false);
  }, [companyId]);

  const rows = useMemo(
    () => [...(file?.companies?.[companyId] || [])].sort((a, b) => (b.date || "").localeCompare(a.date || "")),
    [file, companyId]
  );
  const market = useMemo(() => rows.filter(isMarketTrade), [rows]);
  const other = useMemo(() => rows.filter((r) => !isMarketTrade(r)), [rows]);
  if (!file || rows.length === 0) return null;

  const currency = (market[0] || rows[0]).currency || "USD";
  const buys = side(market, "buy", currency);
  const sells = side(market, "sell", currency);

  return (
    <section className="np-feed" aria-label={t("Insider trades")}>
      <FeedHead title={t("Insider trades")} hint={t("last 365 days")} updated={file.updated} />

      {market.length > 0 ? (
        <>
          <div className="np-it-sum">
            <span className="np-it-buy-n">
              {t("Buys")} <b>{buys.n}</b>
              {buys.value && " · " + buys.value}
            </span>
            <span className="np-it-sell-n">
              {t("Sells")} <b>{sells.n}</b>
              {sells.value && " · " + sells.value}
            </span>
          </div>
          {previewRows(market, openMain).map((r, i) => (
            <TradeRow r={r} key={r.url + "|" + r.insider + "|" + i} />
          ))}
          <ShowAllToggle total={market.length} open={openMain} onToggle={() => setOpenMain((o) => !o)} />
        </>
      ) : (
        <div className="np-empty">{t("No open-market buys or sells in the last 365 days.")}</div>
      )}

      {other.length > 0 && (
        <div className="np-it-other">
          <button className="np-linkbtn" onClick={() => setShowOther((s) => !s)} aria-expanded={showOther}>
            {showOther ? "▾ " : "▸ "}
            {t("Option exercises, tax withholding, grants and gifts ({n})", { n: other.length })}
          </button>
          {showOther && (
            <div className="np-it-other-list">
              {previewRows(other, openOther).map((r, i) => (
                <TradeRow r={r} key={r.url + "|" + r.insider + "|" + i} />
              ))}
              <ShowAllToggle total={other.length} open={openOther} onToggle={() => setOpenOther((o) => !o)} />
            </div>
          )}
        </div>
      )}

      <SourcesLine sources={file.sources} />
    </section>
  );
}
