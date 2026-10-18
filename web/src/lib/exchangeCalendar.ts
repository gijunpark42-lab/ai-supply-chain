// exchangeCalendar.ts — "is this stock's exchange shut for the WHOLE day today?"
//
// The weekend perp chip (components/WeekendPerpPrice.tsx) shows a 24/7
// Hyperliquid price only on days the home exchange does not trade at all:
// weekends and exchange holidays, judged in the EXCHANGE'S local time (Saturday
// in Seoul starts while it is still Friday in New York). It is NOT shown during
// a normal session or the ordinary overnight gap between two trading days.
//
// Holiday lists are full-day closures only (half days don't count) for 2026-2027.
// Extend them each year. An exchange WITHOUT a list here (China, Hong Kong ...)
// falls back to weekends only: on a local holiday the chip just stays hidden,
// which is the safe failure.

// NYSE / NASDAQ (same calendar). Saturday holidays move to Friday, Sunday ones to
// Monday — except New Year's Day 2028 (Sat), which NYSE does not move to Dec 31.
const NYSE = [
  "2026-01-01", // New Year's Day
  "2026-01-19", // Martin Luther King Jr. Day
  "2026-02-16", // Washington's Birthday
  "2026-04-03", // Good Friday
  "2026-05-25", // Memorial Day
  "2026-06-19", // Juneteenth
  "2026-07-03", // Independence Day (observed; Jul 4 is a Saturday)
  "2026-09-07", // Labor Day
  "2026-11-26", // Thanksgiving
  "2026-12-25", // Christmas
  "2027-01-01", // New Year's Day
  "2027-01-18", // Martin Luther King Jr. Day
  "2027-02-15", // Washington's Birthday
  "2027-03-26", // Good Friday
  "2027-05-31", // Memorial Day
  "2027-06-18", // Juneteenth (observed; Jun 19 is a Saturday)
  "2027-07-05", // Independence Day (observed; Jul 4 is a Sunday)
  "2027-09-06", // Labor Day
  "2027-11-25", // Thanksgiving
  "2027-12-24", // Christmas (observed; Dec 25 is a Saturday)
];

// KRX (KOSPI / KOSDAQ). Korea moves a holiday that hits a weekend to the next
// weekday ("substitute holiday") for most holidays; KRX also shuts on Dec 31.
const KRX = [
  "2026-01-01", // New Year's Day
  "2026-02-16", "2026-02-17", "2026-02-18", // Seollal (Lunar New Year)
  "2026-03-02", // Independence Movement Day (substitute; Mar 1 is a Sunday)
  "2026-05-01", // Labor Day
  "2026-05-05", // Children's Day
  "2026-05-25", // Buddha's Birthday (substitute; May 24 is a Sunday)
  "2026-06-03", // Local elections
  "2026-08-17", // Liberation Day (substitute; Aug 15 is a Saturday)
  "2026-09-24", "2026-09-25", // Chuseok (Sep 26 is a Saturday, no substitute)
  "2026-10-05", // National Foundation Day (substitute; Oct 3 is a Saturday)
  "2026-10-09", // Hangul Day
  "2026-12-25", // Christmas
  "2026-12-31", // Year-end closing day
  "2027-01-01", // New Year's Day
  "2027-02-08", "2027-02-09", // Seollal (Feb 6-7 are a weekend; Feb 9 = substitute)
  "2027-03-01", // Independence Movement Day
  "2027-05-05", // Children's Day
  "2027-05-13", // Buddha's Birthday
  "2027-08-16", // Liberation Day (substitute; Aug 15 is a Sunday)
  "2027-09-14", "2027-09-15", "2027-09-16", // Chuseok
  "2027-10-04", // National Foundation Day (substitute; Oct 3 is a Sunday)
  "2027-10-11", // Hangul Day (substitute; Oct 9 is a Saturday)
  "2027-12-27", // Christmas (substitute; Dec 25 is a Saturday)
  "2027-12-31", // Year-end closing day
];

// JPX (Tokyo Stock Exchange): Japan's national holidays plus Jan 2-3 and Dec 31.
const JPX = [
  "2026-01-01", "2026-01-02", // New Year
  "2026-01-12", // Coming of Age Day
  "2026-02-11", // National Foundation Day
  "2026-02-23", // Emperor's Birthday
  "2026-03-20", // Vernal Equinox
  "2026-04-29", // Showa Day
  "2026-05-04", "2026-05-05", "2026-05-06", // Golden Week (May 6 = substitute for May 3)
  "2026-07-20", // Marine Day
  "2026-08-11", // Mountain Day
  "2026-09-21", "2026-09-22", "2026-09-23", // Respect for the Aged, bridge day, Autumnal Equinox
  "2026-10-12", // Sports Day
  "2026-11-03", // Culture Day
  "2026-11-23", // Labor Thanksgiving Day
  "2026-12-31", // Year-end
  "2027-01-01", // New Year (Jan 2-3 are a weekend)
  "2027-01-11", // Coming of Age Day
  "2027-02-11", // National Foundation Day
  "2027-02-23", // Emperor's Birthday
  "2027-03-22", // Vernal Equinox (substitute; Mar 21 is a Sunday)
  "2027-04-29", // Showa Day
  "2027-05-03", "2027-05-04", "2027-05-05", // Golden Week
  "2027-07-19", // Marine Day
  "2027-08-11", // Mountain Day
  "2027-09-20", // Respect for the Aged Day
  "2027-09-23", // Autumnal Equinox
  "2027-10-11", // Sports Day
  "2027-11-03", // Culture Day
  "2027-11-23", // Labor Thanksgiving Day
  "2027-12-31", // Year-end
];

interface Calendar {
  tz: string; // IANA time zone the exchange keeps its calendar in
  holidays: Set<string>; // "YYYY-MM-DD" full-day closures
}

const CALENDARS: Record<string, Calendar> = {
  NYSE: { tz: "America/New_York", holidays: new Set(NYSE) },
  KRX: { tz: "Asia/Seoul", holidays: new Set(KRX) },
  JPX: { tz: "Asia/Tokyo", holidays: new Set(JPX) },
  CN: { tz: "Asia/Shanghai", holidays: new Set<string>() }, // weekends only (no list yet)
  HK: { tz: "Asia/Hong_Kong", holidays: new Set<string>() }, // weekends only (no list yet)
};

// The exchange labels used in company_metadata → which calendar they follow.
const EXCHANGE_CALENDAR: Record<string, string> = {
  NASDAQ: "NYSE",
  NYSE: "NYSE",
  "NYSE American": "NYSE",
  KOSPI: "KRX",
  KRX: "KRX",
  KOSDAQ: "KRX",
  TSE: "JPX",
  SSE: "CN",
  SZSE: "CN",
  HKEX: "HK",
};

function calendarFor(exchange: string | null): Calendar | null {
  const key = exchange ? EXCHANGE_CALENDAR[exchange] : undefined;
  return key ? CALENDARS[key] : null;
}

/** The exchange's IANA time zone (null for an exchange not listed above). */
export function exchangeTz(exchange: string | null): string | null {
  return calendarFor(exchange)?.tz ?? null;
}

/** The calendar date ("YYYY-MM-DD") and short weekday ("Sat") in a time zone. */
function localDay(tz: string, when: Date): { date: string; weekday: string } {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: tz,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    weekday: "short",
  }).formatToParts(when);
  const get = (type: string) => parts.find((p) => p.type === type)?.value || "";
  return { date: `${get("year")}-${get("month")}-${get("day")}`, weekday: get("weekday") };
}

/**
 * True when the exchange does not trade at all on today's local date: a
 * weekend or a listed holiday. False for an unknown exchange (never claim a
 * market is closed when we don't know its calendar).
 */
export function closedAllDay(exchange: string | null, when: Date = new Date()): boolean {
  const cal = calendarFor(exchange);
  if (!cal) return false;
  const { date, weekday } = localDay(cal.tz, when);
  return weekday === "Sat" || weekday === "Sun" || cal.holidays.has(date);
}
